"""Active-profile resolution (research D-37, contracts/gateway-interface.md §6, FR-011, FR-013)."""

from __future__ import annotations

import pytest
from app.application.gateway.errors import NoActiveProfileError
from app.application.gateway.registry import ProfileRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.usefixtures("seeded_profiles")
async def test_resolves_the_one_active_profile_per_role(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)

    llm_profile = await registry.resolve("llm")
    embedding_profile = await registry.resolve("embedding")

    assert llm_profile.name == "gw-test-llm-active"
    assert llm_profile.role == "llm"
    assert llm_profile.is_active is True
    assert embedding_profile.name == "gw-test-embedding-active"
    assert embedding_profile.role == "embedding"
    assert embedding_profile.dim == 8


@pytest.mark.usefixtures("seeded_profiles")
async def test_no_active_profile_error_names_the_role(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)

    async with gateway_session_factory() as session:
        await session.execute(
            text("UPDATE model_profiles SET is_active = false WHERE role = 'llm'")
        )
        await session.commit()

    try:
        with pytest.raises(NoActiveProfileError) as exc_info:
            await registry.resolve("llm")
        assert "llm" in str(exc_info.value)
    finally:
        async with gateway_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE model_profiles SET is_active = true WHERE name = 'gw-test-llm-active'"
                )
            )
            await session.commit()


@pytest.mark.usefixtures("seeded_profiles")
async def test_a_profile_change_is_visible_after_the_ttl_and_not_before(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = {"now": 0.0}
    registry = ProfileRegistry(gateway_session_factory, ttl_s=30.0, clock=lambda: clock["now"])

    first = await registry.resolve("llm")
    assert first.name == "gw-test-llm-active"

    async with gateway_session_factory() as session:
        await session.execute(
            text("UPDATE model_profiles SET is_active = false WHERE name = 'gw-test-llm-active'")
        )
        await session.execute(
            text("UPDATE model_profiles SET is_active = true WHERE name = 'gw-test-llm-inactive'")
        )
        await session.commit()

    try:
        clock["now"] = 10.0
        still_cached = await registry.resolve("llm")
        assert still_cached.name == "gw-test-llm-active"  # within the TTL — stale by design

        clock["now"] = 31.0
        refreshed = await registry.resolve("llm")
        assert refreshed.name == "gw-test-llm-inactive"  # past the TTL — cache miss re-reads
    finally:
        async with gateway_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE model_profiles SET is_active = false "
                    "WHERE name = 'gw-test-llm-inactive'"
                )
            )
            await session.execute(
                text(
                    "UPDATE model_profiles SET is_active = true WHERE name = 'gw-test-llm-active'"
                )
            )
            await session.commit()


async def test_no_active_profile_error_when_nothing_is_seeded(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No `seeded_profiles` fixture here — proves the error fires with a genuinely empty table."""
    registry = ProfileRegistry(gateway_session_factory)

    async with gateway_session_factory() as session:
        existing = (
            await session.execute(text("SELECT count(*) FROM model_profiles WHERE role = 'llm'"))
        ).scalar_one()
    if existing:
        pytest.skip("another gateway test already seeded llm profiles this session")

    with pytest.raises(NoActiveProfileError) as exc_info:
        await registry.resolve("llm")

    assert "llm" in str(exc_info.value)
