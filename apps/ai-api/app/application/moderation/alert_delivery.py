"""The only caller of Telegram's three outbound methods (`contracts/alerting.md` §4, §5 B7, §6;
D-TG-215, D-TG-227).

- `deliver` posts one alert at most once (V1-V6): a guarded claim, the re-check and the destination
  read in the claiming transaction, the send outside any transaction, then the record.
- `refresh` edits a posted alert when its render state changed (U1-U5).
- `answer_press` answers a press (B7), after its guard.

Every call is preceded by a runtime guard: a send goes only to the designated, unmonitored
destination; an edit only to the alert's own posted chat, which must not be monitored; an answer
only to a press whose message is in no monitored chat (N1). No log line carries an excerpt or a
rendered text (V7): the keys are `alert_id`, `chat_id` and `incident_id`.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alert_render import excerpt_shown, render_alert, render_state
from app.application.moderation.alerting import (
    AlertRef,
    RenderSettings,
    build_render_input,
    load_alert,
    subject_live,
)
from app.domain.moderation.alerting import MAX_DELIVERY_ATTEMPTS, MAX_EDIT_ATTEMPTS, SubjectType
from app.infrastructure.models_moderation import alerts, telegram_chats
from app.providers.telegram.client import TelegramProvider
from app.providers.telegram.errors import (
    TelegramCallbackExpiredError,
    TelegramError,
    TelegramMessageGoneError,
    TelegramOutcomeUnknownError,
    TelegramRejectedError,
)

logger = logging.getLogger(__name__)

DESTINATION_MIGRATED = "destination_migrated"
OUTBOUND_REFUSED = "outbound_refused"


class OutboundRefusedError(RuntimeError):
    """A send or edit addressed somewhere the contract forbids (N1). Never expected: D2 is a
    database constraint, so this is the second wall, not the first."""


class DeliveryOutcome(enum.StrEnum):
    SENT = "sent"
    NOT_CLAIMED = "not_claimed"  # V1: nothing to do (already sent, final, suppressed, …)
    NOT_SENT = "not_sent"  # V2: no destination, or the subject ended
    RETRY = "retry"  # V5: failed, another attempt is allowed
    FAILED = "failed"  # V5: failed and final


class RefreshOutcome(enum.StrEnum):
    UNCHANGED = "unchanged"
    EDITED = "edited"
    FINALISED = "finalised"  # ended with nothing new to say: `final_at` set, no edit
    GONE = "gone"  # U3: deleted in Telegram, marked final
    FAILED = "failed"  # U3: recorded in `last_edit_*`, retried by the next evaluation
    REFUSED = "refused"  # N1: the posted chat is now monitored; never edited again
    SKIPPED = "skipped"  # not sent, or past `MAX_EDIT_ATTEMPTS`


@dataclass(frozen=True)
class Destination:
    id: int
    chat_id: int


# --- the guards (D-TG-227) ---


async def destination(session: AsyncSession) -> Destination | None:
    """The designated destination (D1), read in the caller's transaction. A designated row that
    is monitored is refused outright, whatever D2 says."""
    row = (
        await session.execute(
            sa.select(
                telegram_chats.c.id, telegram_chats.c.chat_id, telegram_chats.c.is_monitored
            ).where(telegram_chats.c.is_alert_destination.is_(True))
        )
    ).one_or_none()
    if row is None:
        return None
    if row.is_monitored:
        raise OutboundRefusedError("the alert destination is monitored")
    return Destination(id=int(row.id), chat_id=int(row.chat_id))


async def guard_send_target(session: AsyncSession, chat_id: int) -> None:
    """V3: a send's `chat_id` must be the destination's, and the destination unmonitored."""
    target = await destination(session)
    if target is None or target.chat_id != chat_id:
        raise OutboundRefusedError("a send is addressed to a chat that is not the destination")


async def guard_edit_target(session: AsyncSession, alert: AlertRef, chat_id: int) -> None:
    """U2: an edit's target must be the alert's own posted chat, and no monitored chat."""
    if alert.sent_chat_id is None or chat_id != alert.sent_chat_id:
        raise OutboundRefusedError("an edit is addressed to a chat the alert was not posted in")
    monitored = (
        await session.execute(
            sa.select(
                sa.exists().where(
                    telegram_chats.c.chat_id == chat_id, telegram_chats.c.is_monitored.is_(True)
                )
            )
        )
    ).scalar_one()
    if monitored:
        raise OutboundRefusedError("an edit is addressed to a monitored chat")


async def guard_answer_target(session: AsyncSession, chat_id: int | None) -> None:
    """B7: a press is answered only when its message's chat is not monitored (N1). A callback
    with no message is addressed to no chat."""
    if chat_id is None:
        return
    monitored = (
        await session.execute(
            sa.select(
                sa.exists().where(
                    telegram_chats.c.chat_id == chat_id, telegram_chats.c.is_monitored.is_(True)
                )
            )
        )
    ).scalar_one()
    if monitored:
        raise OutboundRefusedError("an answer is addressed to a press in a monitored chat")


def _log_extra(alert: AlertRef, chat_id: int | None = None) -> dict[str, Any]:
    extra: dict[str, Any] = {"alert_id": alert.id}
    if chat_id is not None:
        extra["chat_id"] = chat_id
    if alert.subject_type is SubjectType.INCIDENT:
        extra["incident_id"] = alert.subject_id
    return extra


# --- delivery (V1-V6) ---

_CLAIM = sa.text(
    """
