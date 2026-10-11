"""A worker task's engine must never outlive the task (the `ai-control` 500s: every Dramatiq task
built a pooled engine inside `asyncio.run()` and abandoned it, so idle connections piled up until
PostgreSQL had no slot left).

No database here: `create_async_engine` does not connect, and `AsyncEngine.dispose` is instrumented.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from app.infrastructure import db
from app.infrastructure.config import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai_test"
_WORKERS_DIR = Path(__file__).resolve().parents[2] / "app" / "workers"


class _Boom(Exception):
    pass


@pytest.fixture
def settings() -> Settings:
    return Settings.model_construct(database_url=_URL)


@dataclass
class EngineSpy:
    """Every engine `make_engine` handed out, and which of them got disposed."""

    created: list[AsyncEngine] = field(default_factory=list)
    disposed: list[AsyncEngine] = field(default_factory=list)


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch) -> EngineSpy:
    spy = EngineSpy()
    real_make_engine = db.make_engine
    real_dispose = AsyncEngine.dispose

    def spy_make_engine(settings: Settings, *, pool_mode: db.PoolMode = "service") -> AsyncEngine:
        engine = real_make_engine(settings, pool_mode=pool_mode)
        spy.created.append(engine)
        return engine

    async def spy_dispose(self: AsyncEngine, close: bool = True) -> None:
        spy.disposed.append(self)
        await real_dispose(self, close)

    monkeypatch.setattr(db, "make_engine", spy_make_engine)
    monkeypatch.setattr(AsyncEngine, "dispose", spy_dispose)
    return spy


def test_service_engine_keeps_normal_pooling(settings: Settings) -> None:
    engine = db.make_engine(settings)

    assert not isinstance(engine.pool, NullPool)


def test_worker_engine_uses_null_pool(settings: Settings) -> None:
    engine = db.make_engine(settings, pool_mode="worker")

    assert isinstance(engine.pool, NullPool)


def test_fastapi_app_engine_is_pooled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _URL)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from app.main import create_app

    assert not isinstance(create_app().state.engine.pool, NullPool)


async def test_worker_session_factory_disposes_after_success(
    settings: Settings, engines: EngineSpy
) -> None:
    async with db.worker_session_factory(settings) as session_factory:
        assert isinstance(session_factory, async_sessionmaker)
        assert engines.disposed == []

    assert len(engines.created) == 1
    assert isinstance(engines.created[0].pool, NullPool)
    assert engines.disposed == engines.created


async def test_worker_session_factory_disposes_when_the_body_raises(
    settings: Settings, engines: EngineSpy
) -> None:
    with pytest.raises(_Boom):
        async with db.worker_session_factory(settings):
            raise _Boom

    assert len(engines.created) == 1
    assert engines.disposed == engines.created


def test_run_with_worker_session_returns_the_result_and_disposes(
    settings: Settings, engines: EngineSpy
) -> None:
    async def body(session_factory: async_sessionmaker[AsyncSession]) -> str:
        return "done"

    assert db.run_with_worker_session(body, settings) == "done"
    assert len(engines.created) == 1
    assert engines.disposed == engines.created


def test_run_with_worker_session_disposes_when_the_task_raises(
    settings: Settings, engines: EngineSpy
) -> None:
    async def body(session_factory: async_sessionmaker[AsyncSession]) -> None:
        raise _Boom

    with pytest.raises(_Boom):
        db.run_with_worker_session(body, settings)

    assert len(engines.created) == 1
    assert engines.disposed == engines.created


def test_repeated_runs_leave_no_undisposed_engine(settings: Settings, engines: EngineSpy) -> None:
    async def ok(session_factory: async_sessionmaker[AsyncSession]) -> None:
        return None

    async def fail(session_factory: async_sessionmaker[AsyncSession]) -> None:
        raise _Boom

    for i in range(20):
        if i % 3 == 0:
            with pytest.raises(_Boom):
                db.run_with_worker_session(fail, settings)
        else:
            db.run_with_worker_session(ok, settings)

    assert len(engines.created) == 20
    assert all(isinstance(e.pool, NullPool) for e in engines.created)
    assert len(engines.disposed) == 20
    assert {id(e) for e in engines.disposed} == {id(e) for e in engines.created}


def _worker_sources() -> list[Path]:
    return sorted(p for p in _WORKERS_DIR.rglob("*.py"))


def test_no_worker_module_creates_an_engine_on_its_own() -> None:
    """The only way a task may obtain an engine is `worker_session_factory` /
    `run_with_worker_session`, which own its disposal. A hand-rolled `make_engine(...)` or
    `create_async_engine(...)` under `app/workers/` is how the leak came back in."""
    offenders: list[str] = []
    for path in _worker_sources():
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name in {"make_engine", "create_async_engine", "create_engine"}:
                    offenders.append(f"{path.relative_to(_WORKERS_DIR)}:{node.lineno} {name}")
            if isinstance(node, ast.FunctionDef) and node.name == "_default_session_factory":
                offenders.append(f"{path.relative_to(_WORKERS_DIR)}:{node.lineno} {node.name}")

    assert offenders == []
