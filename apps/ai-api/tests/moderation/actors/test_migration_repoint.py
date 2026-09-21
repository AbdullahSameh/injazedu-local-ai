"""⚠ The chat-migration re-point (`data-model.md` §4.3, `contracts/moderator-ownership.md` §6,
D-TG-54, research Finding 3).

T063: probe 4 showed TG-M1's `apply_chat_migration_if_any` leaves the surviving chat row at
`is_monitored = false`, so a promoted group silently stops being measured while every health
signal stays green. These tests assert the re-point carries `is_monitored` and `injaz_course_id`
forward, moves ownership assignments with zero intervals closed and zero opened, refuses a
conflicting destination, and that messages either side of the promotion are countable as one
group's history.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.assignments import (
    RepointConflictError,
    open_assignment,
    repoint_for_migration,
)
from app.application.moderation.identities import map_moderator
from app.application.moderation.messages import derive_message, group_history_chat_ids
from app.infrastructure.models_moderation import (
    moderator_group_assignments,
    telegram_chats,
    telegram_messages,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _fetch_chat(
    session_factory: async_sessionmaker[AsyncSession], *, chat_id: int
) -> Any:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(telegram_chats).where(telegram_chats.c.chat_id == chat_id)
            )
        ).mappings().one()


async def test_repoint_moves_assignments_and_carries_measurement_forward_with_no_intervals_touched(
    actors_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    old_chat_id = -_rand_id()
    new_chat_id = -_rand_id()
    await insert_chat(chat_id=old_chat_id, is_monitored=True)
    await insert_chat(chat_id=new_chat_id, is_monitored=False)

    async with actors_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.chat_id == old_chat_id)
            .values(injaz_course_id=77)
        )
        await session.commit()

    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Owner"
    )
    old_pk = (await _fetch_chat(actors_session_factory, chat_id=old_chat_id))["id"]
    assignment_id = await open_assignment(
        actors_session_factory, telegram_chat_id=old_pk, moderator_id=moderator_id
    )
    before = await fetch_assignment(assignment_id=assignment_id)

    await repoint_for_migration(
        actors_session_factory, old_chat_id=old_chat_id, new_chat_id=new_chat_id
    )

    after = await fetch_assignment(assignment_id=assignment_id)
    new_row = await _fetch_chat(actors_session_factory, chat_id=new_chat_id)
    old_row = await _fetch_chat(actors_session_factory, chat_id=old_chat_id)

    assert after["telegram_chat_id"] == new_row["id"]
    # Zero intervals closed, zero opened — a technical migration is not a handover.
    assert after["valid_from"] == before["valid_from"]
    assert after["valid_to"] is None
    assert new_row["is_monitored"] is True
    assert new_row["injaz_course_id"] == 77
    assert old_row["is_monitored"] is False

    new_pk = new_row["id"]
    async with actors_session_factory() as session:
        count_on_new = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderator_group_assignments)
                .where(moderator_group_assignments.c.telegram_chat_id == new_pk)
            )
        ).scalar_one()
        count_on_old = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderator_group_assignments)
                .where(moderator_group_assignments.c.telegram_chat_id == old_pk)
            )
        ).scalar_one()
    assert count_on_new == 1  # the one assignment moved here
    assert count_on_old == 0  # nothing opened, nothing left orphaned on the old row


async def test_repoint_refuses_when_the_surviving_row_already_has_a_current_primary(
    actors_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    fetch_assignment: Any,
) -> None:
    old_chat_id = -_rand_id()
    new_chat_id = -_rand_id()
    await insert_chat(chat_id=old_chat_id, is_monitored=True)
    await insert_chat(chat_id=new_chat_id, is_monitored=False)

    incumbent_moderator = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Old Owner"
    )
    conflicting_moderator = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Already There"
    )

    old_pk = (await _fetch_chat(actors_session_factory, chat_id=old_chat_id))["id"]
    new_pk = (await _fetch_chat(actors_session_factory, chat_id=new_chat_id))["id"]
    old_assignment_id = await open_assignment(
        actors_session_factory, telegram_chat_id=old_pk, moderator_id=incumbent_moderator
    )
    await open_assignment(
        actors_session_factory, telegram_chat_id=new_pk, moderator_id=conflicting_moderator
    )

    with pytest.raises(RepointConflictError):
        await repoint_for_migration(
            actors_session_factory, old_chat_id=old_chat_id, new_chat_id=new_chat_id
        )

    # No partial rows: the old row's assignment is untouched, the new row's is untouched.
    old_row_after = await fetch_assignment(assignment_id=old_assignment_id)
    assert old_row_after["telegram_chat_id"] == old_pk
    old_chat_after = await _fetch_chat(actors_session_factory, chat_id=old_chat_id)
    assert old_chat_after["is_monitored"] is True


async def test_messages_either_side_of_a_promotion_are_one_groups_history_with_no_loss(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    old_chat_id = -_rand_id()
    new_chat_id = -_rand_id()
    await insert_chat(chat_id=old_chat_id, is_monitored=True)
    await insert_chat(chat_id=new_chat_id, is_monitored=False)

    # The link columns are `apply_chat_migration_if_any`'s job (already TG-M1); this test
    # exercises only the re-point and the history read, so it sets them directly.
    async with actors_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.chat_id == old_chat_id)
            .values(migrated_to_chat_id=new_chat_id)
        )
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.chat_id == new_chat_id)
            .values(migrated_from_chat_id=old_chat_id)
        )
        await session.commit()

    pre_update = make_message_update(1, chat_id=old_chat_id, text="before promotion")
    pre_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=old_chat_id, update=pre_update
    )
    await derive_message(actors_session_factory, update_row_id=pre_row_id)

    await repoint_for_migration(
        actors_session_factory, old_chat_id=old_chat_id, new_chat_id=new_chat_id
    )

    post_update = make_message_update(2, chat_id=new_chat_id, message_id=1, text="after promotion")
    post_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=new_chat_id, update=post_update
    )
    await derive_message(actors_session_factory, update_row_id=post_row_id)

    new_pk = (await _fetch_chat(actors_session_factory, chat_id=new_chat_id))["id"]
    async with actors_session_factory() as session:
        history_ids = await group_history_chat_ids(session, telegram_chat_id=new_pk)
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(telegram_messages)
                .where(telegram_messages.c.telegram_chat_id.in_(history_ids))
            )
        ).scalar_one()

    assert len(history_ids) == 2  # the old row and the new row, nothing else
    assert count == 2  # 0 lost, 0 double-counted — both message_id=1 rows are distinct chats
