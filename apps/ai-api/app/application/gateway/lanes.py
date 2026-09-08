"""The machine-wide execution lane (`llm` | `embed`), held as a Redis lease (research D-33,
data-model.md §3, contracts/gateway-interface.md §6).

⚠ Not an `asyncio.Semaphore`: Ollama does not serialise concurrent generations (measured, probe
5), and M0 runs two worker processes plus the API — an in-process lock would admit three
concurrent generations while each reported itself compliant. Single occupancy must therefore be
enforced machine-wide, in Redis, not in process memory.

Occupancy is a single lease key, claimed with `SET … PX … NX` — Redis guarantees that command is
atomic, so exactly one acquirer can ever hold it, with no separate "pop a token, then set its
lease" step to race against (an earlier version of this module had exactly that race: a fast
concurrent acquirer could slip through the gap between the pop and the lease `SET`). A holder
killed mid-call is recovered for free: its lease's TTL simply expires, no explicit orphan check
needed (FR-034). A watchdog renews the TTL periodically while the call runs, and a fencing value
(the holder id) stops a delayed renewal or release from ever touching a *different* holder's lease
after expiry and reclaim. A separate list is used only as a wakeup channel, so waiters block via
`BLPOP` (FIFO among clients continuously blocked in one such call) instead of busy-polling.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Protocol

from redis.asyncio import Redis

from app.application.gateway.errors import ModelTimeoutError

# Compare-and-delete: only the current holder's own release can clear the lease, never a stale
# holder's delayed call racing a reclaim by someone else. Always pings the wakeup channel so a
# blocked waiter retries promptly, whether or not this caller still owned the lease.
_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
end
redis.call('LPUSH', KEYS[2], '1')
return 1
"""

# Compare-and-renew: only extends the TTL if it is still this holder's lease.
_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class LaneLike(Protocol):
    def hold(self, *, timeout_s: float) -> AbstractAsyncContextManager[str]: ...


class Lane:
    """A single-occupancy, machine-wide execution lane."""

    def __init__(
        self,
        redis: Redis,
        name: str,
        *,
        lease_ttl_s: float = 30.0,
        renew_interval_s: float = 10.0,
        poll_interval_s: float = 1.0,
        key_prefix: str = "ai:gw",
    ) -> None:
        self._redis = redis
        self._name = name
        self._lease_ttl_s = lease_ttl_s
        self._renew_interval_s = renew_interval_s
        self._poll_interval_s = poll_interval_s
        self._lease_key = f"{key_prefix}:lane:{name}:lease"
        self._wakeup_key = f"{key_prefix}:lane:{name}:tokens"

    async def acquire(self, *, timeout_s: float, holder: str | None = None) -> str:
        """Claim the lease; raise `ModelTimeoutError` past `timeout_s`.

        FIFO holds for waiters continuously blocked in one `BLPOP` call — Redis only orders
        those. `poll_interval_s` bounds how long a waiter can wait before re-checking whether the
        lease has expired out from under a dead holder, so a very short interval trades some
        queue fairness for faster orphan detection; `lease_ttl_s`-scale values (the default) keep
        both practical.
        """
        holder_id = holder or uuid.uuid4().hex
        deadline = time.monotonic() + timeout_s
        ttl_ms = int(self._lease_ttl_s * 1000)

        while True:
            claimed = await self._redis.set(self._lease_key, holder_id, px=ttl_ms, nx=True)
            if claimed:
                return holder_id

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelTimeoutError(
                    f"lane {self._name!r} did not free within {timeout_s}s",
                    profile_name=f"<lane:{self._name}>",
                )
            await self._redis.blpop(
                [self._wakeup_key], timeout=max(min(remaining, self._poll_interval_s), 0.01)
            )
            # Whether that woke us or simply timed out, loop back and retry the atomic claim.

    async def release(self, token: str) -> None:
        await self._redis.eval(_RELEASE_SCRIPT, 2, self._lease_key, self._wakeup_key, token)

    async def _renew(self, token: str) -> None:
        ttl_ms = int(self._lease_ttl_s * 1000)
        while True:
            await asyncio.sleep(self._renew_interval_s)
            await self._redis.eval(_RENEW_SCRIPT, 1, self._lease_key, token, ttl_ms)

    @asynccontextmanager
    async def hold(self, *, timeout_s: float, holder: str | None = None) -> AsyncIterator[str]:
        """Acquire, hold with a renewing watchdog, and release on every exit path — success,
        failure, timeout, cancellation (FR-034)."""
        token = await self.acquire(timeout_s=timeout_s, holder=holder)
        watchdog = asyncio.create_task(self._renew(token))
        try:
            yield token
        finally:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
            await self.release(token)
