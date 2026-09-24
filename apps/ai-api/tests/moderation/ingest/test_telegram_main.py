"""`app.telegram_main._poll_once` — the composition that Phases 4-8's tested `ingest.py`
functions are actually wired into. Discovered missing while walking `quickstart.md` (T084):
the shipped entrypoint only ever exercised US1's behaviour before this. Not a re-test of each
building block (already covered under its own story's tests) — only that `_poll_once` calls
them in the right order with the right arguments.
"""

from __future__ import annotations

import sqlalchemy as sa
from app.application.moderation.ingest import next_offset
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import ingestion_gaps, ingestion_state, telegram_chats
from app.providers.telegram.client import TelegramClient
from app.telegram_main import _poll_once
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import (
    FakeTelegramTransport,
    RecordingSleep,
    make_message_update,
    make_my_chat_member_update,
)


def _settings(*, credential: str = "t") -> Settings:
    return Settings(
        DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
        REDIS_URL="redis://localhost:6379/0", TELEGRAM_BOT_TOKEN=credential,
    )


async def test_a_normal_poll_stores_discovers_the_chat_and_advances_the_position(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    fake_transport: FakeTelegramTransport,
    tick_lease_redis: Redis,
) -> None:
    fake_transport.enqueue_ok(
        "getUpdates",
        [
            make_message_update(1, chat_id=ingest_chat_id),
            make_my_chat_member_update(2, chat_id=ingest_chat_id, status="member"),
        ],
    )
    client = TelegramClient("t", transport=fake_transport.transport)

    stood_down = await _poll_once(
        ingest_session_factory,
        client,
        bot_id=ingest_bot_id,
        bot_username="injaz_test_bot",
        allowed_updates=["message", "my_chat_member"],
        settings=_settings(),
        redis=tick_lease_redis,
    )

    assert stood_down is False
    assert await next_offset(ingest_session_factory, bot_id=ingest_bot_id) == 3

    async with ingest_session_factory() as session:
        chat_row = (
            await session.execute(
                sa.select(telegram_chats.c.bot_status).where(
                    telegram_chats.c.chat_id == ingest_chat_id
                )
            )
        ).one()
    assert chat_row.bot_status == "member"


async def test_five_consecutive_409s_stand_down_via_the_same_poll_loop(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    fake_transport: FakeTelegramTransport,
    recording_sleep: RecordingSleep,
    tick_lease_redis: Redis,
) -> None:
    for _ in range(5):
        fake_transport.enqueue_error(
            "getUpdates", 409, description="Conflict: terminated by other getUpdates request"
        )
    client = TelegramClient("t", transport=fake_transport.transport)

    results = [
        await _poll_once(
            ingest_session_factory,
            client,
            bot_id=ingest_bot_id,
            bot_username=None,
            allowed_updates=["message"],
            settings=_settings(),
            redis=tick_lease_redis,
            sleep=recording_sleep,
        )
        for _ in range(5)
    ]

    assert results == [False, False, False, False, True]
    async with ingest_session_factory() as session:
        row = (
            await session.execute(
                sa.select(ingestion_state.c.stood_down_at).where(
                    ingestion_state.c.bot_id == ingest_bot_id
                )
            )
        ).one()
        gap_rows = (
            await session.execute(
                sa.select(ingestion_gaps.c.reason).where(ingestion_gaps.c.bot_id == ingest_bot_id)
            )
        ).all()
    assert row.stood_down_at is not None
    assert [r.reason for r in gap_rows] == ["conflict_409"]
