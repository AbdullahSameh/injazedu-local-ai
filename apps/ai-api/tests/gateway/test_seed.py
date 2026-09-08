"""Seed idempotency and operator-edit survival (research D-36, SC-013, FR-010).

Runs `seed_profiles()` against `TEST_DATABASE_URL` — never the operator's database
(Constitution Principle II) — by pointing `DATABASE_URL` at it for the duration of the test.
"""

from __future__ import annotations

import os

import pytest
from app.scripts.seed_profiles import _ROSTER, seed_profiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_NAMES = [str(row["name"]) for row in _ROSTER]


@pytest.fixture
def _seed_targets_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])


async def _deactivate_active(
    session_factory: async_sessionmaker[AsyncSession], role: str
) -> str | None:
    """Free up `role` so the roster's active row can be inserted without tripping the
    partial unique index — some other gateway test's session-scoped fixture may already have
    an active profile for this role. Returns the name to restore, if any."""
    async with session_factory() as session:
        row = (
            await session.execute(
                text("SELECT name FROM model_profiles WHERE role = :role AND is_active"),
                {"role": role},
            )
        ).first()
        if row is None:
            return None
        await session.execute(
            text("UPDATE model_profiles SET is_active = false WHERE name = :name"),
            {"name": row.name},
        )
        await session.commit()
        return str(row.name)


async def _reactivate(session_factory: async_sessionmaker[AsyncSession], name: str | None) -> None:
    if name is None:
        return
    async with session_factory() as session:
        await session.execute(
            text("UPDATE model_profiles SET is_active = true WHERE name = :name"), {"name": name}
        )
        await session.commit()


async def _delete_roster(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM model_profiles WHERE name = ANY(:names)"), {"names": _NAMES}
        )
        await session.commit()


@pytest.mark.usefixtures("_seed_targets_test_database")
async def test_seeding_twice_produces_the_same_rows_with_no_duplicates(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    previously_active_llm = await _deactivate_active(gateway_session_factory, "llm")
    previously_active_embedding = await _deactivate_active(gateway_session_factory, "embedding")
    try:
        first_run = seed_profiles()
        second_run = seed_profiles()

        assert first_run == len(_ROSTER)
        assert second_run == 0

        async with gateway_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM model_profiles WHERE name = ANY(:names)"),
                    {"names": _NAMES},
                )
            ).scalar_one()
        assert count == len(_ROSTER)
    finally:
        await _delete_roster(gateway_session_factory)
        await _reactivate(gateway_session_factory, previously_active_llm)
        await _reactivate(gateway_session_factory, previously_active_embedding)


@pytest.mark.usefixtures("_seed_targets_test_database")
async def test_reseed_does_not_overwrite_an_operators_edit(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    previously_active_llm = await _deactivate_active(gateway_session_factory, "llm")
    previously_active_embedding = await _deactivate_active(gateway_session_factory, "embedding")
    try:
        seed_profiles()

        async with gateway_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE model_profiles SET base_url = :url WHERE name = 'ollama-gemma4-e2b'"
                ),
                {"url": "http://operator-edited-endpoint:11434/v1"},
            )
            await session.commit()

        seed_profiles()

        async with gateway_session_factory() as session:
            base_url = (
                await session.execute(
                    text("SELECT base_url FROM model_profiles WHERE name = 'ollama-gemma4-e2b'")
                )
            ).scalar_one()
        assert base_url == "http://operator-edited-endpoint:11434/v1"
    finally:
        await _delete_roster(gateway_session_factory)
        await _reactivate(gateway_session_factory, previously_active_llm)
        await _reactivate(gateway_session_factory, previously_active_embedding)
