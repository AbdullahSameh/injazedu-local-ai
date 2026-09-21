"""Moderator identity constraints (FR-025, FR-026, FR-029, FR-030) — the two directions of the
one-to-one identity/moderator link, and that deactivation changes only availability.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.identities import map_moderator, upsert_identity
from app.infrastructure.models_moderation import moderator_group_assignments, moderators
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_mapping_one_identity_to_two_moderators_is_refused(
    actors_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tg_user_id = _rand_id()
    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="First Mapping"
    )

    with pytest.raises(IntegrityError):
        await map_moderator(
            actors_session_factory, tg_user_id=tg_user_id, display_name="Second Mapping"
        )


def test_a_moderator_row_must_reference_exactly_one_identity(actors_sync_engine: Engine) -> None:
    """`telegram_user_id` is a single, `NOT NULL` column (`data-model.md` §3) — together with the
    uniqueness above, that is both directions of FR-026: an identity cannot map to two moderators,
    and a moderator cannot exist without, or hold more than, one identity — there is structurally
    no second column to put one in."""
    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderators (telegram_user_id, display_name) "
                        "VALUES (NULL, 'No Identity')"
                    )
                )
        finally:
            trans.rollback()


async def test_deactivation_preserves_the_record_and_assignment_history(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = _rand_id()
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Moderator Name"
    )

    async with actors_session_factory() as session:
        await session.execute(
            moderator_group_assignments.insert().values(
                telegram_chat_id=chat_pk,
                moderator_id=moderator_id,
                assignment_role="primary",
                valid_from=sa.func.now(),
            )
        )
        await session.commit()

    async with actors_session_factory() as session:
        await session.execute(
            moderators.update().where(moderators.c.id == moderator_id).values(is_active=False)
        )
        await session.commit()

    async with actors_session_factory() as session:
        moderator_row = (
            await session.execute(sa.select(moderators).where(moderators.c.id == moderator_id))
        ).mappings().one()
        assignment_row = (
            await session.execute(
                sa.select(moderator_group_assignments).where(
                    moderator_group_assignments.c.moderator_id == moderator_id
                )
            )
        ).mappings().one()

    assert moderator_row["is_active"] is False
    assert moderator_row["display_name"] == "Moderator Name"
    assert assignment_row["valid_to"] is None
    assert assignment_row["assignment_role"] == "primary"


async def test_reports_use_the_operator_set_display_name_not_a_platform_rename(
    actors_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tg_user_id = _rand_id()
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Operator Chosen Name"
    )

    # A platform profile rename, observed later through the ordinary upsert path...
    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="new_platform_handle",
            display_name="New Platform Name",
            is_bot=False,
            observed_at=datetime.fromtimestamp(1_800_000_000, tz=UTC),
        )
        await session.commit()

    async with actors_session_factory() as session:
        moderator_row = (
            await session.execute(sa.select(moderators).where(moderators.c.id == moderator_id))
        ).mappings().one()

    # ...never touches the moderator's own, operator-set name (FR-029).
    assert moderator_row["display_name"] == "Operator Chosen Name"
