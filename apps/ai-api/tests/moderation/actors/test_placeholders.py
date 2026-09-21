"""Placeholder identities: mapping a moderator before that person has ever been observed
(FR-027, FR-028, SC-009, D-TG-52).

Exercises `app.application.moderation.identities.map_moderator` and `create_placeholder_identity`
(implemented, T042/T044).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.moderation.identities import map_moderator, upsert_identity
from app.infrastructure.models_moderation import telegram_users
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_mapping_a_never_observed_identifier_creates_exactly_one_placeholder(
    actors_session_factory: async_sessionmaker[AsyncSession],
    fetch_user: Any,
) -> None:
    tg_user_id = _rand_id()

    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Future Moderator"
    )

    row = await fetch_user(tg_user_id=tg_user_id)
    assert row is not None
    assert row["display_name"] is None
    assert row["username"] is None
    assert row["first_seen_at"] is None

    async with actors_session_factory() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(telegram_users)
                .where(telegram_users.c.tg_user_id == tg_user_id)
            )
        ).scalar_one()
    assert count == 1


async def test_the_first_real_observation_fills_the_placeholder_in_creating_no_second_identity(
    actors_session_factory: async_sessionmaker[AsyncSession],
    fetch_user: Any,
) -> None:
    tg_user_id = _rand_id()
    observed_at = datetime.fromtimestamp(1_700_000_000, tz=UTC)

    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Future Moderator"
    )

    async with actors_session_factory() as session:
        surrogate_id = await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="now_seen",
            display_name="Now Seen",
            is_bot=False,
            observed_at=observed_at,
        )
        await session.commit()

    row = await fetch_user(tg_user_id=tg_user_id)
    assert row is not None
    assert row["id"] == surrogate_id
    assert row["display_name"] == "Now Seen"
    assert row["username"] == "now_seen"
    assert row["first_seen_at"] == observed_at
    assert row["last_seen_at"] == observed_at

    async with actors_session_factory() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(telegram_users)
                .where(telegram_users.c.tg_user_id == tg_user_id)
            )
        ).scalar_one()
    assert count == 1
