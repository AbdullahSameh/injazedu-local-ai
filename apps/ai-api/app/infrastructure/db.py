"""Async SQLAlchemy engine and session factory over the ai_app identity.

Reads DATABASE_URL — never the migrator's (research D-12, D-05).

Two lifetimes, two pool modes:

- ``"service"`` — a long-lived process (FastAPI, the Telegram poller) owns one engine for its whole
  life and keeps SQLAlchemy's normal connection pool.
- ``"worker"`` — a Dramatiq task runs one short-lived ``asyncio.run()`` and then its event loop is
  gone. Pooled async connections are bound to the loop that opened them, so a pool can neither be
  shared across tasks nor outlive its task: ``NullPool`` closes each connection the moment its
  session releases it. Use ``worker_session_factory`` / ``run_with_worker_session``, which also
  dispose the engine — never ``make_engine(..., pool_mode="worker")`` directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.infrastructure.config import Settings, load_settings

PoolMode = Literal["service", "worker"]


def make_engine(settings: Settings, *, pool_mode: PoolMode = "service") -> AsyncEngine:
    if pool_mode == "worker":
        return create_async_engine(settings.database_url, poolclass=NullPool)
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def worker_session_factory(
    settings: Settings | None = None,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The one owner of a worker task's engine: creates it with ``NullPool`` and disposes it on
    every exit path, including an exception out of the task body."""
    engine = make_engine(settings or load_settings(), pool_mode="worker")
    try:
        yield make_session_factory(engine)
    finally:
        await engine.dispose()


def run_with_worker_session[T](
    body: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]],
    settings: Settings | None = None,
) -> T:
    """Runs ``body(session_factory)`` in a fresh event loop and returns its result. The engine is
    disposed before the loop closes, whether ``body`` returns or raises."""

    async def _main() -> T:
        async with worker_session_factory(settings) as session_factory:
            return await body(session_factory)

    return asyncio.run(_main())
