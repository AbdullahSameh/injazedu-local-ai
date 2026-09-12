"""Shared fixtures for `tests/moderation/ingest/`: `FakeTelegramTransport` — an
`httpx.MockTransport` scripting the response shapes of `contracts/telegram-provider.md` §7
(probe 5 confirmed the round trip against real `httpx` 0.28.1) — a sleep recorder for asserting
backoff/`retry_after` behaviour without slowing tests down, and an async session factory against
`injaz_ai_test` via `TEST_DATABASE_URL`, following `tests/gateway/conftest.py`.

Assumes `injaz_ai_test` is already migrated to head; `make test-db-reset` is the operator's step.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.infrastructure.models_moderation import (
    ingestion_gaps,
    ingestion_state,
    telegram_chats,
    telegram_updates,
)
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_APP_DIR = Path(__file__).resolve().parents[3]


class FakeTelegramTransport:
    """Scripts one queue of responses per Bot API method. `enqueue*` appends; each call to that
    method pops the next entry. Popping an empty queue is a test-authoring error, not a fake
    "steady state" — it raises loudly rather than silently replaying a stale response."""

    def __init__(self) -> None:
        self._queues: dict[str, list[httpx.Response | Exception]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def enqueue_ok(self, method: str, result: Any) -> None:
        self._queue(method, httpx.Response(200, json={"ok": True, "result": result}))

    def enqueue_error(
        self,
        method: str,
        status_code: int,
        *,
        description: str = "error",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {"ok": False, "error_code": status_code, "description": description}
        if parameters is not None:
            body["parameters"] = parameters
        self._queue(method, httpx.Response(status_code, json=body))

    def enqueue_exception(self, method: str, exc: Exception) -> None:
        self._queue(method, exc)

    def _queue(self, method: str, entry: httpx.Response | Exception) -> None:
        self._queues.setdefault(method, []).append(entry)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        params: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.calls.append((method, params))
        queue = self._queues.get(method)
        if not queue:
            raise AssertionError(
                f"FakeTelegramTransport: no scripted response queued for {method!r}"
            )
        entry = queue.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)


class RecordingSleep:
    """A stand-in for `asyncio.sleep` that records the requested durations instead of waiting,
    so a test can assert exact backoff/`retry_after` values without taking real time."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def fake_transport() -> FakeTelegramTransport:
    return FakeTelegramTransport()


@pytest.fixture
def recording_sleep() -> RecordingSleep:
    return RecordingSleep()


