"""US4 — a supergroup promotion keeps one history (FR-029, D-TG-44, SC-011)."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from app.application.moderation.ingest import apply_chat_migration_if_any, store_batch
from app.infrastructure.models_moderation import telegram_chats
from app.providers.telegram.client import parse_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import (
    make_message_update,
    make_migrate_from_update,
    make_migrate_to_update,
)


@pytest.fixture
def chat_ids() -> tuple[int, int]:
    """A unique (old, new) chat-id pair per test — negative, like real group/supergroup ids."""
    old = -random.randint(10_000_000, 1_000_000_000)
    new = -random.randint(1_000_000_001, 2_000_000_000)
    return old, new


@pytest_asyncio.fixture
async def migration_cleanup(
    ingest_session_factory: async_sessionmaker[AsyncSession], chat_ids: tuple[int, int]
) -> AsyncIterator[None]:
    yield
    old_id, new_id = chat_ids
    async with ingest_session_factory() as session:
        await session.execute(
            telegram_chats.delete().where(telegram_chats.c.chat_id.in_([old_id, new_id]))
        )
        await session.commit()


async def _chat_row(session_factory: async_sessionmaker[AsyncSession], chat_id: int):
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(telegram_chats).where(telegram_chats.c.chat_id == chat_id)
            )
        ).one_or_none()


async def test_a_promotion_links_old_and_new_rows_in_both_directions(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    chat_ids: tuple[int, int],
    migration_cleanup: None,
) -> None:
    old_id, new_id = chat_ids
    update = parse_update(make_migrate_to_update(9400, old_chat_id=old_id, new_chat_id=new_id))

    await apply_chat_migration_if_any(ingest_session_factory, update=update)

    old_row = await _chat_row(ingest_session_factory, old_id)
    new_row = await _chat_row(ingest_session_factory, new_id)
    assert old_row.migrated_to_chat_id == new_id
    assert new_row.migrated_from_chat_id == old_id


async def test_the_mirrored_migrate_from_event_alone_links_both_directions_too(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    chat_ids: tuple[int, int],
    migration_cleanup: None,
) -> None:
    # Only the *new* chat's stream delivers this event — either one alone carries both
    # identifiers, so either alone is enough to make the pair navigable from both sides
    # (D-TG-44), the classic Telegram footgun where the mirrored pair does not always both land.
    old_id, new_id = chat_ids
    update = parse_update(make_migrate_from_update(9401, old_chat_id=old_id, new_chat_id=new_id))

    await apply_chat_migration_if_any(ingest_session_factory, update=update)

    old_row = await _chat_row(ingest_session_factory, old_id)
    new_row = await _chat_row(ingest_session_factory, new_id)
    assert old_row.migrated_to_chat_id == new_id
    assert new_row.migrated_from_chat_id == old_id


async def test_events_under_the_old_and_new_ids_are_all_stored_with_no_loss_or_duplication(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    chat_ids: tuple[int, int],
    ingest_cleanup: None,
    migration_cleanup: None,
) -> None:
    old_id, new_id = chat_ids
    pre = parse_update(make_message_update(9402, chat_id=old_id))
    migrate = parse_update(make_migrate_to_update(9403, old_chat_id=old_id, new_chat_id=new_id))
    post = parse_update(make_message_update(9404, chat_id=new_id))

    await apply_chat_migration_if_any(ingest_session_factory, update=migrate)
    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=[pre, migrate, post],
        schedule=lambda *_a: None,
    )

    assert {u.update_id for u in stored} == {9402, 9403, 9404}  # 0 lost, 0 double-counted
