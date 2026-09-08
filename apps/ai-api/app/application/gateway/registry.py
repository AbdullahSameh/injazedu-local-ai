"""Active-profile resolution, cached for a bounded window (research D-37,
contracts/gateway-interface.md §6).

`ProfileRegistry.resolve(role)` is the first step of every gateway call: exactly one active
profile per role, or `NoActiveProfileError` naming the role (FR-011, FR-013).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.gateway.errors import NoActiveProfileError
from app.domain.model_profile import ModelProfile, Role
from app.infrastructure.models import model_profiles


def _row_to_profile(row: Any) -> ModelProfile:
    params: Mapping[str, Any] = row.params or {}
    return ModelProfile(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model=row.model,
        role=row.role,
        params=params,
        is_active=row.is_active,
        base_url=row.base_url,
        dim=row.dim,
        api_key_env=row.api_key_env,
    )


class ProfileRegistry:
    """Resolves the one active profile per role, cached for `ttl_s` seconds (D-37).

    A `clock` may be injected for tests; production callers use the default `time.monotonic`.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._ttl_s = ttl_s
        self._clock = clock
        self._cache: dict[Role, tuple[ModelProfile, float]] = {}

    async def resolve(self, role: Role) -> ModelProfile:
        now = self._clock()
        cached = self._cache.get(role)
        if cached is not None and now < cached[1]:
            return cached[0]

        profile = await self._load(role)
        self._cache[role] = (profile, now + self._ttl_s)
        return profile

    async def _load(self, role: Role) -> ModelProfile:
        async with self._session_factory() as session:
            result = await session.execute(
                select(model_profiles).where(
                    model_profiles.c.role == role, model_profiles.c.is_active.is_(True)
                )
            )
            row = result.first()

        if row is None:
            raise NoActiveProfileError(
                f"no active profile for role={role!r}", profile_name=f"<none:{role}>"
            )
        return _row_to_profile(row)
