"""⚠ The handover protocol: one transaction, close before open, one timestamp value bound to
both sides (`contracts/moderator-ownership.md` §2, D-TG-47, research Finding 2).

T047: probe 3 measured a ~10 ms hole with **zero** owners when two clock readings are used, and
**no constraint fires** — a test that checks *near* the handover instant cannot see it. These
tests assert the incumbent's `valid_to` and the successor's `valid_from` are the **identical**
value, and that exactly one owner covers that exact instant.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.assignments import handover, open_assignment, responsible_at
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderator_group_assignments
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_handover_leaves_no_hole_and_no_overlap(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
    count_current_owners_at: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_a = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Incumbent"
    )
    moderator_b = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Successor"
    )

    incumbent_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_a
    )
    successor_id = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_b
    )

    incumbent_row = await fetch_assignment(assignment_id=incumbent_id)
    successor_row = await fetch_assignment(assignment_id=successor_id)

    # (a) the identical value, not merely close.
    assert incumbent_row["valid_to"] == successor_row["valid_from"]

    at = successor_row["valid_from"]

    # (b) exactly one owner covers that exact instant.
    assert await count_current_owners_at(telegram_chat_id=chat_pk, t=at) == 1

    async with actors_session_factory() as session:
        owner = await responsible_at(session, telegram_chat_id=chat_pk, t=at)
    assert owner == moderator_b


async def test_a_second_current_primary_is_refused_with_no_partial_rows(
    actors_sync_engine: Engine,
) -> None:
    """A direct bypass of the handover protocol — two primaries opened without closing the
    first — must be rejected atomically, leaving only the original row (`test_db_invariants.py`
    covers the same constraint directly; this asserts the "no partial rows" half explicitly)."""
    chat_id = -_rand_id()
    tg_user_id_a = _rand_id()
    tg_user_id_b = _rand_id()

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk = conn.execute(
                text(
                    "INSERT INTO telegram_chats (chat_id, chat_type) "
                    "VALUES (:chat_id, 'group') RETURNING id"
                ),
                {"chat_id": chat_id},
            ).scalar_one()
            user_a = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id_a},
            ).scalar_one()
            user_b = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id_b},
            ).scalar_one()
            moderator_a = conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'A') RETURNING id"
                ),
                {"user": user_a},
            ).scalar_one()
            moderator_b = conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'B') RETURNING id"
                ),
                {"user": user_b},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO moderator_group_assignments "
                    "(telegram_chat_id, moderator_id, assignment_role, valid_from) "
                    "VALUES (:chat, :moderator, 'primary', now())"
                ),
                {"chat": chat_pk, "moderator": moderator_a},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderator_group_assignments "
                        "(telegram_chat_id, moderator_id, assignment_role, valid_from) "
                        "VALUES (:chat, :moderator, 'primary', now())"
                    ),
                    {"chat": chat_pk, "moderator": moderator_b},
                )
        finally:
            trans.rollback()


async def test_a_failure_partway_through_a_handover_leaves_the_incumbent_current(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    """A handover to a non-existent moderator violates the FK on the insert half — the whole
    transaction must roll back, leaving the incumbent's `valid_to` untouched (still NULL) and
    zero successor rows created."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderator_a = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Incumbent"
    )
    incumbent_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_a
    )

    nonexistent_moderator_id = 999_999_999_999

    with pytest.raises(IntegrityError):
        await handover(
            actors_session_factory,
            telegram_chat_id=chat_pk,
            moderator_id=nonexistent_moderator_id,
        )

    incumbent_row = await fetch_assignment(assignment_id=incumbent_id)
    assert incumbent_row["valid_to"] is None

    async with actors_session_factory() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderator_group_assignments)
                .where(moderator_group_assignments.c.telegram_chat_id == chat_pk)
            )
        ).scalar_one()
    assert count == 1


def test_a_zero_width_interval_is_refused(actors_sync_engine: Engine) -> None:
    tg_user_id = _rand_id()
    at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk = conn.execute(
                text(
                    "INSERT INTO telegram_chats (chat_id, chat_type) "
                    "VALUES (:chat_id, 'group') RETURNING id"
                ),
                {"chat_id": -_rand_id()},
            ).scalar_one()
            user_pk = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id},
            ).scalar_one()
            moderator_pk = conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'Zero Width') RETURNING id"
                ),
                {"user": user_pk},
            ).scalar_one()

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderator_group_assignments "
                        "(telegram_chat_id, moderator_id, assignment_role, valid_from, valid_to) "
                        "VALUES (:chat, :moderator, 'primary', :at, :at)"
                    ),
                    {"chat": chat_pk, "moderator": moderator_pk, "at": at},
                )
        finally:
            trans.rollback()


async def test_no_closed_interval_is_deleted_or_rewritten_across_three_handovers(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    moderators = [
        await map_moderator(actors_session_factory, tg_user_id=_rand_id(), display_name=name)
        for name in ("A", "B", "C", "D")
    ]

    id_a = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderators[0]
    )
    row_a_before = await fetch_assignment(assignment_id=id_a)
    assert row_a_before["valid_to"] is None

    id_b = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderators[1]
    )
    row_a_after_first = await fetch_assignment(assignment_id=id_a)
    valid_to_a_after_first = row_a_after_first["valid_to"]
    assert valid_to_a_after_first is not None
    assert row_a_after_first["valid_from"] == row_a_before["valid_from"]

    id_c = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderators[2]
    )
    row_a_after_second = await fetch_assignment(assignment_id=id_a)
    row_b_after_second = await fetch_assignment(assignment_id=id_b)
    # A's closed interval is untouched by a handover two steps later.
    assert row_a_after_second["valid_to"] == valid_to_a_after_first
    assert row_a_after_second["valid_from"] == row_a_before["valid_from"]
    assert row_b_after_second["valid_to"] is not None

    id_d = await handover(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderators[3]
    )

    async with actors_session_factory() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderator_group_assignments)
                .where(moderator_group_assignments.c.telegram_chat_id == chat_pk)
            )
        ).scalar_one()
    # One row per handover — nothing deleted, nothing merged.
    assert count == 4
    assert {id_a, id_b, id_c, id_d} == {
        row["id"]
        for row in [
            await fetch_assignment(assignment_id=i) for i in (id_a, id_b, id_c, id_d)
        ]
    }
