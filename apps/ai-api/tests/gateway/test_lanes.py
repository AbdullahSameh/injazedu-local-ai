"""The machine-wide lane: single occupancy, FIFO waiting, and crash recovery (research D-33,
data-model.md §3, contracts/gateway-interface.md §6, T051-T053).

⚠ Every acquirer here gets its own `Lane` over its own Redis connection — no Python object or
event-loop state is shared between them — standing in for separate OS processes, since D-33's
whole point is that correctness must not depend on shared in-process state. `gateway_redis` (T018)
scopes every key to this test run's namespace so concurrent test runs never collide.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from app.application.gateway.errors import ModelTimeoutError
from app.application.gateway.lanes import Lane
from redis.asyncio import Redis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _new_client() -> Redis:
    return Redis.from_url(_REDIS_URL, decode_responses=True)


def _lane(redis: Redis, namespace: str, name: str = "llm", **overrides: object) -> Lane:
    defaults: dict[str, object] = dict(
        lease_ttl_s=1.0, renew_interval_s=0.3, poll_interval_s=0.2, key_prefix=f"ai:gw:{namespace}"
    )
    defaults.update(overrides)
    return Lane(redis, name, **defaults)  # type: ignore[arg-type]


class _Acquirer:
    """A standalone `Lane` + Redis connection — a stand-in for one separate process."""

    def __init__(self, namespace: str, name: str = "llm", **overrides: object) -> None:
        self.redis = _new_client()
        self.lane = _lane(self.redis, namespace, name, **overrides)

    async def aclose(self) -> None:
        await self.redis.aclose()


async def test_concurrent_acquirers_from_independent_lanes_never_overlap(
    gateway_redis_namespace: str,
) -> None:
    concurrency = 6
    in_flight = 0
    max_in_flight = 0
    acquirers = [_Acquirer(gateway_redis_namespace) for _ in range(concurrency)]

    async def run(acquirer: _Acquirer) -> None:
        nonlocal in_flight, max_in_flight
        async with acquirer.lane.hold(timeout_s=10.0):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)  # yields control — a real overlap would show up here
            in_flight -= 1

    try:
        await asyncio.gather(*(run(a) for a in acquirers))
    finally:
        for acquirer in acquirers:
            await acquirer.aclose()

    assert max_in_flight == 1


async def test_waiting_is_fifo(gateway_redis_namespace: str) -> None:
    # A `poll_interval_s` longer than this test's whole run: FIFO is a guarantee about clients
    # continuously blocked in one `BLPOP` call, and Redis only orders those. A shorter interval
    # would let a waiter's periodic orphan-check re-issue its `BLPOP` at the wrong moment and
    # jump the queue — a real, accepted trade-off against bounded orphan-detection latency
    # (`test_orphan_holder_frees_the_lane_within_the_lease_ttl` exercises that side instead).
    holder = _Acquirer(gateway_redis_namespace, name="fifo", poll_interval_s=5.0)
    waiters = [
        _Acquirer(gateway_redis_namespace, name="fifo", poll_interval_s=5.0) for _ in range(3)
    ]
    order: list[int] = []

    try:
        held_token = await holder.lane.acquire(timeout_s=5.0)

        async def wait_and_record(index: int, acquirer: _Acquirer) -> None:
            async with acquirer.lane.hold(timeout_s=5.0):
                order.append(index)

        tasks = []
        for index, acquirer in enumerate(waiters):
            tasks.append(asyncio.create_task(wait_and_record(index, acquirer)))
            await asyncio.sleep(0.1)  # let each waiter start blocking before the next queues up

        await asyncio.sleep(0.1)
        await holder.lane.release(held_token)

        await asyncio.gather(*tasks)
        assert order == [0, 1, 2]
    finally:
        await holder.aclose()
        for acquirer in waiters:
            await acquirer.aclose()


async def test_lane_releases_on_success_failure_and_cancellation(
    gateway_redis_namespace: str,
) -> None:
    acquirer = _Acquirer(gateway_redis_namespace, name="exits")

    async def _assert_capacity_restored() -> None:
        """A fast probe-acquire: if the previous holder didn't release, this times out."""
        probe = await acquirer.lane.acquire(timeout_s=1.0)
        await acquirer.lane.release(probe)

    try:
        async with acquirer.lane.hold(timeout_s=5.0):
            pass
        await _assert_capacity_restored()

        with pytest.raises(RuntimeError):
            async with acquirer.lane.hold(timeout_s=5.0):
                raise RuntimeError("boom")
        await _assert_capacity_restored()

        with pytest.raises(ModelTimeoutError):
            async with acquirer.lane.hold(timeout_s=5.0):
                raise ModelTimeoutError("simulated attempt timeout", profile_name="p")
        await _assert_capacity_restored()

        async def _hold_forever() -> None:
            async with acquirer.lane.hold(timeout_s=5.0):
                await asyncio.sleep(10)

        task = asyncio.create_task(_hold_forever())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _assert_capacity_restored()
    finally:
        await acquirer.aclose()


async def test_orphan_holder_frees_the_lane_within_the_lease_ttl(
    gateway_redis_namespace: str,
) -> None:
    lease_ttl_s = 1.0
    acquirer = _Acquirer(
        gateway_redis_namespace, name="orphan", lease_ttl_s=lease_ttl_s, renew_interval_s=0.3
    )

    try:
        # Acquired via `.acquire()` directly, not `.hold()` — no watchdog, no release. This
        # models a holder that dies mid-call: the lease will expire and nothing frees the token.
        await acquirer.lane.acquire(timeout_s=5.0)

        started = time.monotonic()
        recovered_token = await acquirer.lane.acquire(timeout_s=lease_ttl_s + 5.0)
        recovered_within = time.monotonic() - started
        await acquirer.lane.release(recovered_token)

        assert recovered_within <= lease_ttl_s + 2.0
    finally:
        await acquirer.aclose()
