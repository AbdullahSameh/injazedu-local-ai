"""GET /health and GET /health/live over real HTTP-shaped requests, probes stubbed.

No real Postgres/Redis/Ollama is touched — each probe is monkeypatched so the test exercises the
endpoint's own contract: complete four-component body, status-code mapping, model_runtime never
affecting the overall verdict (FR-007, SC-003).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from app.application.health_service import ComponentReport, ComponentState
from app.application.probes import broker as broker_probe
from app.application.probes import database as database_probe
from app.application.probes import model_runtime as model_runtime_probe
from app.application.probes import worker as worker_probe
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def _ok(detail: str = "") -> ComponentReport:
    return ComponentReport(status=ComponentState.OK, required=True, detail=detail)


def _down(detail: str = "") -> ComponentReport:
    return ComponentReport(status=ComponentState.DOWN, required=True, detail=detail)


async def _client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    async def _ok_db(engine: object) -> ComponentReport:
        return _ok("PostgreSQL 16, extension vector 0.8.0")

    async def _ok_broker(redis_client: object) -> ComponentReport:
        return _ok("Redis 7.4")

    async def _ok_worker(redis_client: object, ttl_s: int) -> ComponentReport:
        return _ok("1 worker")

    async def _ok_model_runtime(base_url: str) -> ComponentReport:
        return ComponentReport(status=ComponentState.OK, required=False, detail="Ollama 0.33")

    monkeypatch.setattr(database_probe, "check", _ok_db)
    monkeypatch.setattr(broker_probe, "check", _ok_broker)
    monkeypatch.setattr(worker_probe, "check", _ok_worker)
    monkeypatch.setattr(model_runtime_probe, "check", _ok_model_runtime)

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_liveness_always_returns_200(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _client(monkeypatch)
    async with client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_health_reports_all_four_components_when_everything_is_ok(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = await _client(monkeypatch)
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["components"]) == {"database", "broker", "worker", "model_runtime"}


@pytest.mark.asyncio
async def test_a_failing_required_probe_yields_503_naming_that_component(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = await _client(monkeypatch)

    async def _down_db(engine: object) -> ComponentReport:
        return _down("connection refused at postgres:5432")

    monkeypatch.setattr(database_probe, "check", _down_db)

    async with client:
        response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["components"]["database"]["status"] == "down"
    assert "connection refused" in body["components"]["database"]["detail"]
    assert set(body["components"]) == {"database", "broker", "worker", "model_runtime"}


@pytest.mark.asyncio
async def test_a_failing_model_runtime_probe_still_yields_200(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = await _client(monkeypatch)

    async def _down_model_runtime(base_url: str) -> ComponentReport:
        return ComponentReport(status=ComponentState.DOWN, required=False, detail="unreachable")

    monkeypatch.setattr(model_runtime_probe, "check", _down_model_runtime)

    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["model_runtime"]["status"] == "down"
