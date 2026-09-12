"""US4 — groups appear by themselves, and losing coverage is visible (FR-026, FR-027, FR-028,
FR-030, FR-031, SC-009, SC-010, SC-012).
"""

from __future__ import annotations

import sqlalchemy as sa
from app.application.moderation.ingest import store_batch, upsert_chats_from_batch
from app.infrastructure.models_moderation import telegram_chats
from app.providers.telegram.client import parse_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update, make_my_chat_member_update


async def _chat_row(session_factory: async_sessionmaker[AsyncSession], chat_id: int):
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(telegram_chats).where(telegram_chats.c.chat_id == chat_id)
            )
        ).one_or_none()


async def test_a_my_chat_member_add_creates_the_row(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_chat_id: int,
    ingest_chat_cleanup: None,
) -> None:
    update = parse_update(
        make_my_chat_member_update(9000, chat_id=ingest_chat_id, status="member")
    )

    await upsert_chats_from_batch(ingest_session_factory, updates=[update])

    row = await _chat_row(ingest_session_factory, ingest_chat_id)
    assert row is not None
    assert row.chat_id == ingest_chat_id
    assert row.chat_type == "supergroup"
    assert row.title == "Test Group"
    assert row.bot_status == "member"
    assert row.bot_status_at is not None


async def test_all_four_standing_changes_update_the_record_and_can_delete_is_observation_only(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_chat_id: int,
    ingest_chat_cleanup: None,
) -> None:
    async def _apply(update_id: int, status: str, *, can_delete: bool | None = None) -> None:
        update = parse_update(
            make_my_chat_member_update(
                update_id,
                chat_id=ingest_chat_id,
                status=status,
                can_delete_messages=can_delete,
            )
        )
        await upsert_chats_from_batch(ingest_session_factory, updates=[update])

    await _apply(9100, "member")  # added
    assert (await _chat_row(ingest_session_factory, ingest_chat_id)).bot_status == "member"

    await _apply(9101, "administrator", can_delete=True)  # promoted
    row = await _chat_row(ingest_session_factory, ingest_chat_id)
    assert row.bot_status == "administrator"
    assert row.bot_can_delete is True

    await _apply(9102, "member")  # demoted
    row = await _chat_row(ingest_session_factory, ingest_chat_id)
    assert row.bot_status == "member"
    assert row.bot_can_delete is None  # an observation, not a sticky fact — no longer applies

    await _apply(9103, "left")  # removed
    assert (await _chat_row(ingest_session_factory, ingest_chat_id)).bot_status == "left"


async def test_a_group_seen_only_through_an_ordinary_message_gets_bot_status_unknown(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_chat_id: int,
    ingest_chat_cleanup: None,
) -> None:
    update = parse_update(make_message_update(9200, chat_id=ingest_chat_id))

    await upsert_chats_from_batch(ingest_session_factory, updates=[update])

    row = await _chat_row(ingest_session_factory, ingest_chat_id)
    assert row is not None
    # Never guessed as "administrator" — guessing would hide exactly the coverage failure this
    # milestone exists to make visible (D-TG-43).
    assert row.bot_status == "unknown"


async def test_a_new_chat_is_not_monitored_and_its_events_still_store(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
) -> None:
    update = parse_update(make_message_update(9300, chat_id=ingest_chat_id))

    await upsert_chats_from_batch(ingest_session_factory, updates=[update])
    row = await _chat_row(ingest_session_factory, ingest_chat_id)
    assert row.is_monitored is False  # the opt-in switch defaults off; no screen exists yet

    stored = await store_batch(
        ingest_session_factory, bot_id=ingest_bot_id, updates=[update], schedule=lambda *_a: None
    )
    assert {u.update_id for u in stored} == {9300}  # still captured despite not being monitored
