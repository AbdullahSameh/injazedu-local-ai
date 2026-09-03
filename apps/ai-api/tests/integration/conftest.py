"""Fixtures for the diagnostics integration tests (T041, T042, T045).

Runs against a real Redis (REDIS_URL, not test-namespaced — the keys are ephemeral and
self-contained, so Principle II's `_test` guard applies only to Postgres) and a real, separate
`dramatiq` worker process, proving FR-016's "separate process" requirement for real rather than
mocking it away.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import redis
from httpx import ASGITransport, AsyncClient

APP_DIR = Path(__file__).resolve().parents[2]

WORKER_ENV = {
    **os.environ,
    "REDIS_URL": "redis://localhost:6379/0",
    "DATABASE_URL": "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai",
}


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", WORKER_ENV["DATABASE_URL"])
    monkeypatch.setenv("REDIS_URL", WORKER_ENV["REDIS_URL"])


@pytest.fixture
async def client(app_env: None) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def redis_client() -> Iterator[redis.Redis]:
    client = redis.Redis.from_url(WORKER_ENV["REDIS_URL"], decode_responses=True)
    try:
        yield client
    finally:
        client.close()


def _clear_stale_heartbeats() -> None:
    client = redis.Redis.from_url(WORKER_ENV["REDIS_URL"], decode_responses=True)
    try:
        for key in client.scan_iter(match="ai:worker:heartbeat:*", count=100):
            client.delete(key)
    finally:
        client.close()


def start_worker() -> subprocess.Popen[bytes]:
    _clear_stale_heartbeats()
    args = [
        sys.executable,
        "-m",
        "dramatiq",
        "app.workers.main",
        "--processes",
        "1",
        "--threads",
        "2",
    ]
    process = subprocess.Popen(
        args,
        cwd=APP_DIR,
        env=WORKER_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for_worker_ready(process)
    return process


def _wait_for_worker_ready(process: subprocess.Popen[bytes], timeout_s: float = 15.0) -> None:
    client = redis.Redis.from_url(WORKER_ENV["REDIS_URL"], decode_responses=True)
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read().decode() if process.stdout else ""
                raise RuntimeError(f"worker process exited early:\n{output}")
            if any(client.scan_iter(match="ai:worker:heartbeat:*", count=100)):
                return
            time.sleep(0.2)
    finally:
        client.close()
    process.kill()
    raise TimeoutError("worker did not report a heartbeat in time")


def stop_worker(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def worker() -> Iterator[subprocess.Popen[bytes]]:
    process = start_worker()
    try:
        yield process
    finally:
        stop_worker(process)


def poll_until(redis_client: redis.Redis, nonce: str, timeout_s: float = 10.0) -> dict[str, str]:
    import json

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = redis_client.get(f"ai:diag:{nonce}")
        if raw is not None:
            return dict(json.loads(raw))
        time.sleep(0.1)
    raise TimeoutError(f"no outcome recorded for nonce {nonce} within {timeout_s}s")
