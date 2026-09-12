"""`process_update` — the interpreting stub (FR-032, FR-033, `data-model.md` §1).

TG-M1 interprets nothing: this actor's only job is to prove the handoff, the ordering and the
drain end-to-end, against an already-verified pipeline. It sets `processed_at` and derives
nothing else — no message parsing, no screen, no model call. Setting it twice is the same
result: `processed_at` is simply written again, and `process_error` is cleared, matching a
stub that can never fail. TG-M2 fills in the body without changing this contract.
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


async def process_update_row(
    session_factory: async_sessionmaker[AsyncSession], update_row_id: int
) -> None:
    async with session_factory() as session:
        await session.execute(
            telegram_updates.update()
            .where(telegram_updates.c.id == update_row_id)
            .values(processed_at=sa.func.now(), process_error=None)
        )
        await session.commit()


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def process_update(update_row_id: int, update_id: int) -> None:
    logger.info("update processed", extra={"update_id": update_id})
    asyncio.run(process_update_row(_default_session_factory(), update_row_id))
