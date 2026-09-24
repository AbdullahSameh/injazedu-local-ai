"""`evaluate_attention` — the fast, delayed judgement path (T028, contract §1 "why judgement may
run more than once", D-TG-80).

Scheduled per new student message with `delay=MODERATION_BURST_GAP_S` seconds
(`app/application/moderation/messages.py`'s `derive_message`). This is an **optimisation only**:
`telegram_messages.attention_evaluated_at IS NULL` is the authoritative work list a later sweep
(T053, not built here) claims from, so a delayed message lost to a Redis restart (research
Finding 3) costs a slower judgement, never a missed one.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.attention import assemble_burst, open_item
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory

logger = logging.getLogger(__name__)


async def evaluate_attention_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    message_thread_id: int | None,
    around: datetime,
    gap_s: int,
) -> int | None:
    """Assembles the burst settled around `around` and judges it — one transaction, so the
    per-chat advisory lock (`chat_lock`, held inside `open_item`) covers the whole read-then-write
    (C11, D-TG-81)."""
    async with session_factory() as session:
        burst = await assemble_burst(
            session,
            telegram_chat_id=telegram_chat_id,
            telegram_user_id=telegram_user_id,
            message_thread_id=message_thread_id,
            around=around,
            gap_s=gap_s,
        )
        item_id = await open_item(session, burst)
        await session.commit()

    if item_id is not None:
        logger.info(
            "attention item opened",
            extra={"chat_id": telegram_chat_id, "item_id": item_id},
        )
    return item_id


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def evaluate_attention(
    telegram_chat_id: int,
    telegram_user_id: int,
    message_thread_id: int | None,
    around_timestamp: float,
) -> None:
    """`around_timestamp` is a Unix epoch float — the originating message's own `sent_at`
    (never the judgement time, B2) — since a dramatiq message body is JSON and cannot carry a
    `datetime` directly."""
    settings = load_settings()
    around = datetime.fromtimestamp(around_timestamp, tz=UTC)
    asyncio.run(
        evaluate_attention_once(
            _default_session_factory(),
            telegram_chat_id=telegram_chat_id,
            telegram_user_id=telegram_user_id,
            message_thread_id=message_thread_id,
            around=around,
            gap_s=settings.moderation_burst_gap_s,
        )
    )
