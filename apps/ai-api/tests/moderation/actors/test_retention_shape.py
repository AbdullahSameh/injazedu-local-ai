"""The retention shape (FR-055…FR-058, SC-025).

Only the *shape* exists in this milestone — `telegram_users.identity_purged_at` and
`telegram_messages.text_purged_at`, both already part of revision `0004` (`data-model.md` §1, §2).
No code here ever writes them; the removal job itself belongs to TG-M10. These tests simulate what
a future removal does — an `UPDATE` setting the marker and nulling the removable fields — and
assert every durable field survives, that an identity linked to a moderator is excluded from the
candidate set, and that nothing in this milestone's normal operation touches either marker.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.moderation.assignments import open_assignment
from app.application.moderation.identities import map_moderator, upsert_identity
from app.application.moderation.messages import derive_message
from app.infrastructure.models_moderation import (
    moderators,
    telegram_messages,
    telegram_users,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_removing_a_name_leaves_the_pseudonym_and_every_timestamp_intact(
    actors_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tg_user_id = _rand_id()
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="student1",
            display_name="Student One",
            is_bot=False,
            observed_at=observed_at,
        )
        await session.commit()

    async with actors_session_factory() as session:
        before = (
            await session.execute(
                sa.select(telegram_users).where(telegram_users.c.tg_user_id == tg_user_id)
            )
        ).mappings().one()

        await session.execute(
            telegram_users.update()
            .where(telegram_users.c.tg_user_id == tg_user_id)
            .values(username=None, display_name=None, identity_purged_at=sa.func.now())
        )
        await session.commit()

        after = (
            await session.execute(
                sa.select(telegram_users).where(telegram_users.c.tg_user_id == tg_user_id)
            )
        ).mappings().one()

    assert after["username"] is None
    assert after["display_name"] is None
    assert after["identity_purged_at"] is not None
    # Every durable field is untouched: the pseudonym and every timing survive (FR-055).
    assert after["tg_user_id"] == before["tg_user_id"]
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["last_seen_at"] == before["last_seen_at"]
    assert after["is_bot"] == before["is_bot"]


async def test_removing_a_messages_text_leaves_every_other_field_intact(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    await insert_chat(chat_id=actors_chat_id, is_monitored=True)
    update = make_message_update(1, chat_id=actors_chat_id, text="a question with a url http://x")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )
    message_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert message_id is not None

    async with actors_session_factory() as session:
        before = (
            await session.execute(
                sa.select(telegram_messages).where(telegram_messages.c.id == message_id)
            )
        ).mappings().one()

        await session.execute(
            telegram_messages.update()
            .where(telegram_messages.c.id == message_id)
            .values(original_text=None, normalized_text=None, text_purged_at=sa.func.now())
        )
        await session.commit()

        after = (
            await session.execute(
                sa.select(telegram_messages).where(telegram_messages.c.id == message_id)
            )
        ).mappings().one()

    assert after["original_text"] is None
    assert after["normalized_text"] is None
    assert after["text_purged_at"] is not None
    # Every durable field survives (FR-057): group, sender, send time, reply target, moderator
    # flag, entity flags and every timing.
    assert after["telegram_chat_id"] == before["telegram_chat_id"]
    assert after["telegram_user_id"] == before["telegram_user_id"]
    assert after["sent_at"] == before["sent_at"]
    assert after["edited_at"] == before["edited_at"]
    assert after["reply_to_message_id"] == before["reply_to_message_id"]
    assert after["is_from_moderator"] == before["is_from_moderator"]
    assert after["entity_flags"] == before["entity_flags"]
    assert after["media_kind"] == before["media_kind"]


async def test_an_identity_linked_to_a_moderator_is_excluded_from_name_removal_candidates(
    actors_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    moderator_tg_user_id = _rand_id()
    ordinary_tg_user_id = _rand_id()

    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=moderator_tg_user_id, display_name="Moderator"
    )
    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=ordinary_tg_user_id,
            username="student2",
            display_name="Student Two",
            is_bot=False,
            observed_at=datetime.now(UTC),
        )
        await session.commit()

    # data-model.md §1's exact exclusion: `WHERE NOT EXISTS (SELECT 1 FROM moderators m WHERE
    # m.telegram_user_id = telegram_users.id)`.
    async with actors_session_factory() as session:
        candidate_tg_user_ids = (
            await session.execute(
                sa.select(telegram_users.c.tg_user_id).where(
                    telegram_users.c.tg_user_id.in_(
                        [moderator_tg_user_id, ordinary_tg_user_id]
                    ),
                    ~sa.exists(
                        sa.select(sa.literal(1))
                        .select_from(moderators)
                        .where(moderators.c.telegram_user_id == telegram_users.c.id)
                    ),
                )
            )
        ).scalars().all()

    assert ordinary_tg_user_id in candidate_tg_user_ids
    assert moderator_tg_user_id not in candidate_tg_user_ids

    # Sanity: the moderator mapping really does reach this identity (ON DELETE RESTRICT keeps
    # the join exact) — otherwise the exclusion above would be vacuous.
    async with actors_session_factory() as session:
        linked_tg_user_id = (
            await session.execute(
                sa.select(telegram_users.c.tg_user_id)
                .select_from(moderators.join(
                    telegram_users, moderators.c.telegram_user_id == telegram_users.c.id
                ))
                .where(moderators.c.id == moderator_id)
            )
        ).scalar_one()
    assert linked_tg_user_id == moderator_tg_user_id


async def test_this_milestone_removes_nothing_in_normal_operation(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    """Neither marker is ever written by ordinary derivation or identity resolution — only a
    future, dedicated removal job (TG-M10) writes them (FR-058). Scoped to this test's own rows,
    since `injaz_ai_test` is shared with the other tests in this file that simulate a removal."""
    tg_user_id = _rand_id()
    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=_rand_id(), display_name="Owner"
    )
    await open_assignment(
        actors_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="ordinary traffic",
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Ordinary"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )
    message_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert message_id is not None

    async with actors_session_factory() as session:
        identity_purged_at = (
            await session.execute(
                sa.select(telegram_users.c.identity_purged_at).where(
                    telegram_users.c.tg_user_id == tg_user_id
                )
            )
        ).scalar_one()
        text_purged_at = (
            await session.execute(
                sa.select(telegram_messages.c.text_purged_at).where(
                    telegram_messages.c.id == message_id
                )
            )
        ).scalar_one()

    assert identity_purged_at is None
    assert text_purged_at is None
