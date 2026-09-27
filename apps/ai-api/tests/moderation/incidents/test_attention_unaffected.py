"""T065 — TG-M3 stays untouched (FR-086, SC-016): over one seeded traffic set, every TG-M3
figure (`first_response_time_stats`, `unanswered_stats`, `oldest_waiting`,
`accuracy_by_rule_version`) reads identically before and after this milestone's evidence and
incidents are added; a moderator's reaction on a waiting question still closes nothing; opening an
incident on an item's own anchor leaves the item byte-identical.

`attention_items` rows are built directly, exactly as `tests/moderation/attention/test_metrics.py`
does — siblings under `tests/moderation/` do not inherit each other's `conftest.py`.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.metrics import (
    accuracy_by_rule_version,
    first_response_time_stats,
    oldest_waiting,
    unanswered_stats,
)
from app.infrastructure.models_moderation import attention_items
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_PERIOD_FROM = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_PERIOD_TO = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _insert_item(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
    opened_at: datetime,
    status: str = "open",
    frt_seconds: float | None = None,
    responsible_moderator_id: int | None = None,
) -> None:
    values: dict[str, Any] = {
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": telegram_message_id,
        "opened_at": opened_at,
        "source": "rule",
        "rule_version": 1,
        "status": status,
        "responsible_moderator_id": responsible_moderator_id,
    }
    if frt_seconds is not None:
        values["first_response_message_id"] = telegram_message_id + 9_000
        values["first_response_at"] = opened_at + timedelta(seconds=frt_seconds)
        values["first_response_kind"] = "group_message"
    await session.execute(attention_items.insert().values(**values))


async def _all_attention_stats(session: AsyncSession, *, chat_id: int) -> dict[str, Any]:
    return {
        "frt": await first_response_time_stats(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO, min_samples=10, chat_id=chat_id
        ),
        "unanswered": await unanswered_stats(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO, chat_id=chat_id
        ),
        "oldest_waiting": await oldest_waiting(session, chat_id=chat_id),
        "accuracy": await accuracy_by_rule_version(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO
        ),
    }


async def test_tg_m3_figures_are_identical_before_and_after_tg_m4_evidence_and_incidents(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())

    answered_sent_at = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=answered_sent_at,
        telegram_user_id=student_id,
    )
    waiting_sent_at = datetime(2026, 1, 6, 10, 0, 0, tzinfo=UTC)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=waiting_sent_at, telegram_user_id=student_id
    )

    async with incident_session_factory() as session:
        await _insert_item(
            session,
            telegram_chat_id=chat_pk,
            telegram_message_id=1,
            opened_at=answered_sent_at,
            status="answered",
            frt_seconds=90,
        )
        await _insert_item(
            session,
            telegram_chat_id=chat_pk,
            telegram_message_id=2,
            opened_at=waiting_sent_at,
            status="open",
        )
        await session.commit()

    async with incident_session_factory() as session:
        before = await _all_attention_stats(session, chat_id=chat_pk)

    # TG-M4 traffic layered on top: an incident (with acknowledgement and enforcement evidence)
    # on the answered question's own message, and a moderator's reaction on the still-waiting one.
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=answered_sent_at,
        detected_at=answered_sent_at + timedelta(hours=1),
        category="SPAM_OR_AD",
        severity="low",
    )
    mod = await insert_moderator()
    ack_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=answered_sent_at + timedelta(hours=1, minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=ack_update_id,
    )
    ban_update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=answered_sent_at + timedelta(hours=2),
        subject_telegram_user_id=student_id,
        source_update_id=ban_update_id,
    )

    # A moderator's reaction on the *waiting* question's own message.
    waiting_ack_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=waiting_sent_at + timedelta(minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=2,
        source_update_id=waiting_ack_update_id,
    )

    async with incident_session_factory() as session:
        waiting_item_before = (
            (
                await session.execute(
                    select(attention_items).where(
                        attention_items.c.telegram_chat_id == chat_pk,
                        attention_items.c.telegram_message_id == 2,
                    )
                )
            )
            .mappings()
            .one()
        )

    # Opening a second incident directly on the waiting item's own anchor message.
    waiting_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=2,
        opened_at=waiting_sent_at,
        detected_at=waiting_sent_at + timedelta(hours=1),
        category="ABUSE",
        severity="medium",
    )

    async with incident_session_factory() as session:
        waiting_item_after = (
            (
                await session.execute(
                    select(attention_items).where(
                        attention_items.c.telegram_chat_id == chat_pk,
                        attention_items.c.telegram_message_id == 2,
                    )
                )
            )
            .mappings()
            .one()
        )
        after = await _all_attention_stats(session, chat_id=chat_pk)

    assert incident_id is not None
    assert waiting_incident_id is not None
    # A moderator's reaction on a waiting question closes nothing — the item's own status column
    # (TG-M3's own state, not TG-M4's derived one) is untouched.
    assert waiting_item_before["status"] == "open"
    assert waiting_item_after["status"] == "open"
    # Opening an incident on the item's anchor leaves the item byte-identical.
    assert dict(waiting_item_before) == dict(waiting_item_after)

    # `oldest_waiting` is deliberately a *live* figure (`now() - opened_at`, M12-M14) — it drifts
    # by the wall-clock time between the two calls, never by anything TG-M4 wrote. Every other
    # figure is a plain aggregate over stored rows and must be byte-identical.
    before_without_oldest_waiting = {k: v for k, v in before.items() if k != "oldest_waiting"}
    after_without_oldest_waiting = {k: v for k, v in after.items() if k != "oldest_waiting"}
    assert before_without_oldest_waiting == after_without_oldest_waiting
    assert before["oldest_waiting"] is not None
    assert after["oldest_waiting"] is not None
    assert abs((after["oldest_waiting"] - before["oldest_waiting"]).total_seconds()) < 5
