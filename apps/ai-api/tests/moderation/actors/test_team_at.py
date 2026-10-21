"""`team_at(chat, t)` — the one half-open definition of "on the team" (TG-M2.1,
`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` T3, amending
`contracts/moderator-ownership.md` §3: O2, O3 and O5 now hold for a set, O1 is withdrawn).

⚠ T045: tested at the **four boundary positions** — before `valid_from`, exactly at `valid_from`
(included), exactly at `valid_to` (excluded), after `valid_to` — not near them, using an
assignment row inserted directly with fixed timestamps so the boundaries are exact rather than
inferred from wall-clock timing.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.assignments import handover, open_assignment, team_at
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderator_group_assignments, telegram_chats
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_four_boundary_positions(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Sole Member"
    )

    valid_from = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    valid_to = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)

    async with actors_session_factory() as session:
        await session.execute(
            moderator_group_assignments.insert().values(
                telegram_chat_id=chat_pk,
                moderator_id=moderator_id,
                assignment_role="primary",
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
        await session.commit()

    async with actors_session_factory() as session:
        # before valid_from
        assert (
            await team_at(
                session,
                telegram_chat_id=chat_pk,
                t=valid_from - timedelta(seconds=1),
            )
            == []
        )
        # at valid_from — included
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=valid_from)
            == [moderator_id]
        )
        # at valid_to — excluded
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=valid_to) == []
        )
        # after valid_to
        assert (
            await team_at(
                session,
                telegram_chat_id=chat_pk,
                t=valid_to + timedelta(seconds=1),
            )
            == []
        )


async def test_an_uncovered_instant_returns_no_team_never_the_current_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Current Owner"
    )
    assignment_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )
    row = await fetch_assignment(assignment_id=assignment_id)

    before_anyone = row["valid_from"] - timedelta(days=1)
    async with actors_session_factory() as session:
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=before_anyone) == []
        )


async def test_a_past_answer_is_unchanged_after_two_later_handovers(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_a = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="A"
    )
    moderator_b = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="B"
    )
    moderator_c = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="C"
    )

    id_a = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_a
    )
    row_a = await fetch_assignment(assignment_id=id_a)
    t_at_a = row_a["valid_from"]
    before_anyone = t_at_a - timedelta(days=1)

    id_b = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_b
    )
    row_b = await fetch_assignment(assignment_id=id_b)
    t_at_b = row_b["valid_from"]

    id_c = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_c
    )
    row_c = await fetch_assignment(assignment_id=id_c)
    t_at_c = row_c["valid_from"]

    # Three past instants spanning two (now-superseded) owners, checked after a second and
    # third handover have both already happened — none of them may move the answer (O5).
    async with actors_session_factory() as session:
        assert await team_at(session, telegram_chat_id=chat_pk, t=before_anyone) == []
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=t_at_a) == [moderator_a]
        )
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=t_at_b) == [moderator_b]
        )
        assert (
            await team_at(session, telegram_chat_id=chat_pk, t=t_at_c) == [moderator_c]
        )


async def test_a_backup_is_visible_but_never_on_the_team(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    primary_id_moderator = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Primary"
    )
    backup_moderator = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Backup"
    )

    primary_assignment_id = await open_assignment(
        actors_session_factory,
        telegram_chat_id=chat_pk,
        moderator_id=primary_id_moderator,
        role="primary",
    )
    backup_assignment_id = await open_assignment(
        actors_session_factory,
        telegram_chat_id=chat_pk,
        moderator_id=backup_moderator,
        role="backup",
    )

    backup_row = await fetch_assignment(assignment_id=backup_assignment_id)
    assert backup_row["moderator_id"] == backup_moderator  # visible, recorded

    primary_row = await fetch_assignment(assignment_id=primary_assignment_id)
    async with actors_session_factory() as session:
        team = await team_at(session, telegram_chat_id=chat_pk, t=primary_row["valid_from"])
        team_after_backup = await team_at(
            session, telegram_chat_id=chat_pk, t=backup_row["valid_from"]
        )
    assert team == [primary_id_moderator]
    assert team_after_backup == [primary_id_moderator]


async def test_two_concurrent_members_are_both_on_the_team(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    """T1: adding a member leaves the incumbent current. Both cover the later instant, and only
    the first covers the earlier one."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_a = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="A"
    )
    moderator_b = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="B"
    )

    id_a = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_a
    )
    id_b = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_b
    )
    row_a = await fetch_assignment(assignment_id=id_a)
    row_b = await fetch_assignment(assignment_id=id_b)
    assert row_a["valid_to"] is None

    async with actors_session_factory() as session:
        assert await team_at(session, telegram_chat_id=chat_pk, t=row_a["valid_from"]) == [
            moderator_a
        ]
        assert await team_at(
            session, telegram_chat_id=chat_pk, t=row_b["valid_from"]
        ) == sorted([moderator_a, moderator_b])


async def test_the_team_follows_a_migration_one_hop(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    """T3: a migration re-points memberships to the surviving chat, but items stay on the
    superseded one — so the superseded chat's team is read from its successor."""
    old_pk = await insert_chat(chat_id=actors_chat_id)
    new_chat_id = -_rand_id()
    new_pk = await insert_chat(chat_id=new_chat_id)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Follows"
    )
    valid_from = datetime(2024, 3, 1, 9, 0, 0, tzinfo=UTC)

    async with actors_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.id == old_pk)
            .values(migrated_to_chat_id=new_chat_id)
        )
        await session.execute(
            moderator_group_assignments.insert().values(
                telegram_chat_id=new_pk,
                moderator_id=moderator_id,
                assignment_role="primary",
                valid_from=valid_from,
            )
        )
        await session.commit()

    async with actors_session_factory() as session:
        assert await team_at(session, telegram_chat_id=old_pk, t=valid_from) == [moderator_id]
        assert await team_at(session, telegram_chat_id=new_pk, t=valid_from) == [moderator_id]
