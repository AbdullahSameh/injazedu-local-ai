"""The anchor is `(telegram_chat_id, telegram_message_id)` — one message anchors at most one
incident, ever (T019, lifecycle contract I2, FR-002, SC-006).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_two_chats_with_identically_numbered_messages_open_two_incidents(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_a = await insert_chat(chat_id=-_rand_id())
    chat_b = await insert_chat(chat_id=-_rand_id())
    sent_at = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
    await insert_message(telegram_chat_id=chat_a, message_id=2, sent_at=sent_at)
    await insert_message(telegram_chat_id=chat_b, message_id=2, sent_at=sent_at)

    incident_a = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_a,
        telegram_message_id=2,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    incident_b = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_b,
        telegram_message_id=2,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )

    assert incident_a is not None
    assert incident_b is not None
    assert incident_a != incident_b


async def test_the_same_anchor_opened_twice_yields_one_incident(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
    )

    first = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    second = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="ABUSE",
        severity="high",
        opened_by_user_id=2,
    )

    assert first is not None
    assert second is None
