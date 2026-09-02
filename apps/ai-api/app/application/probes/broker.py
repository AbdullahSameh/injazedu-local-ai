"""Broker probe: Redis PING, version reported in `detail`."""

from __future__ import annotations

from redis.asyncio import Redis

from app.application.health_service import ComponentReport, ComponentState

REQUIRED = True


async def check(redis_client: Redis) -> ComponentReport:
    await redis_client.ping()
    info = await redis_client.info(section="server")
    version = info.get("redis_version", "unknown")
    return ComponentReport(status=ComponentState.OK, required=REQUIRED, detail=f"Redis {version}")
