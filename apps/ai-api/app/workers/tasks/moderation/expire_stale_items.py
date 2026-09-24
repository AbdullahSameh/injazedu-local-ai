"""`expire_stale_items` — the ageing sweep (T063, `contracts/attention-rules.md` §6 G2-G4,
D-TG-87).

One set-based guarded `UPDATE … WHERE status = 'open' AND opened_at < now() - max_age_s`: every
item past `MODERATION_ITEM_MAX_AGE_S` becomes `expired`, with `closed_at` and `close_reason`
recorded. Idempotent by its own predicate — no row loop, and a second run changes nothing, since
an already-expired item no longer matches `status = 'open'` (G2). `now()` is the database's own
clock, never Python's: the ceiling is a property of stored rows, not of whichever process happens
to run the sweep.
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import attention_items

logger = logging.getLogger(__name__)


async def expire_stale_items_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    max_age_s: int,
    telegram_chat_id: int | None = None,
) -> int:
    """The one guarded write (contract §6 G2): set-based, never a row loop. Returns the number of
    items expired — 0 is a normal outcome, not an error.

    `telegram_chat_id` (a surrogate `telegram_chats.id`) narrows the sweep to one chat — used by
    `rederive_chat.py --with-attention` (D-TG-89) so a catch-up run's own expiry report reflects
    only what it touched. The periodic actor below never passes it, so its own behaviour is
    unchanged: one sweep, every chat.
    """
    cutoff = sa.func.now() - (
        sa.bindparam("max_age_s", max_age_s, type_=sa.Integer) * sa.text("interval '1 second'")
    )
    conditions = [attention_items.c.status == "open", attention_items.c.opened_at < cutoff]
    if telegram_chat_id is not None:
        conditions.append(attention_items.c.telegram_chat_id == telegram_chat_id)
    async with session_factory() as session:
        result = await session.execute(
            attention_items.update()
            .where(*conditions)
            .values(status="expired", closed_at=sa.func.now(), close_reason="expired")
        )
        await session.commit()
    return result.rowcount  # type: ignore[attr-defined,no-any-return]


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def expire_stale_items() -> None:
    settings = load_settings()
    handled = asyncio.run(
        expire_stale_items_once(
            _default_session_factory(), max_age_s=settings.moderation_item_max_age_s
        )
    )
    logger.info("expired stale attention items: %d rows", handled)
