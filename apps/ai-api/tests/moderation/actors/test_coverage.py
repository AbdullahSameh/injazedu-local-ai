"""Coverage loss is visible, not tidied away (FR-054, SC-020, D-TG-65).

A bot demotion (or outright removal) is recorded on `telegram_chats` at capture time, by TG-M1's
`upsert_chats_from_batch` (`data-model.md` §1) — this milestone's contribution is the guarantee
that `is_monitored` is never touched by that write, so the group stays measured and the loss
*shows* rather than being silently switched off, and that already-derived messages and ownership
assignments are untouched by a standing change.
"""

from __future__ import annotations

import random
from typing import Any

import sqlalchemy as sa
from app.application.moderation.assignments import open_assignment
from app.application.moderation.identities import map_moderator
from app.application.moderation.ingest import upsert_chats_from_batch
from app.application.moderation.messages import derive_message
from app.infrastructure.models_moderation import telegram_chats
from app.providers.telegram.client import parse_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update, make_my_chat_member_update


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


async def test_a_bot_demotion_records_standing_and_never_switches_measurement_off(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_chat_id: int,
    insert_chat: Any,
) -> None:
    await insert_chat(chat_id=actors_chat_id, is_monitored=True)
    async with actors_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.chat_id == actors_chat_id)
            .values(bot_status="administrator")
        )
        await session.commit()

    demotion = parse_update(
        make_my_chat_member_update(1, chat_id=actors_chat_id, status="member")
    )
    await upsert_chats_from_batch(actors_session_factory, updates=[demotion])

    row = await _fetch_chat(actors_session_factory, chat_id=actors_chat_id)
    assert row["bot_status"] == "member"
    assert row["is_monitored"] is True  # coverage lost, never switches off (D-TG-65)

    # Surfaced as a coverage problem: distinguishable by the same read the groups screen uses
    # (T061) — measured, and the bot is not an administrator.
    async with actors_session_factory() as session:
        coverage_problem_chat_ids = (
            await session.execute(
                sa.select(telegram_chats.c.chat_id).where(
                    telegram_chats.c.is_monitored.is_(True),
                    telegram_chats.c.bot_status != "administrator",
                )
            )
        ).scalars().all()
    assert actors_chat_id in coverage_problem_chat_ids


async def test_a_bot_removal_leaves_existing_messages_and_assignments_untouched(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)

    message_update = make_message_update(1, chat_id=actors_chat_id, text="before removal")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=message_update
    )
    await derive_message(actors_session_factory, update_row_id=row_id)

    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Owner"
    )
    assignment_id = await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )

    removal = parse_update(make_my_chat_member_update(2, chat_id=actors_chat_id, status="kicked"))
    await upsert_chats_from_batch(actors_session_factory, updates=[removal])

    row = await _fetch_chat(actors_session_factory, chat_id=actors_chat_id)
    assert row["bot_status"] == "kicked"
    assert row["is_monitored"] is True

    message_after = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert message_after is not None
    assert message_after["original_text"] == "before removal"

    assignment_after = await fetch_assignment(assignment_id=assignment_id)
    assert assignment_after["telegram_chat_id"] == chat_pk
    assert assignment_after["valid_to"] is None
