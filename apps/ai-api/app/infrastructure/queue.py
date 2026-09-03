"""Dramatiq Redis broker plus the worker liveness heartbeat (research D-09).

The heartbeat runs on a daemon thread — Dramatiq exposes no liveness signal of its own, and the
health check's worker probe (app/application/probes/worker.py) reads what this writes.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time

import dramatiq
import redis
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware

from app.infrastructure.config import Settings

HEARTBEAT_KEY_PREFIX = "ai:worker:heartbeat"


class HeartbeatMiddleware(Middleware):
    def __init__(self, redis_url: str, interval_s: int, ttl_s: int) -> None:
        self._redis_url = redis_url
        self._interval_s = interval_s
        self._ttl_s = ttl_s
        self._stop = threading.Event()

    def after_process_boot(self, broker: dramatiq.Broker) -> None:
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self) -> None:
        client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        key = f"{HEARTBEAT_KEY_PREFIX}:{socket.gethostname()}:{os.getpid()}"
        while not self._stop.is_set():
            payload = json.dumps(
                {"pid": os.getpid(), "host": socket.gethostname(), "ts": time.time()}
            )
            client.setex(key, self._ttl_s, payload)
            self._stop.wait(self._interval_s)


def make_broker(settings: Settings) -> RedisBroker:
    broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
    broker.add_middleware(
        HeartbeatMiddleware(
            settings.redis_url,
            settings.worker_heartbeat_interval_s,
            settings.worker_heartbeat_ttl_s,
        )
    )
    return broker
