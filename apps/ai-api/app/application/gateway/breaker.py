"""Redis-backed circuit breaker, keyed by profile (research D-32, contracts/gateway-interface.md
§5–6).

State is shared in Redis, not per process: one process discovering the runtime is down should
spare the others from each learning it independently. Only retryable failures count toward the
trip (FR-033) — that decision is the gateway's, made by which calls reach `record_failure` at all;
this class itself only counts what it is told to. No separate half-open lock is needed: the lane
above the breaker already bounds a profile to one call in flight, so the first call after
`open_until` passes is naturally the only trial — it closes the breaker on success and reopens it
on failure.
"""

from __future__ import annotations

from typing import Protocol

from redis.asyncio import Redis

from app.application.gateway.errors import CircuitOpenError

_FAILURES_TTL_S = 120


class BreakerLike(Protocol):
    async def before_call(self, profile_id: int, *, profile_name: str) -> None: ...

    async def record_success(self, profile_id: int) -> None: ...

    async def record_failure(self, profile_id: int) -> None: ...


class CircuitBreaker:
    """Opens after `threshold` consecutive retryable failures for a profile; half-open after
    `open_s`."""

    def __init__(
        self,
        redis: Redis,
        *,
        threshold: int = 5,
        open_s: int = 30,
        key_prefix: str = "ai:gw:breaker",
    ) -> None:
        self._redis = redis
        self._threshold = threshold
        self._open_s = open_s
        self._key_prefix = key_prefix

    def _failures_key(self, profile_id: int) -> str:
        return f"{self._key_prefix}:{profile_id}:failures"

    def _open_until_key(self, profile_id: int) -> str:
        return f"{self._key_prefix}:{profile_id}:open_until"

    async def before_call(self, profile_id: int, *, profile_name: str) -> None:
        if await self._redis.get(self._open_until_key(profile_id)) is not None:
            raise CircuitOpenError(
                f"circuit open for profile {profile_name!r}", profile_name=profile_name
            )

    async def record_success(self, profile_id: int) -> None:
        await self._redis.delete(self._failures_key(profile_id), self._open_until_key(profile_id))

    async def record_failure(self, profile_id: int) -> None:
        key = self._failures_key(profile_id)
        count = await self._redis.incr(key)
        await self._redis.expire(key, _FAILURES_TTL_S)
        if count >= self._threshold:
            await self._redis.set(self._open_until_key(profile_id), "1", ex=self._open_s)
