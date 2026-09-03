"""Tasks enqueued while no worker is running are processed once a worker starts (FR-019)."""

from __future__ import annotations

import redis
from httpx import AsyncClient

from tests.integration.conftest import poll_until, start_worker, stop_worker


async def test_queued_while_no_worker_then_processed_once_one_starts(
    client: AsyncClient, redis_client: redis.Redis
) -> None:
    response = await client.post("/v1/diagnostics/ping")
    assert response.status_code == 202
    nonce = response.json()["nonce"]

    pending = await client.get(f"/v1/diagnostics/ping/{nonce}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    worker = start_worker()
    try:
        outcome = poll_until(redis_client, nonce)
        assert outcome["status"] == "completed"
        assert outcome["result"] == "pong"
    finally:
        stop_worker(worker)