def make_update(update_id: int, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """A raw Bot API update dict carrying exactly one `kind` key, as `getUpdates` would return."""
    return {"update_id": update_id, kind: body}


def make_message_update(
    update_id: int, *, chat_id: int = -1001, text: str = "hello", message_id: int | None = None
) -> dict[str, Any]:
    return make_update(
        update_id,
        "message",
        {
            "message_id": message_id or update_id,
            "date": 1_700_000_000,
            "chat": {"id": chat_id, "type": "group"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    )


def make_my_chat_member_update(
    update_id: int,
    *,
    chat_id: int = -1001,
    status: str = "member",
    can_delete_messages: bool | None = None,
) -> dict[str, Any]:
    new_member: dict[str, Any] = {"user": {"id": 999, "is_bot": True}, "status": status}
    if can_delete_messages is not None:
        new_member["can_delete_messages"] = can_delete_messages
    return make_update(
        update_id,
        "my_chat_member",
        {
            "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "date": 1_700_000_000,
            "old_chat_member": {"user": {"id": 999, "is_bot": True}, "status": "left"},
            "new_chat_member": new_member,
        },
    )


def make_migrate_to_update(update_id: int, *, old_chat_id: int, new_chat_id: int) -> dict[str, Any]:
    """The service message Telegram delivers on the **old** chat's stream when it becomes a
    supergroup (`contracts/telegram-provider.md` §1, "service messages")."""
    return make_update(
        update_id,
        "message",
        {
            "message_id": update_id,
            "date": 1_700_000_000,
            "chat": {"id": old_chat_id, "type": "group", "title": "Test Group"},
            "migrate_to_chat_id": new_chat_id,
        },
    )


def make_migrate_from_update(
    update_id: int, *, old_chat_id: int, new_chat_id: int
) -> dict[str, Any]:
    """The mirrored service message delivered on the **new** chat's stream."""
    return make_update(
        update_id,
        "message",
        {
            "message_id": update_id,
            "date": 1_700_000_000,
            "chat": {"id": new_chat_id, "type": "supergroup", "title": "Test Group"},
            "migrate_from_chat_id": old_chat_id,
        },
    )


@pytest.fixture
def ingest_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the ingestion tables if they're missing before a DB-dependent test runs.

    `test_migration_0003.py`, alphabetically earlier in this same package, deliberately starts
    and ends every one of its own tests at an *empty* schema (its own documented contract,
    mirroring `tests/integration/test_migrations.py`'s). Every other file here assumes
    `injaz_ai_test` is already at head. Only tests that actually request `ingest_session_factory`
    pay this check — tests with no database dependency stay database-free.
    """
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('telegram_updates')")).scalar_one()
    finally:
        engine.dispose()

    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def ingest_session_factory(
    ingest_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(ingest_test_database_url)
    engine = create_async_engine(ingest_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def ingest_engine(ingest_test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The raw engine, for the probes (`ingestion_probe.check`) that take one directly rather
    than a session factory — mirrors the other four probes' signatures."""
    _ensure_schema_at_head(ingest_test_database_url)
    engine = create_async_engine(ingest_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def ingest_bot_id() -> int:
    """A unique bot id per test, so each test's rows in the shared `injaz_ai_test` ingestion
    tables never collide with another test's (mirrors `gateway_redis_namespace`'s isolation)."""
    return random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
async def ingest_cleanup(
    ingest_session_factory: async_sessionmaker[AsyncSession], ingest_bot_id: int
) -> AsyncIterator[None]:
    """Deletes only the rows this test's `ingest_bot_id` created — the ingestion tables are
    shared, disposable test-DB state, not something any one test owns outright. Requested
    explicitly by tests that write through `ingest_bot_id`, not autoused, so tests with no
    database dependency (identity resolution, provider errors) stay database-free."""
    yield
    async with ingest_session_factory() as session:
        for table in (telegram_updates, ingestion_state, ingestion_gaps):
            await session.execute(table.delete().where(table.c.bot_id == ingest_bot_id))
        await session.commit()


@pytest.fixture
def ingest_chat_id() -> int:
    """A unique negative chat id per test — group and supergroup ids are negative (probe 2c).
    `telegram_chats` has no `bot_id` column (data-model.md §4: chats are global, not scoped per
    bot), so isolation between tests comes only from this being unique, mirroring
    `ingest_bot_id`."""
    return -random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
async def ingest_chat_cleanup(
    ingest_session_factory: async_sessionmaker[AsyncSession], ingest_chat_id: int
) -> AsyncIterator[None]:
    """Deletes only the `telegram_chats` row this test's `ingest_chat_id` created."""
    yield
    async with ingest_session_factory() as session:
        await session.execute(
            telegram_chats.delete().where(telegram_chats.c.chat_id == ingest_chat_id)
        )
        await session.commit()


@pytest_asyncio.fixture
async def poll_lease_redis() -> AsyncIterator[Redis]:
    """A real Redis client for `hold_poll_lease` tests (US6, D-TG-37).

    `ai:tg:poll:lease` is a single, unnamespaced, machine-wide key by design — there is exactly
    one poller per machine, never a family of named lanes to isolate by test run. So this fixture
    deletes it before *and* after each test instead, guarding against a prior crashed run leaving
    it set as well as leaving one behind for the next.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    await client.delete("ai:tg:poll:lease")
    try:
        yield client
    finally:
        await client.delete("ai:tg:poll:lease")
        await client.aclose()
