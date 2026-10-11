"""T043 — one real classification against the local runtime, `@pytest.mark.llm` (excluded from
`make check` by `addopts`). Touches no database: it proves only that the real gateway, the real
model and each pinned instruction together return a complete, in-range answer
(`contracts/classification-pipeline.md` §2, §2a, research probe 4).
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway.errors import GatewayError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry, _row_to_profile
from app.application.moderation.classification import (
    PROMPT_VERSIONS,
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.domain.moderation.classification import CATEGORIES, SEVERITIES
from app.infrastructure.config import load_settings
from app.infrastructure.models import model_profiles
from app.providers.llm.base import StructuredRequest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class _PinnedRegistry:
    """Resolves the seeded classification profile by name, active or not — mirroring
    `smoke_moderation.py`'s own stand-in, so this test does not depend on the roster's activation
    state."""

    def __init__(self, session_factory: Any, profile_name: str) -> None:
        self._session_factory = session_factory
        self._profile_name = profile_name

    async def resolve(self, role: str) -> Any:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(model_profiles).where(model_profiles.c.name == self._profile_name)
            )
            row = result.first()
        if row is None:
            pytest.skip(f"no profile named {self._profile_name!r} is seeded")
        return _row_to_profile(row)


@pytest.mark.llm
@pytest.mark.parametrize("prompt_version", PROMPT_VERSIONS)
async def test_a_synthetic_advert_is_classified_completely_in_range(prompt_version: str) -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = ProfileRegistry(session_factory)

    try:
        await registry.resolve("moderation")
    except GatewayError:
        pinned = _PinnedRegistry(session_factory, "ollama-gemma4-e2b-moderation")
        registry = pinned  # type: ignore[assignment]

    gateway = Gateway(registry)
    text = normalize("انضموا لقناتنا لتعلم التداول واستثمار فلوسكم من هنا")
    model_input = build_model_input(text, prompt_version=prompt_version)

    try:
        response = await gateway.generate_structured(
            StructuredRequest(messages=model_input, schema_model=MessageClassificationResult),
            role="moderation",
        )
    finally:
        await engine.dispose()

    answer = response.value
    assert answer.category in CATEGORIES
    assert 0 <= answer.confidence <= 1
    assert answer.severity in SEVERITIES
