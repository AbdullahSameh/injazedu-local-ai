"""The `ping` diagnostic actor (research D-10, data-model.md §4).

Proves the enqueue -> execute -> observe loop without a database table: the outcome is written
to `ai:diag:{nonce}` in Redis, TTL 300 s, and read back by the API's GET endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import UTC, datetime

import dramatiq
import redis

from app.infrastructure.config import load_settings

logger = logging.getLogger(__name__)

RESULT_KEY_PREFIX = "ai:diag"
RESULT_TTL_S = 300


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dramatiq.actor(max_retries=0)
def ping(nonce: str, should_fail: bool = False) -> None:
    settings = load_settings()
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"{RESULT_KEY_PREFIX}:{nonce}"
    finished_at = datetime.now(UTC).isoformat()

    if should_fail:
        error = RuntimeError("diagnostic failure requested")
        payload = {
            "status": "failed",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "finished_at": finished_at,
            "worker": _worker_id(),
        }
        client.setex(key, RESULT_TTL_S, json.dumps(payload))
        logger.error("diagnostic ping failed", extra={"nonce": nonce})
        raise error

    payload = {
        "status": "completed",
        "result": "pong",
        "finished_at": finished_at,
        "worker": _worker_id(),
    }
    client.setex(key, RESULT_TTL_S, json.dumps(payload))
    logger.info("diagnostic ping completed", extra={"nonce": nonce})
