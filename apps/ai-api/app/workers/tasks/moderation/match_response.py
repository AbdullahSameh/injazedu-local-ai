"""`match_response` — the live, no-delay closing path (T046, contract §4).

Scheduled per newly-derived moderator message (`app/application/moderation/messages.py`'s
`derive_message`), with no delay: an answer should close its question the moment it is captured,
unlike judgement, which must wait a full settle window for a burst to finish forming.
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.attention import match_response as _match_response
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import telegram_messages

logger = logging.getLogger(__name__)


async def match_response_once(
    session_factory: async_sessionmaker[AsyncSession], *, telegram_message_row_id: int
) -> int | None:
    """Fetches the stored message by its surrogate id and matches it against open items — one
    transaction, so the per-chat advisory lock (held inside `match_response`) covers the whole
    read-then-write (C11)."""
    async with session_factory() as session:
        message = dict(
            (
                await session.execute(
                    sa.select(telegram_messages).where(
                        telegram_messages.c.id == telegram_message_row_id
                    )
                )
            )
            .mappings()
            .one()
        )
        item_id = await _match_response(session, message)
        await session.commit()

    if item_id is not None:
        logger.info(
            "attention item answered",
            extra={"item_id": item_id, "message_id": telegram_message_row_id},
        )
    return item_id


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


@dramatiq.actor(max_retries=3)
def match_response(telegram_message_row_id: int) -> None:
    asyncio.run(
        match_response_once(
            _default_session_factory(), telegram_message_row_id=telegram_message_row_id
        )
    )
