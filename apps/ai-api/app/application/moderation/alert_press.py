"""A button press in the alert group (`contracts/alerting.md` §5 B1-B6; D-TG-217, D-TG-219).

`derive_alert_press(update_row_id)` turns one captured `callback_query` into at most one recorded
act and an outcome:

- **B1, the gate.** The pressed message must be an alert's own `(sent_chat_id, sent_message_id)`
  (`uq_alerts_posted`), and the data must be `a:<that alert's id>:<h|f|t>`, with `h`/`f` only on an
  incident and `t` only on a question. The data alone is never trusted (N6).
- **B2, the presser.** `from.id` must map, through `telegram_users`, to a declared moderator who is
  active and was declared at or before the press (N7). Nobody else's press records anything. No
  identity is written from the alert group: nothing there is measured (D3).
- **B3, the instant.** The act's `occurred_at` is the update's `received_at`.
- **B4, incident acts.** Under `incident_lock`, an ended incident records nothing; otherwise
  `alert_handled` (a confirmation) or `alert_false_positive`, linked to the incident and the alert.
- **B5, takes.** Under the source chat's `chat_lock`, an item no longer open records nothing;
  otherwise `alert_take`. Assignment is the assignee view's decision (FR-557), read back here
  only to choose the answer.
- **B6, idempotence.** One act per update (`uq_moderation_actions_source_update`). A re-run finds
  its own act first and returns the same outcome.

Every act's `telegram_chat_id` is the **source** group's, never the alert group's. Nothing here
calls Telegram (B8): `press_answer` only composes the answer, which `alert_delivery` sends.
Logs carry `alert_id`, `incident_id` and `update_id`, never a name or a text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alert_render import answer_text
from app.application.moderation.alerting import AlertRef
from app.application.moderation.assignments import team_at
from app.application.moderation.locks import chat_lock, incident_lock
from app.domain.moderation.alerting import (
    ACT_KIND,
    ACTIONS_FOR,
    PressAction,
    PressOutcome,
    SubjectType,
    decode_callback,
)
from app.infrastructure.models_moderation import (
    alerts,
    moderation_actions,
    moderators,
    telegram_updates,
    telegram_users,
)

logger = logging.getLogger(__name__)

_ENDED_INCIDENT = ("resolved", "closed_false_positive")


@dataclass(frozen=True)
class _Press:
    """What the captured callback says, unverified."""

    update_row_id: int
    callback_query_id: str | None
    chat_id: int | None  # the platform id of the pressed message's chat
    message_id: int | None
    data: Any
    tg_user_id: int | None
    received_at: datetime


@dataclass(frozen=True)
class _Presser:
    moderator_id: int
    telegram_user_id: int


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _press_of(row: Any) -> _Press:
    body = _object(row["payload"].get("callback_query"))
    message = _object(body.get("message"))
    chat = _object(message.get("chat"))
    sender = _object(body.get("from"))
    callback_id = body.get("id")
    return _Press(
        update_row_id=int(row["id"]),
        callback_query_id=str(callback_id) if callback_id is not None else None,
        chat_id=int(chat["id"]) if isinstance(chat.get("id"), int) else None,
        message_id=(
            int(message["message_id"]) if isinstance(message.get("message_id"), int) else None
        ),
        data=body.get("data"),
        tg_user_id=int(sender["id"]) if isinstance(sender.get("id"), int) else None,
        received_at=row["received_at"],
    )


async def _load_press(session: AsyncSession, update_row_id: int) -> _Press | None:
    row = (
        (
            await session.execute(
                sa.select(
                    telegram_updates.c.id,
                    telegram_updates.c.update_type,
                    telegram_updates.c.payload,
                    telegram_updates.c.received_at,
                ).where(telegram_updates.c.id == update_row_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["update_type"] != "callback_query":
        return None
    return _press_of(row)


async def _gate(session: AsyncSession, press: _Press) -> tuple[AlertRef, PressAction] | None:
    """B1: the alert posted as the pressed message, and the action its data names, or `None`."""
    if press.chat_id is None or press.message_id is None:
        return None
    decoded = decode_callback(press.data)
    if decoded is None:
        return None
    row = (
        (
            await session.execute(
                sa.select(alerts).where(
                    alerts.c.sent_chat_id == press.chat_id,
                    alerts.c.sent_message_id == press.message_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    alert = AlertRef.from_row(row)
    alert_id, action = decoded
    if alert_id != alert.id or action not in ACTIONS_FOR[alert.subject_type]:
        return None
    return alert, action


async def _presser(session: AsyncSession, press: _Press) -> _Presser | None:
    """B2: a declared, active moderator, declared at or before the press."""
    if press.tg_user_id is None:
        return None
    row = (
        await session.execute(
            sa.select(moderators.c.id, moderators.c.telegram_user_id)
            .join(telegram_users, telegram_users.c.id == moderators.c.telegram_user_id)
            .where(
                telegram_users.c.tg_user_id == press.tg_user_id,
                moderators.c.is_active.is_(True),
                moderators.c.created_at <= press.received_at,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return _Presser(moderator_id=int(row.id), telegram_user_id=int(row.telegram_user_id))


async def _own_act(session: AsyncSession, update_row_id: int) -> Any:
    """B6: the act this update already recorded, if any."""
    return (
        (
            await session.execute(
                sa.select(
                    moderation_actions.c.action_type,
                    moderation_actions.c.actor_moderator_id,
                ).where(moderation_actions.c.source_update_id == update_row_id)
            )
        )
        .mappings()
        .one_or_none()
    )


async def _subject_chat(session: AsyncSession, alert: AlertRef) -> int:
    table = (
        "moderation_incidents" if alert.subject_type is SubjectType.INCIDENT else "attention_items"
    )
    chat_pk: int = (
        await session.execute(
            sa.text(f"SELECT telegram_chat_id FROM {table} WHERE id = :id"),  # noqa: S608
            {"id": alert.subject_id},
        )
    ).scalar_one()
    return chat_pk


async def _record(
    session: AsyncSession,
    *,
    alert: AlertRef,
    action: PressAction,
    presser: _Presser,
    press: _Press,
    chat_pk: int,
) -> None:
    values: dict[str, Any] = {
        "telegram_chat_id": chat_pk,
        "action_type": ACT_KIND[action],
        "action_strength": "confirmation" if action is PressAction.HANDLED else None,
        "occurred_at": press.received_at,
        "actor_telegram_user_id": presser.telegram_user_id,
        "actor_moderator_id": presser.moderator_id,
        "source_update_id": press.update_row_id,
        "alert_id": alert.id,
        "detail": {},
    }
    if alert.subject_type is SubjectType.INCIDENT:
        values["moderation_incident_id"] = alert.subject_id
    await session.execute(
        pg_insert(moderation_actions)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_moderation_actions_source_update")
    )


async def _incident_press(
    session: AsyncSession,
    *,
    alert: AlertRef,
    action: PressAction,
    presser: _Presser,
    press: _Press,
) -> PressOutcome:
    """B4, under `incident_lock`, so a press never lands over a closure from another route."""
    async with incident_lock(session):
        if await _own_act(session, press.update_row_id) is not None:
            return PressOutcome.RECORDED
        status = (
            await session.execute(
                sa.text("SELECT status FROM moderation_incident_state WHERE incident_id = :id"),
                {"id": alert.subject_id},
            )
        ).scalar_one()
        if status in _ENDED_INCIDENT:
            return PressOutcome.ALREADY_ENDED
        chat_pk = await _subject_chat(session, alert)
        await _record(
            session, alert=alert, action=action, presser=presser, press=press, chat_pk=chat_pk
        )
    return PressOutcome.RECORDED


async def _take_outcome(
    session: AsyncSession, *, item_id: int, chat_pk: int, moderator_id: int, at: datetime
) -> PressOutcome:
    """B5's three recorded outcomes, read back from the derived state: not on the team at the
    instant, else whether the assignee view names the presser or someone else."""
    if moderator_id not in await team_at(session, telegram_chat_id=chat_pk, t=at):
        return PressOutcome.RECORDED_NOT_TEAM
    assignee = (
        await session.execute(
            sa.text(
                "SELECT assigned_moderator_id FROM attention_item_assignee "
                "WHERE attention_item_id = :id"
            ),
            {"id": item_id},
        )
    ).scalar_one_or_none()
    if assignee is not None and int(assignee) != moderator_id:
        return PressOutcome.ALREADY_TAKEN
    return PressOutcome.RECORDED


async def _take_press(
    session: AsyncSession, *, alert: AlertRef, presser: _Presser, press: _Press
) -> PressOutcome:
    """B5, under the source chat's `chat_lock`, so a take never races the answer that closes the
    item."""
    chat_pk = await _subject_chat(session, alert)
    async with chat_lock(session, chat_pk):
        if await _own_act(session, press.update_row_id) is None:
            status = (
                await session.execute(
                    sa.text("SELECT status FROM attention_items WHERE id = :id"),
                    {"id": alert.subject_id},
                )
            ).scalar_one()
            if status != "open":
                return PressOutcome.ALREADY_ENDED
            await _record(
                session,
                alert=alert,
                action=PressAction.TAKE,
                presser=presser,
                press=press,
                chat_pk=chat_pk,
            )
        return await _take_outcome(
            session,
            item_id=alert.subject_id,
            chat_pk=chat_pk,
            moderator_id=presser.moderator_id,
            at=press.received_at,
        )


async def _recorded_outcome(
    session: AsyncSession, *, alert: AlertRef, act: Any, press: _Press
) -> PressOutcome:
    """B6: the outcome of an act this update already recorded."""
    if alert.subject_type is SubjectType.INCIDENT:
        return PressOutcome.RECORDED
    return await _take_outcome(
        session,
        item_id=alert.subject_id,
        chat_pk=await _subject_chat(session, alert),
        moderator_id=int(act["actor_moderator_id"]),
        at=press.received_at,
    )


async def derive_alert_press(
    session_factory: async_sessionmaker[AsyncSession], update_row_id: int
) -> PressOutcome:
    """B1-B6 for one captured `callback_query`. Records at most one act; never calls Telegram."""
    async with session_factory() as session:
        press = await _load_press(session, update_row_id)
        gated = await _gate(session, press) if press is not None else None
        if press is None or gated is None:
            logger.info("alert press invalid", extra={"update_id": update_row_id})
            return PressOutcome.INVALID
        alert, action = gated
        act = await _own_act(session, update_row_id)
        if act is not None:
            outcome = await _recorded_outcome(session, alert=alert, act=act, press=press)
        else:
            presser = await _presser(session, press)
            if presser is None:
                outcome = PressOutcome.NOT_A_MODERATOR
            elif alert.subject_type is SubjectType.INCIDENT:
                outcome = await _incident_press(
                    session, alert=alert, action=action, presser=presser, press=press
                )
            else:
                outcome = await _take_press(session, alert=alert, presser=presser, press=press)
        await session.commit()

    extra: dict[str, Any] = {"alert_id": alert.id, "update_id": update_row_id}
    if alert.subject_type is SubjectType.INCIDENT:
        extra["incident_id"] = alert.subject_id
    logger.info("alert press: %s", outcome.value, extra=extra)
    return outcome


# --- the answer (B7) ---


@dataclass(frozen=True)
class PressAnswer:
    """What `answer_alert_press` sends and refreshes: the callback to answer (none for a press
    without one), the pressed message's chat (for the guard), the answer's text and the alert to
    refresh (none when the gate found no alert)."""

    callback_query_id: str | None
    chat_id: int | None
    text: str
    alert_id: int | None


async def _assignee_name(session: AsyncSession, item_id: int) -> str | None:
    name: str | None = (
        await session.execute(
            sa.text(
                "SELECT m.display_name FROM attention_item_assignee a "
                "JOIN moderators m ON m.id = a.assigned_moderator_id "
                "WHERE a.attention_item_id = :id"
            ),
            {"id": item_id},
        )
    ).scalar_one_or_none()
    return name


async def _subject_status(session: AsyncSession, alert: AlertRef) -> str | None:
    sql = (
        "SELECT status FROM moderation_incident_state WHERE incident_id = :id"
        if alert.subject_type is SubjectType.INCIDENT
        else "SELECT status FROM attention_items WHERE id = :id"
    )
    status: str | None = (
        await session.execute(sa.text(sql), {"id": alert.subject_id})
    ).scalar_one_or_none()
    return status


async def press_answer(
    session_factory: async_sessionmaker[AsyncSession],
    update_row_id: int,
    outcome: PressOutcome,
) -> PressAnswer:
    """The answer to one press (`alert-messages.md` §5), composed from the outcome and the derived
    state now: the assignee's name for `already_taken`, the subject's status for
    `already_ended`."""
    async with session_factory() as session:
        press = await _load_press(session, update_row_id)
        if press is None:
            return PressAnswer(
                callback_query_id=None,
                chat_id=None,
                text=answer_text(PressOutcome.INVALID),
                alert_id=None,
            )
        gated = await _gate(session, press)
        alert, action = gated if gated is not None else (None, None)
        assignee_name = ended_status = None
        if alert is not None and outcome is PressOutcome.ALREADY_TAKEN:
            assignee_name = await _assignee_name(session, alert.subject_id)
        if alert is not None and outcome is PressOutcome.ALREADY_ENDED:
            ended_status = await _subject_status(session, alert)
    return PressAnswer(
        callback_query_id=press.callback_query_id,
        chat_id=press.chat_id,
        text=answer_text(
            outcome if alert is not None else PressOutcome.INVALID,
            action=action,
            assignee_name=assignee_name,
            ended_status=ended_status,
        ),
        alert_id=alert.id if alert is not None else None,
    )

