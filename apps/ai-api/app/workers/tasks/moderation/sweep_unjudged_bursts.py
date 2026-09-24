"""`sweep_unjudged_bursts` — the authoritative judgement path (T064, `contracts/attention-
rules.md` §1 B4, D-TG-72, D-TG-80, research Finding 3).

`telegram_messages.attention_evaluated_at IS NULL` is the authoritative work list;
`evaluate_attention`'s delayed dramatiq message is an optimisation only, since this stack's Redis
is not durable (`appendonly no`, RDB snapshots at 60-3600 s, a volume `make down-hard` deletes —
a lost delayed message is a question that never happened, with no gap recorded). Claims messages
older than the settle window with `FOR UPDATE SKIP LOCKED`, in `sent_at` order — TG-M1's
`drain_pending_updates` idiom (probe 8) — then judges each distinct `(chat, sender, thread)`
burst the claimed rows belong to through `assemble_burst`/`open_item`: the same predicate the
fast path uses, never a second one (D-TG-82).
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.attention import assemble_burst, open_item
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import telegram_messages

logger = logging.getLogger(__name__)

_CLAIM_BATCH_SIZE = 200


async def sweep_unjudged_bursts_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    gap_s: int,
    batch_size: int = _CLAIM_BATCH_SIZE,
) -> int:
    """Claims up to `batch_size` unjudged, settled messages in one transaction —
    `FOR UPDATE SKIP LOCKED` so this can run alongside live judgement and a concurrent sweep
    without contending for a row either already holds (mirrors `drain_pending_updates_once`,
    probe 8) — then judges each distinct burst the claimed rows belong to.

    A burst is judged through `assemble_burst`/`open_item`, which re-reads it from the database
    regardless of which of its members happened to be claimed here (D-TG-79); `open_item` stamps
    `attention_evaluated_at` on every member it reads, whether or not an item resulted, so a
    message this call declines is never revisited (B4). A `sender_chat` message
    (`telegram_user_id IS NULL`) forms no burst (FR-013) and is stamped evaluated directly.

    Returns the number of claimed rows — 0 means the backlog is empty.
    """
    cutoff = sa.func.now() - (
        sa.bindparam("gap_s", gap_s, type_=sa.Integer) * sa.text("interval '1 second'")
    )
    async with session_factory() as session:
        claimed = (
            (
                await session.execute(
                    sa.select(
                        telegram_messages.c.id,
                        telegram_messages.c.telegram_chat_id,
                        telegram_messages.c.telegram_user_id,
                        telegram_messages.c.message_thread_id,
                        telegram_messages.c.sent_at,
                    )
                    .where(
                        telegram_messages.c.attention_evaluated_at.is_(None),
                        telegram_messages.c.sent_at < cutoff,
                    )
                    .order_by(telegram_messages.c.sent_at)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        if not claimed:
            return 0

        sender_chat_ids: list[int] = []
        # Covered by *actual* burst membership, never by `(chat, user, thread)` alone: the same
        # sender can have two separate, far-apart bursts claimed in one batch, and a key-only
        # dedup would silently skip the second one forever (measured — a sender's message 30s
        # after a first burst was left unjudged under a naive key set). `assemble_burst` is the
        # one source of truth for which claimed rows a given burst actually settles.
        covered_ids: set[int] = set()
        for row in claimed:
            if row["telegram_user_id"] is None:
                sender_chat_ids.append(row["id"])
                continue
            if row["id"] in covered_ids:
                continue
            burst = await assemble_burst(
                session,
                telegram_chat_id=row["telegram_chat_id"],
                telegram_user_id=row["telegram_user_id"],
                message_thread_id=row["message_thread_id"],
                around=row["sent_at"],
                gap_s=gap_s,
            )
            covered_ids.update(member["id"] for member in burst)
            await open_item(session, burst)

        if sender_chat_ids:
            await session.execute(
                telegram_messages.update()
                .where(telegram_messages.c.id.in_(sender_chat_ids))
                .values(attention_evaluated_at=sa.func.now())
            )

        await session.commit()

    return len(claimed)


async def sweep_unjudged_bursts_all(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    gap_s: int,
    batch_size: int = _CLAIM_BATCH_SIZE,
) -> int:
    """Drains the whole authoritative work list, one claimed batch at a time. Returns the total
    number of rows handled."""
    total = 0
    while True:
        handled = await sweep_unjudged_bursts_once(
            session_factory, gap_s=gap_s, batch_size=batch_size
        )
        total += handled
        if handled < batch_size:
            return total


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def sweep_unjudged_bursts() -> None:
    settings = load_settings()
    handled = asyncio.run(
        sweep_unjudged_bursts_all(
            _default_session_factory(), gap_s=settings.moderation_burst_gap_s
        )
    )
    logger.info("swept unjudged bursts: %d rows", handled)
