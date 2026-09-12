"""US1 — after interpretation, only `processed_at` / `process_error` differ; `payload`,
`update_id`, `bot_id` and `received_at` are unchanged (FR-009).
"""

from __future__ import annotations

import sqlalchemy as sa
from app.application.moderation.ingest import store_batch
from app.infrastructure.models_moderation import telegram_updates
from app.providers.telegram.client import parse_update
from app.workers.tasks.moderation.process_update import process_update_row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


async def test_interpretation_changes_only_processed_at_and_process_error(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raw = make_message_update(700)
    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=[parse_update(raw)],
        schedule=lambda *_a: None,
    )
    row_id = stored[0].id

    async with ingest_session_factory() as session:
        before = (
            (
                await session.execute(
                    sa.select(telegram_updates).where(telegram_updates.c.id == row_id)
                )
            )
            .mappings()
            .one()
        )

    await process_update_row(ingest_session_factory, row_id)

    async with ingest_session_factory() as session:
        after = (
            (
                await session.execute(
                    sa.select(telegram_updates).where(telegram_updates.c.id == row_id)
                )
            )
            .mappings()
            .one()
        )

    assert before["processed_at"] is None
    assert after["processed_at"] is not None

    changed = {key for key in before if before[key] != after[key]}
    assert changed == {"processed_at"}

    assert after["payload"] == before["payload"]
    assert after["update_id"] == before["update_id"]
    assert after["bot_id"] == before["bot_id"]
    assert after["received_at"] == before["received_at"]


async def test_setting_processed_twice_is_the_same_result(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raw = make_message_update(701)
    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=[parse_update(raw)],
        schedule=lambda *_a: None,
    )
    row_id = stored[0].id

    await process_update_row(ingest_session_factory, row_id)
    async with ingest_session_factory() as session:
        once = (
            await session.execute(
                sa.select(telegram_updates.c.payload, telegram_updates.c.process_error).where(
                    telegram_updates.c.id == row_id
                )
            )
        ).one()

    await process_update_row(ingest_session_factory, row_id)
    async with ingest_session_factory() as session:
        twice = (
            await session.execute(
                sa.select(telegram_updates.c.payload, telegram_updates.c.process_error).where(
                    telegram_updates.c.id == row_id
                )
            )
        ).one()

    assert twice.payload == once.payload
    assert twice.process_error == once.process_error is None
