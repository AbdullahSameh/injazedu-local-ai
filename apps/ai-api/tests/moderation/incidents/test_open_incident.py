"""Opening an incident (T020, lifecycle contract I1-I7, FR-001...FR-009, SC-025):
`opened_at` = the anchor's `sent_at`; `detected_at` = the database's `now()` at insert;
`source='operator'` with its opener recorded; labels required and stored exactly; a service
message is refused; a bot's message is accepted; opening never touches an attention item; the
incident reads **open** the instant it exists.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.infrastructure.models_moderation import attention_items
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _fetch_attention_item(
    incident_session_factory: async_sessionmaker[AsyncSession], item_id: int
) -> dict[str, Any]:
    async with incident_session_factory() as session:
        result = await session.execute(
            select(attention_items).where(attention_items.c.id == item_id)
        )
        return dict(result.mappings().one())


async def test_opened_at_is_the_message_sent_at_detected_at_is_now(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    sent_at = datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=sent_at)

    before = datetime.now(UTC)
    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=7,
    )
    after = datetime.now(UTC)
    assert incident_id is not None

    row = await fetch_incident(incident_id=incident_id)
    assert row["opened_at"] == sent_at
    assert before - timedelta(seconds=1) <= row["detected_at"] <= after + timedelta(seconds=1)
    assert row["opened_at"] != row["detected_at"]


async def test_source_and_opener_and_labels_are_recorded_exactly(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="ABUSE",
        severity="high",
        opened_by_user_id=42,
    )
    assert incident_id is not None

    row = await fetch_incident(incident_id=incident_id)
    assert row["source"] == "operator"
    assert row["opened_by_user_id"] == 42
    assert row["category"] == "ABUSE"
    assert row["severity"] == "high"
    assert row["message_classification_id"] is None


async def test_a_service_message_is_refused(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC),
        is_service=True,
    )

    with pytest.raises(ValueError):
        await open_incident(
            incident_session_factory,
            telegram_chat_id=chat_pk,
            telegram_message_id=1,
            category="OTHER",
            severity="low",
            opened_by_user_id=1,
        )


async def test_a_bot_accounts_message_is_accepted(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    bot_user_id = await insert_user(tg_user_id=_rand_id(), is_bot=True)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC),
        telegram_user_id=bot_user_id,
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="medium",
        opened_by_user_id=1,
    )
    assert incident_id is not None
    row = await fetch_incident(incident_id=incident_id)
    assert row["telegram_message_id"] == 1


async def test_opening_an_incident_on_an_items_anchor_leaves_the_item_byte_identical(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    sent_at = datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=sent_at, telegram_user_id=student_id
    )

    async with incident_session_factory() as session:
        item_id = (
            await session.execute(
                attention_items.insert()
                .values(
                    telegram_chat_id=chat_pk,
                    telegram_message_id=1,
                    opened_at=sent_at,
                    source="rule",
                    rule_version=1,
                    status="open",
                )
                .returning(attention_items.c.id)
            )
        ).scalar_one()
        await session.commit()

    before = await _fetch_attention_item(incident_session_factory, item_id)

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None

    after = await _fetch_attention_item(incident_session_factory, item_id)
    assert after == before


async def test_read_state_returns_open_immediately(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    read_state: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None

    state = await read_state(incident_id)
    assert state is not None
    assert state["status"] == "open"
