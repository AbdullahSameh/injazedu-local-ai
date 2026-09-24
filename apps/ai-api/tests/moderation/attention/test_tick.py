"""T062 (US5): the tick lease admits exactly one caller per interval — across a loop of ten
calls within one interval, and across `_poll_once`'s own wiring (T066, D-TG-86, research
Finding 4). The poll loop **enqueues**, never computes: `expire_stale_items` and
`sweep_unjudged_bursts` are sent, not called inline — no derived state is written by
`app.telegram_main` itself (§7.3's boundary preserved).

`_poll_once` lives in ingest-land, not this package, but its tick wiring is TG-M3's own — this
file imports `FakeTelegramTransport` directly from `tests.moderation.ingest.conftest` (a plain
Python import, not fixture injection: siblings under `tests/moderation/` do not inherit each
other's `conftest.py`) rather than duplicating it, and uses this package's own
`attention_session_factory` for the database, since `_poll_once` takes any `async_sessionmaker`
and every ingest table already exists at revision `0005`'s head.
"""

from __future__ import annotations

import os
import random
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.application.moderation.ingest import tick_lease
from app.infrastructure.config import Settings
from app.providers.telegram.client import TelegramClient
from app.telegram_main import _poll_once
from app.workers.tasks.moderation import expire_stale_items as expire_stale_items_module
from app.workers.tasks.moderation import sweep_unjudged_bursts as sweep_unjudged_bursts_module
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import FakeTelegramTransport

_TICK_KEY = "ai:tg:tick:lease"


@pytest_asyncio.fixture
async def tick_redis() -> AsyncIterator[Redis]:
    """A real Redis client, isolated from `poll_lease_redis` by key — deleted before *and* after
    each test so a prior run's admitted lease never leaks into the next (mirrors
    `poll_lease_redis`, `tests/moderation/ingest/conftest.py`)."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    await client.delete(_TICK_KEY)
    try:
        yield client
    finally:
        await client.delete(_TICK_KEY)
        await client.aclose()


def _settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
        REDIS_URL="redis://localhost:6379/0",
        TELEGRAM_BOT_TOKEN="t",
    )


async def test_tick_lease_admits_exactly_one_caller_per_interval(tick_redis: Redis) -> None:
    first = await tick_lease(tick_redis, ttl_s=30)
    second = await tick_lease(tick_redis, ttl_s=30)

    assert first is True
    assert second is False


async def test_ten_iterations_within_one_interval_enqueue_once(tick_redis: Redis) -> None:
    results = [await tick_lease(tick_redis, ttl_s=30) for _ in range(10)]

    assert results.count(True) == 1


async def test_the_poll_loop_enqueues_rather_than_computes(
    attention_session_factory: async_sessionmaker[AsyncSession],
    tick_redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expire_calls: list[None] = []
    sweep_calls: list[None] = []
    monkeypatch.setattr(
        expire_stale_items_module.expire_stale_items,
        "send",
        lambda: expire_calls.append(None),
    )
    monkeypatch.setattr(
        sweep_unjudged_bursts_module.sweep_unjudged_bursts,
        "send",
        lambda: sweep_calls.append(None),
    )

    fake_transport = FakeTelegramTransport()
    fake_transport.enqueue_ok("getUpdates", [])
    fake_transport.enqueue_ok("getUpdates", [])
    client = TelegramClient("t", transport=fake_transport.transport)
    bot_id = random.randint(10_000_000, 2_000_000_000)

    await _poll_once(
        attention_session_factory,
        client,
        bot_id=bot_id,
        bot_username=None,
        allowed_updates=["message"],
        settings=_settings(),
        redis=tick_redis,
    )

    assert len(expire_calls) == 1  # enqueued, not computed here
    assert len(sweep_calls) == 1

    # A second iteration within the same interval: the lease is already held, so nothing more
    # is enqueued.
    await _poll_once(
        attention_session_factory,
        client,
        bot_id=bot_id,
        bot_username=None,
        allowed_updates=["message"],
        settings=_settings(),
        redis=tick_redis,
    )

    assert len(expire_calls) == 1
    assert len(sweep_calls) == 1
