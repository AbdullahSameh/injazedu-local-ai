"""`app.telegram_main._stop_on_sigterm`: a SIGTERM — what `docker stop` sends when a deploy
recreates `ai-telegram` — releases `ai:tg:poll:lease` and exits 0, so the replacement claims the
lease at once instead of standing down (2026-10-21's deploy: the old poller was killed with the
lease still held, and the new one exited 0 under `restart: on-failure`).

The poller runs in a child process and receives a real signal: without the handler the child dies
of SIGTERM with the lease still set, and this test fails rather than the test run.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

from app.application.moderation.ingest import hold_poll_lease
from redis.asyncio import Redis

_APP_DIR = Path(__file__).resolve().parents[3]
_LEASE = "ai:tg:poll:lease"

_CHILD = """
import asyncio, os
from redis.asyncio import Redis
from app.application.moderation.ingest import hold_poll_lease
from app.telegram_main import _stop_on_sigterm

async def poller(redis):
    async with hold_poll_lease(redis, ttl_s=30.0, renew_interval_s=10.0):
        print("held", flush=True)
        await asyncio.Event().wait()  # a long poll that never returns

async def main():
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        await _stop_on_sigterm(poller(redis))
    finally:
        await redis.aclose()

asyncio.run(main())
"""


async def test_sigterm_releases_the_poll_lease_and_exits_zero(poll_lease_redis: Redis) -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        cwd=_APP_DIR,
        env={**os.environ, "REDIS_URL": redis_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdout is not None and child.stderr is not None
    try:
        line = await asyncio.wait_for(asyncio.to_thread(child.stdout.readline), timeout=30)
        assert line.strip() == b"held", child.stderr.read().decode()
        assert await poll_lease_redis.exists(_LEASE) == 1

        child.send_signal(signal.SIGTERM)
        returncode = await asyncio.to_thread(child.wait, 10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

    assert returncode == 0, child.stderr.read().decode()
    assert await poll_lease_redis.exists(_LEASE) == 0

    # The replacement claims it at once — no wait for the TTL.
    async with hold_poll_lease(poll_lease_redis, ttl_s=5.0, renew_interval_s=1.0):
        pass
