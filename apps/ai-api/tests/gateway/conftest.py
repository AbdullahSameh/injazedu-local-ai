"""Shared fixtures for `tests/gateway/`: an async session factory against `injaz_ai_test`, a
session-scoped seeded-profile fixture every story's tests run through, and per-run-namespaced,
TTL-bounded Redis keys for the lane/breaker tests (T018).

Assumes `injaz_ai_test` is already migrated to head — the same assumption `tests/integration/`
makes; `make test-db-reset` is the operator's step, not this fixture's.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

GATEWAY_LANE_LEASE_TTL_S = 30

_SEEDED_PROFILE_NAMES = (
    "gw-test-llm-active",
    "gw-test-llm-inactive",
    "gw-test-embedding-active",
)


@pytest.fixture(scope="session")
def gateway_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest_asyncio.fixture
async def gateway_session_factory(
    gateway_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(gateway_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def seeded_profiles(gateway_test_database_url: str) -> AsyncIterator[None]:
    """One active + one inactive `llm` profile, and one active `embedding` profile.

    Session-scoped: every story's tests resolve against the same known rows, inserted once and
    removed once, rather than each test managing its own profile lifecycle.
    """
    engine = create_async_engine(gateway_test_database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO model_profiles "
                    "(name, provider, base_url, model, role, params, dim, is_active) VALUES "
                    "('gw-test-llm-active', 'fake', NULL, 'fake-llm-active', 'llm', "
                    "  '{}'::jsonb, NULL, true), "
                    "('gw-test-llm-inactive', 'fake', NULL, 'fake-llm-inactive', 'llm', "
                    "  '{}'::jsonb, NULL, false), "
                    "('gw-test-embedding-active', 'fake', NULL, 'fake-embedding-active', "
                    "  'embedding', '{}'::jsonb, 8, true) "
                    "ON CONFLICT (name) DO NOTHING"
                )
            )
        yield
    finally:
        # Best-effort: tests/integration/test_migrations*.py deliberately leave the schema
        # torn down at session end, so the table may already be gone by the time this runs.
        try:
            async with engine.begin() as conn:
                table_exists = (
                    await conn.execute(text("SELECT to_regclass('model_profiles')"))
                ).scalar_one()
                if table_exists is not None:
                    await conn.execute(
                        text("DELETE FROM model_profiles WHERE name = ANY(:names)"),
                        {"names": list(_SEEDED_PROFILE_NAMES)},
                    )
        except SQLAlchemyError:
            pass
        await engine.dispose()


@pytest.fixture
def gateway_redis_namespace() -> str:
    """A per-test-run prefix so concurrent test runs never collide on the same lane keys."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def gateway_redis(gateway_redis_namespace: str) -> AsyncIterator[Redis]:
    """A real Redis client, scoped to keys under this run's namespace, cleaned up on teardown.

    All gateway Redis keys already carry a TTL (data-model.md §3), so a failed test cannot leave
    a lane permanently held even if this cleanup is skipped.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        async for key in client.scan_iter(match=f"ai:gw:*{gateway_redis_namespace}*", count=100):
            await client.delete(key)
        await client.aclose()
