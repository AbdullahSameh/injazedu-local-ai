"""Failure path: the outcome is `failed` carrying `error_type` and `error_message`, and the
worker processes a subsequent task successfully (FR-018).
"""

from __future__ import annotations

import subprocess

import pytest
import redis
from httpx import AsyncClient

from tests.integration.conftest import poll_until


@pytest.mark.asyncio
async def test_failing_ping_is_recorded_and_worker_survives(
    client: AsyncClient, redis_client: redis.Redis, worker: subprocess.Popen[bytes]
) -> None:
    failing_response = await client.post("/v1/diagnostics/ping", json={"should_fail": True})
    assert failing_response.status_code == 202
    failing_nonce = failing_response.json()["nonce"]

    outcome = poll_until(redis_client, failing_nonce)
    assert outcome["status"] == "failed"
    assert outcome["error_type"] == "RuntimeError"
    assert outcome["error_message"] == "diagnostic failure requested"

    # The worker stays available for the next task.
    ok_response = await client.post("/v1/diagnostics/ping")
    assert ok_response.status_code == 202
    ok_nonce = ok_response.json()["nonce"]

    ok_outcome = poll_until(redis_client, ok_nonce)
    assert ok_outcome["status"] == "completed"
    assert ok_outcome["result"] == "pong"
