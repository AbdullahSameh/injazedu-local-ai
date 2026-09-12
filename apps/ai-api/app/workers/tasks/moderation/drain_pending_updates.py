"""`drain_pending_updates` — reconciles the pending index (FR-020, `contracts/ingestion-
guarantees.md` G3, `data-model.md` §1).

`ix_telegram_updates_pending (received_at) WHERE processed_at IS NULL` is the authoritative work
list; the dramatiq message `store_batch` schedules is only an optimisation. Claims in `update_id`
order with `FOR UPDATE SKIP LOCKED` so this can run alongside live capture without contending for
a row a live worker (or another drain run) already holds (probe 8) — claim and mark happen in the
same transaction, so a claimed row can never be re-claimed by a concurrent run.
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import telegram_updates

logger = logging.getLogger(__name__)

_CLAIM_BATCH_SIZE = 100


async def drain_pending_updates_once(
    session_factory: async_sessionmaker[AsyncSession], *, batch_size: int = _CLAIM_BATCH_SIZE
) -> int:
    """Claims and marks processed one batch of pending rows, in `update_id` order. Returns the
    number of rows handled — 0 means the backlog is empty."""
    async with session_factory() as session:
        claimed = (
            (
                await session.execute(
                    sa.select(telegram_updates.c.id)
                    .where(telegram_updates.c.processed_at.is_(None))
                    .order_by(telegram_updates.c.update_id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not claimed:
            return 0

        await session.execute(
            telegram_updates.update()
            .where(telegram_updates.c.id.in_(claimed))
            .values(processed_at=sa.func.now(), process_error=None)
        )
        await session.commit()
    return len(claimed)


async def drain_pending_updates_all(
    session_factory: async_sessionmaker[AsyncSession], *, batch_size: int = _CLAIM_BATCH_SIZE
) -> int:
    """Drains the whole backlog, one claimed batch at a time, until none remain. Returns the
    total number of rows handled."""
    total = 0
    while True:
        handled = await drain_pending_updates_once(session_factory, batch_size=batch_size)
        total += handled
        if handled < batch_size:
            return total


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def drain_pending_updates() -> None:
    handled = asyncio.run(drain_pending_updates_all(_default_session_factory()))
    logger.info("drained pending updates: %d rows", handled)
