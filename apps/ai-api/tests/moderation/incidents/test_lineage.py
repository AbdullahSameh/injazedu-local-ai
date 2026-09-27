"""Membership evidence crossing one promotion hop (T041, lifecycle contract L5, D-TG-107,
FR-082, SC-018, probe 8): an incident on a message in a chat later promoted resolves when the
sender is banned in the **successor** chat, and the incident's own row is never re-pointed. A
single-chat test cannot see this — the whole point of the test.
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


async def test_a_ban_in_the_successor_chat_resolves_the_predecessors_incident(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
    fetch_incident: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    old_platform_chat_id = -_rand_id()
    new_platform_chat_id = -_rand_id()
    old_chat_pk = await insert_chat(
        chat_id=old_platform_chat_id, migrated_to_chat_id=new_platform_chat_id
    )
    new_chat_pk = await insert_chat(chat_id=new_platform_chat_id)

    await insert_message(
        telegram_chat_id=old_chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=old_chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=new_chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=30),
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "ban"

    incident = await fetch_incident(incident_id=incident_id)
    assert incident["telegram_chat_id"] == old_chat_pk


async def test_a_ban_in_an_unrelated_chat_does_not_resolve(
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
    old_platform_chat_id = -_rand_id()
    new_platform_chat_id = -_rand_id()
    old_chat_pk = await insert_chat(
        chat_id=old_platform_chat_id, migrated_to_chat_id=new_platform_chat_id
    )
    await insert_chat(chat_id=new_platform_chat_id)
    unrelated_chat_pk = await insert_chat(chat_id=-_rand_id())

    await insert_message(
        telegram_chat_id=old_chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=old_chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=unrelated_chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=30),
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"