UPDATE alerts
SET delivery_status = 'sending', attempts = attempts + 1
WHERE id = :id
  AND delivery_status IN ('pending', 'failed')
  AND attempts < :max_attempts
  AND last_error_category IS DISTINCT FROM 'telegram_outcome_unknown'
RETURNING *
"""
)


def _failure_category(exc: TelegramError) -> tuple[str, bool]:
    """V5: the category to record and whether another attempt is allowed. A connect-phase
    failure, a 5xx and an exhausted 429 are retryable; an unknown outcome never is (D-TG-215); a
    migrated destination is final under its own category."""
    if isinstance(exc, TelegramRejectedError) and exc.migrate_to_chat_id is not None:
        return DESTINATION_MIGRATED, False
    if isinstance(exc, TelegramOutcomeUnknownError):
        return exc.category, False
    return exc.category, exc.retryable


async def deliver(
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider,
    alert_id: int,
    settings: RenderSettings,
) -> DeliveryOutcome:
    """Posts one alert at most once. The claim commits `sending` before the send, so a crash
    mid-send leaves an alert that is never claimed again rather than one posted twice (N3)."""
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    _CLAIM, {"id": alert_id, "max_attempts": MAX_DELIVERY_ATTEMPTS}
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            await session.rollback()
            return DeliveryOutcome.NOT_CLAIMED
        alert = AlertRef.from_row(row)

        target = await destination(session)
        reason: str | None = None
        if target is None:
            reason = "no_destination"
        elif not await subject_live(session, alert):
            reason = "subject_ended"
        if reason is not None:
            await session.execute(
                alerts.update()
                .where(alerts.c.id == alert.id)
                .values(delivery_status="not_sent", not_sent_reason=reason)
            )
            await session.commit()
            logger.info("alert not sent: %s", reason, extra=_log_extra(alert))
            return DeliveryOutcome.NOT_SENT
        assert target is not None

        await guard_send_target(session, target.chat_id)
        data = await build_render_input(session, alert, settings)
        text, markup = render_alert(data)
        state = render_state(data)
        shown = excerpt_shown(data)
        await session.commit()

    try:
        message_id = await client.send_message(
            chat_id=target.chat_id, text=text, reply_markup=markup
        )
    except TelegramError as exc:
        category, retryable = _failure_category(exc)
        async with session_factory() as session:
            await session.execute(
                alerts.update()
                .where(alerts.c.id == alert.id, alerts.c.delivery_status == "sending")
                .values(
                    delivery_status="failed",
                    last_error_category=category,
                    last_error_at=sa.func.now(),
                )
            )
            await session.commit()
        attempts = int(row["attempts"])
        final = not retryable or attempts >= MAX_DELIVERY_ATTEMPTS
        logger.warning(
            "alert delivery failed: %s (attempt %d%s)",
            category,
            attempts,
            ", final" if final else "",
            extra=_log_extra(alert, target.chat_id),
        )
        return DeliveryOutcome.FAILED if final else DeliveryOutcome.RETRY

    async with session_factory() as session:
        await session.execute(
            alerts.update()
            .where(alerts.c.id == alert.id)
            .values(
                delivery_status="sent",
                sent_chat_id=target.chat_id,
                sent_message_id=message_id,
                delivered_at=sa.func.now(),
                rendered_state=state,
                excerpt_shown=shown,
                final_at=None,
            )
        )
        await session.commit()
    logger.info("alert sent", extra=_log_extra(alert, target.chat_id))
    return DeliveryOutcome.SENT


# --- edits (U1-U5) ---


async def refresh(
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider,
    alert_id: int,
    settings: RenderSettings,
) -> RefreshOutcome:
    """Re-renders a posted alert from the derived state and edits it when its render state
    changed. An ended subject's keyboard is removed and `final_at` set (U2). No state or figure
    changes (U6): only the alert's own edit columns are written."""
    async with session_factory() as session:
        alert = await load_alert(session, alert_id)
        if (
            alert is None
            or alert.delivery_status != "sent"
            or alert.sent_chat_id is None
            or alert.sent_message_id is None
            or (alert.final_at is not None and not alert.excerpt_shown)
        ):
            return RefreshOutcome.SKIPPED
        data = await build_render_input(session, alert, settings)
        live = await subject_live(session, alert)
        state = render_state(data)
        shown = excerpt_shown(data)
        ended_now = not live and alert.final_at is None
        if state == alert.rendered_state:
            if not ended_now:
                return RefreshOutcome.UNCHANGED
            await session.execute(
                alerts.update().where(alerts.c.id == alert.id).values(final_at=sa.func.now())
            )
            await session.commit()
            return RefreshOutcome.FINALISED
        try:
            await guard_edit_target(session, alert, alert.sent_chat_id)
        except OutboundRefusedError:
            # The alert's group has since become monitored (a former destination re-purposed):
            # it may never be addressed again (N1). Recorded once, and the scan stops following
            # it, rather than refusing on every tick.
            await session.execute(
                alerts.update()
                .where(alerts.c.id == alert.id)
                .values(
                    edit_attempts=MAX_EDIT_ATTEMPTS,
                    last_edit_at=sa.func.now(),
                    last_edit_error_category=OUTBOUND_REFUSED,
                )
            )
            await session.commit()
            logger.warning(
                "alert edit refused: its chat is monitored", extra=_log_extra(alert)
            )
            return RefreshOutcome.REFUSED
        text, markup = render_alert(data)
        await session.commit()

    chat_id, message_id = alert.sent_chat_id, alert.sent_message_id
    try:
        await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=None if not live else markup,
        )
    except TelegramMessageGoneError as exc:
        async with session_factory() as session:
            await session.execute(
                alerts.update()
                .where(alerts.c.id == alert.id)
                .values(
                    final_at=sa.func.coalesce(alerts.c.final_at, sa.func.now()),
                    excerpt_shown=False,
                    last_edit_at=sa.func.now(),
                    last_edit_error_category=exc.category,
                )
            )
            await session.commit()
        logger.info("alert gone from its chat; marked final", extra=_log_extra(alert, chat_id))
        return RefreshOutcome.GONE
    except TelegramError as exc:
        async with session_factory() as session:
            await session.execute(
                alerts.update()
                .where(alerts.c.id == alert.id)
                .values(
                    edit_attempts=alerts.c.edit_attempts + 1,
                    last_edit_at=sa.func.now(),
                    last_edit_error_category=exc.category,
                )
            )
            await session.commit()
        logger.warning(
            "alert edit failed: %s", exc.category, extra=_log_extra(alert, chat_id)
        )
        return RefreshOutcome.FAILED

    async with session_factory() as session:
        values: dict[str, Any] = {
            "rendered_state": state,
            "excerpt_shown": shown,
            "last_edit_at": sa.func.now(),
            "edit_attempts": 0,
            "last_edit_error_category": None,
        }
        if not live:
            values["final_at"] = sa.func.coalesce(alerts.c.final_at, sa.func.now())
        await session.execute(alerts.update().where(alerts.c.id == alert.id).values(**values))
        await session.commit()
    logger.info("alert edited", extra=_log_extra(alert, chat_id))
    return RefreshOutcome.EDITED


# --- answers (B7) ---


async def answer_press(
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider,
    *,
    chat_id: int | None,
    callback_query_id: str,
    text: str,
) -> bool:
    """Answers one press after the guard: never a press whose message is in a monitored chat."""
    async with session_factory() as session:
        try:
            await guard_answer_target(session, chat_id)
        except OutboundRefusedError:
            logger.warning(
                "press answer refused: its chat is monitored", extra={"chat_id": chat_id}
            )
            return False
    return await answer(client, callback_query_id=callback_query_id, text=text)


async def answer(client: TelegramProvider, *, callback_query_id: str, text: str) -> bool:
    """Answers one press. A press too old to answer, or an answer whose outcome is unknown, is
    logged by category and ignored: the act is already recorded and the alert's own edit tells the
    rest. Any other failure propagates, so the actor may retry."""
    try:
        await client.answer_callback_query(callback_query_id=callback_query_id, text=text)
    except (TelegramCallbackExpiredError, TelegramOutcomeUnknownError) as exc:
        logger.info("press answer skipped: %s", exc.category)
        return False
    return True
