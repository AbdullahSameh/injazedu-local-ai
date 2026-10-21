"""Team writes (TG-M2.1, `specs/012-tg-m2-1-group-teams/contracts/group-teams.md` T4-T6):
`open_assignment`'s refusals, `end_assignment`, and deactivation ending every membership.

Every refusal leaves the table exactly as it was: the refused write's transaction never commits.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.assignments import (
    MembershipRefusedError,
    deactivate_moderator,
    end_assignment,
    open_assignment,
    team_at,
)
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderator_group_assignments, moderators
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _count_rows(
    session_factory: async_sessionmaker[AsyncSession], *, telegram_chat_id: int
) -> int:
    async with session_factory() as session:
        count: int = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderator_group_assignments)
                .where(moderator_group_assignments.c.telegram_chat_id == telegram_chat_id)
            )
        ).scalar_one()
        return count


async def _declared_at(session_factory: async_sessionmaker[AsyncSession], moderator_id: int) -> Any:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(moderators.c.created_at).where(moderators.c.id == moderator_id)
            )
        ).scalar_one()


async def test_an_inactive_moderator_cannot_join_a_team(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Left"
    )
    await deactivate_moderator(actors_session_factory, moderator_id=moderator_id)

    with pytest.raises(MembershipRefusedError) as exc:
        await open_assignment(
            actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
        )

    assert exc.value.reason == "inactive"
    assert await _count_rows(actors_session_factory, telegram_chat_id=chat_pk) == 0


async def test_a_backdated_membership_overlapping_the_moderators_own_is_refused(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    """T4: an ended membership followed by a backdated one that reaches back inside it would
    overlap the moderator's own history — refused, by the write, since the database constrains only
    the current row (T2)."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Twice"
    )
    first_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )
    assert await end_assignment(actors_session_factory, assignment_id=first_id) is True
    first = await fetch_assignment(assignment_id=first_id)
    inside_it = first["valid_from"] + (first["valid_to"] - first["valid_from"]) / 2

    with pytest.raises(MembershipRefusedError) as exc:
        await open_assignment(
            actors_session_factory,
            telegram_chat_id=chat_pk,
            moderator_id=moderator_id,
            valid_from=inside_it,
        )

    assert exc.value.reason == "overlap"
    assert await _count_rows(actors_session_factory, telegram_chat_id=chat_pk) == 1


async def test_a_second_current_membership_of_the_same_moderator_is_refused(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Already"
    )
    await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )

    with pytest.raises(MembershipRefusedError) as exc:
        await open_assignment(
            actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
        )

    assert exc.value.reason == "overlap"


async def test_a_membership_starting_in_the_future_is_refused(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Soon"
    )
    later = await _declared_at(actors_session_factory, moderator_id) + timedelta(days=1)

    with pytest.raises(MembershipRefusedError) as exc:
        await open_assignment(
            actors_session_factory,
            telegram_chat_id=chat_pk,
            moderator_id=moderator_id,
            valid_from=later,
        )

    assert exc.value.reason == "future"


async def test_a_membership_backdated_before_the_moderator_was_declared_is_refused(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    """T4 / D-TG-207: before the declaration, the moderator's replies were never flagged and
    their reactions never recorded — a membership covering that time would charge misses for
    questions they actually answered."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Late"
    )
    declared = await _declared_at(actors_session_factory, moderator_id)

    with pytest.raises(MembershipRefusedError) as exc:
        await open_assignment(
            actors_session_factory,
            telegram_chat_id=chat_pk,
            moderator_id=moderator_id,
            valid_from=declared - timedelta(seconds=1),
        )
    assert exc.value.reason == "before_declared"

    # The floor itself is allowed: the declaration instant is included.
    assignment_id = await open_assignment(
        actors_session_factory,
        telegram_chat_id=chat_pk,
        moderator_id=moderator_id,
        valid_from=declared,
    )
    async with actors_session_factory() as session:
        assert await team_at(session, telegram_chat_id=chat_pk, t=declared) == [moderator_id]
    assert assignment_id > 0


async def test_ending_a_membership_ends_only_that_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_a, moderator_b = [
        await map_moderator(actors_session_factory, tg_user_id=_rand_id(), display_name=name)
        for name in ("A", "B")
    ]
    id_a = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_a
    )
    id_b = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_b
    )

    assert await end_assignment(actors_session_factory, assignment_id=id_a) is True
    assert await end_assignment(actors_session_factory, assignment_id=id_a) is False

    row_a = await fetch_assignment(assignment_id=id_a)
    assert row_a["valid_to"] is not None
    assert (await fetch_assignment(assignment_id=id_b))["valid_to"] is None
    async with actors_session_factory() as session:
        assert await team_at(session, telegram_chat_id=chat_pk, t=row_a["valid_to"]) == [
            moderator_b
        ]


async def test_deactivation_ends_every_current_membership_at_one_instant(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    """T6 / D-TG-208: someone who left stops being on any team at the deactivation instant;
    their history and their colleagues' memberships stay as they are."""
    chat_one = await insert_chat(chat_id=actors_chat_id)
    chat_two = await insert_chat(chat_id=-_rand_id())
    leaving, staying = [
        await map_moderator(actors_session_factory, tg_user_id=_rand_id(), display_name=name)
        for name in ("Leaving", "Staying")
    ]
    leaving_ids = [
        await open_assignment(actors_session_factory, telegram_chat_id=chat, moderator_id=leaving)
        for chat in (chat_one, chat_two)
    ]
    staying_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_one, moderator_id=staying
    )

    ended = await deactivate_moderator(actors_session_factory, moderator_id=leaving)

    assert ended == 2
    ended_rows = [await fetch_assignment(assignment_id=i) for i in leaving_ids]
    assert ended_rows[0]["valid_to"] is not None
    assert ended_rows[0]["valid_to"] == ended_rows[1]["valid_to"]
    assert (await fetch_assignment(assignment_id=staying_id))["valid_to"] is None
    async with actors_session_factory() as session:
        is_active = (
            await session.execute(
                sa.select(moderators.c.is_active).where(moderators.c.id == leaving)
            )
        ).scalar_one()
    assert is_active is False
