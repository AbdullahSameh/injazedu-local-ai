"""Redis client factory, reading REDIS_URL."""

from __future__ import annotations

from redis.asyncio import Redis

from app.infrastructure.config import Settings


def make_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)
