"""US2 — the backlog drains without loss or duplication (FR-020, SC-021)."""

from __future__ import annotations

import sqlalchemy as sa
from app.application.moderation.ingest import store_batch
from app.infrastructure.models_moderation import telegram_updates
from app.providers.telegram.client import parse_update
from app.workers.tasks.moderation.drain_pending_updates import drain_pending_updates_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


async def test_a_backlog_of_100_rows_drains_in_update_id_order_with_no_duplicates(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    # `drain_pending_updates_all` claims the whole `ix_telegram_updates_pending` index — every
    # bot, not just this test's — because that is its real job (a worker-startup reconciliation
    # sweep). Other tests in the shared `injaz_ai_test` database legitimately leave pending rows
    # behind (they exercise derivation directly, bypassing `process_update_row`), so this test
    # clears whatever is already pending before planting its own 100, making the assertions below
    # deterministic regardless of suite order.
    await drain_pending_updates_all(ingest_session_factory, batch_size=200)

    update_ids = list(range(2000, 2100))
    updates = [parse_update(make_message_update(uid)) for uid in update_ids]

    # Simulates a stopped worker: rows are stored (as live capture would) but never actually
    # interpreted, so they sit in the pending index untouched.
    await store_batch(
        ingest_session_factory, bot_id=ingest_bot_id, updates=updates, schedule=lambda *_a: None
    )

    # A small batch_size forces multiple claim rounds, exercising cross-batch ordering.
    handled = await drain_pending_updates_all(ingest_session_factory, batch_size=40)
    assert handled == 100

    async with ingest_session_factory() as session:
        rows = (
            await session.execute(
                sa.select(telegram_updates.c.update_id, telegram_updates.c.processed_at)
                .where(telegram_updates.c.bot_id == ingest_bot_id)
                .order_by(telegram_updates.c.update_id)
            )
        ).all()

    assert [row.update_id for row in rows] == update_ids  # handed over in update_id order
    assert all(row.processed_at is not None for row in rows)  # 100% marked handled

    # Draining again finds nothing left to claim — no duplicate processing.
    handled_again = await drain_pending_updates_all(ingest_session_factory, batch_size=40)
    assert handled_again == 0
