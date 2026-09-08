"""Empirical proof that the `llm` lane admits at most one caller at a time, machine-wide
(research D-33, FR-029, contracts/gateway-interface.md §6).

Fires several simultaneous acquire-hold-release cycles over independent Redis connections —
standing in for the API process and both workers — and reports the maximum observed in-flight
count. A non-zero exit means the lane failed to serialise them.
"""

from __future__ import annotations

import asyncio
import sys

from app.application.gateway.lanes import Lane
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.redis import make_redis_client

_SIMULATED_CALLERS = 3  # the API process + the two M0 worker processes
_HOLD_S = 0.5


async def _simulate_caller(
    settings: Settings, counters: dict[str, int], lock: asyncio.Lock
) -> None:
    redis = make_redis_client(settings)
    lane = Lane(
        redis,
        "llm",
        lease_ttl_s=settings.gateway_lane_lease_ttl_s,
        renew_interval_s=settings.gateway_lane_renew_s,
    )
    try:
        async with lane.hold(timeout_s=settings.gateway_call_timeout_s):
            async with lock:
                counters["in_flight"] += 1
                counters["max_in_flight"] = max(counters["max_in_flight"], counters["in_flight"])
            await asyncio.sleep(_HOLD_S)
            async with lock:
                counters["in_flight"] -= 1
    finally:
        await redis.aclose()


async def _run() -> int:
    settings = load_settings()
    counters = {"in_flight": 0, "max_in_flight": 0}
    lock = asyncio.Lock()

    await asyncio.gather(
        *(_simulate_caller(settings, counters, lock) for _ in range(_SIMULATED_CALLERS))
    )

    print(f"simulated callers: {_SIMULATED_CALLERS}")
    print(f"maximum observed in-flight: {counters['max_in_flight']}")
    if counters["max_in_flight"] > 1:
        print("check-lane: FAILED — more than one caller was admitted at once", file=sys.stderr)
        return 1
    print("check-lane: OK — the lane admitted at most one caller at a time")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
