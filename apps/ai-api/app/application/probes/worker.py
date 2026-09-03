"""Worker probe: at least one unexpired heartbeat key means the worker is alive (research D-09).

Expired keys vanish on their own (SETEX TTL) — a heartbeat key existing at all means unexpired.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.application.health_service import ComponentReport, ComponentState

REQUIRED = True

HEARTBEAT_PATTERN = "ai:worker:heartbeat:*"


async def check(redis_client: Redis, ttl_s: int) -> ComponentReport:
    live_count = 0
    async for _ in redis_client.scan_iter(match=HEARTBEAT_PATTERN, count=100):
        live_count += 1
        break

    if live_count == 0:
        return ComponentReport(
            status=ComponentState.DOWN,
            required=REQUIRED,
            detail=f"no heartbeat within {ttl_s}s",
        )

    return ComponentReport(
        status=ComponentState.OK,
        required=REQUIRED,
        detail="at least one worker heartbeat is live",
    )
