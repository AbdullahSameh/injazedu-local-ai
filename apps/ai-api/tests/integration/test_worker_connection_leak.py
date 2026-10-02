"""Repeated worker tasks must not leave PostgreSQL connections behind.

Regression for the `ai-control` 500s ("remaining connection slots are reserved…"): each Dramatiq
task used to build a pooled engine inside `asyncio.run()` and abandon it, so the `ai_app` backend
count only ever went up. Runs against `injaz_ai_test` (`TEST_DATABASE_URL`, Principle II) and
counts real backends in `pg_stat_activity`.

The garbage collector is switched off for the loop: an abandoned engine is cyclic garbage, and a
collection that happens to run mid-test would hide the leak this test exists to catch.
"""

from __future__ import annotations

import gc
import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from app.infrastructure.db import run_with_worker_session
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

_RUNS = 25

_COUNT_BACKENDS = sa.text(
    "select count(*) from pg_stat_activity "
    "where datname = current_database() and usename = current_user "
    "and pid <> pg_backend_pid()"
)


@pytest.fixture
def monitor() -> Iterator[Engine]:
    """A separate, unpooled connection that only ever counts the others."""
    engine = sa.create_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point `load_settings()` (which every actor calls) at the test database."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def _backends(monitor: Engine) -> int:
    with monitor.connect() as conn:
        return int(conn.execute(_COUNT_BACKENDS).scalar_one())


@pytest.fixture
def gc_off() -> Iterator[None]:
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def test_repeated_actor_runs_do_not_accumulate_connections(
    monitor: Engine, worker_env: None, gc_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real `drain_pending_updates` actor and the real engine lifecycle; only the table query
    is swapped for `select 1`, so the test does not depend on the schema the migration tests leave
    behind mid-suite."""
    from app.workers.tasks.moderation import drain_pending_updates as module

    async def opens_a_connection(session_factory: async_sessionmaker[AsyncSession]) -> int:
        async with session_factory() as session:
            await session.execute(sa.text("select 1"))
        return 0

    monkeypatch.setattr(module, "drain_pending_updates_all", opens_a_connection)

    module.drain_pending_updates.fn()  # warm-up: anything opened once is part of the baseline
    before = _backends(monitor)

    for _ in range(_RUNS):
        module.drain_pending_updates.fn()

    assert _backends(monitor) <= before


def test_a_failing_task_still_releases_its_connection(
    monitor: Engine, worker_env: None, gc_off: None
) -> None:
    class Boom(Exception):
        pass

    async def opens_a_connection_then_fails(
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        async with session_factory() as session:
            await session.execute(sa.text("select 1"))
        raise Boom

    before = _backends(monitor)

    for _ in range(_RUNS):
        with pytest.raises(Boom):
            run_with_worker_session(opens_a_connection_then_fails)

    assert _backends(monitor) <= before
