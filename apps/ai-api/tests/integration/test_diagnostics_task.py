"""Success round trip: enqueue, then observe `completed` with its result (FR-017, SC-007).

Runs against a real Redis and a real, separate `dramatiq` worker process.
"""

from __future__ import annotations

import subprocess

import pytest
import redis
from httpx import AsyncClient

from tests.integration.conftest import poll_until


@pytest.mark.asyncio
async def test_ping_completes_and_is_observable(
    client: AsyncClient, redis_client: redis.Redis, worker: subprocess.Popen[bytes]
) -> None:
    response = await client.post("/v1/diagnostics/ping")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    nonce = body["nonce"]

    outcome = poll_until(redis_client, nonce)
    assert outcome["status"] == "completed"
    assert outcome["result"] == "pong"
    assert "worker" in outcome
    assert "finished_at" in outcome

    read_back = await client.get(f"/v1/diagnostics/ping/{nonce}")
    assert read_back.status_code == 200
    read_body = read_back.json()
    assert read_body["status"] == "completed"
    assert read_body["result"] == "pong"
