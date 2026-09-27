"""Pre-flag evidence (T043, the first clarification, FR-043, SC-023's state half): a ban dated
after posting but before `detected_at` reads **resolved** from the moment the incident exists,
crediting the performer; a ban dated before posting does not link at all — the incident stays
open. The figure half of SC-023 is `test_metrics.py` (T058).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_ban_after_posting_but_before_flagging_resolves_immediately(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_id,
    )
    pre_flag_moment = _OPENED_AT + timedelta(minutes=30)
    assert _OPENED_AT < pre_flag_moment < _DETECTED_AT

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    performer_id = await insert_user(tg_user_id=_rand_id())
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=pre_flag_moment,
        actor_telegram_user_id=performer_id,
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "ban"
    assert state["resolved_at"] == pre_flag_moment
    assert state["resolved_by_telegram_user_id"] == performer_id


async def test_a_ban_before_posting_does_not_link(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_id,
    )
    before_posting = _OPENED_AT - timedelta(minutes=5)

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=before_posting,
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"
