"""⚠ The moderator snapshot on each message: write-once, and its honest limits (FR-032…FR-034,
SC-011, `contracts/message-derivation.md` §5).

T037: a message written before its sender was a moderator must keep `is_from_moderator = false`
after **all three** of mapping that sender as a moderator, unmapping them, and deactivating them —
testing only the first leaves two open doors.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from app.application.moderation.identities import map_moderator
from app.application.moderation.messages import derive_message
from app.infrastructure.models_moderation import moderators
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_flag_survives_mapping_unmapping_and_deactivation(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = _rand_id()
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Sender"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["is_from_moderator"] is False

    # (1) mapping the sender as a moderator afterwards changes nothing already written.
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Mapped Afterwards"
    )
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["is_from_moderator"] is False

    # (2) ...then unmapping them...
    async with actors_session_factory() as session:
        await session.execute(moderators.delete().where(moderators.c.id == moderator_id))
        await session.commit()
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["is_from_moderator"] is False

    # (3) ...then mapping again and deactivating them.
    moderator_id = await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Mapped Again"
    )
    async with actors_session_factory() as session:
        await session.execute(
            moderators.update().where(moderators.c.id == moderator_id).values(is_active=False)
        )
        await session.commit()
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["is_from_moderator"] is False


async def test_flag_is_true_when_sender_was_already_a_declared_moderator_at_insert(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = _rand_id()
    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Already Mapped"
    )

    update = make_message_update(
        2,
        chat_id=actors_chat_id,
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Sender"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=2)
    assert row is not None
    assert row["is_from_moderator"] is True


async def test_flag_is_false_for_a_bot_sender_even_if_mapped(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    """D-TG-60 / FR-017: `is_bot` rules a sender out, whatever the mapping says."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = _rand_id()
    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Mistakenly Mapped Bot"
    )

    update = make_message_update(
        3,
        chat_id=actors_chat_id,
        from_user={"id": tg_user_id, "is_bot": True, "first_name": "Bot"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=3)
    assert row is not None
    assert row["is_from_moderator"] is False


async def test_flag_is_false_for_a_message_with_no_personal_sender(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        4,
        chat_id=actors_chat_id,
        from_user=None,
        sender_chat={"id": -5001, "type": "channel"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=4)
    assert row is not None
    assert row["telegram_user_id"] is None
    assert row["is_from_moderator"] is False


def test_the_database_refuses_the_flag_without_a_personal_sender(
    actors_sync_engine: Engine,
) -> None:
    """`ck_telegram_messages_moderator_needs_user` — the store enforces D-TG-60 directly, not
    only the application (FR-017)."""
    chat_id = -_rand_id()
    bot_id = _rand_id()
    update_id = _rand_id()

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
            update_pk = conn.execute(
                text(
                    "INSERT INTO telegram_updates (bot_id, update_id, update_type, payload) "
                    "VALUES (:bot_id, :update_id, 'message', '{}'::jsonb) RETURNING id"
                ),
                {"bot_id": bot_id, "update_id": update_id},
            ).scalar_one()

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO telegram_messages "
                        "(telegram_chat_id, message_id, sent_at, source_update_id, "
                        " is_from_moderator) "
                        "VALUES (:chat, 1, now(), :update, true)"
                    ),
                    {"chat": chat_pk, "update": update_pk},
                )
        finally:
            trans.rollback()


async def test_flag_does_not_depend_on_owning_the_chat(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    """FR-034: anyone's answer ends a student's wait — the flag needs no assignment at all."""
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = _rand_id()
    await map_moderator(
        actors_session_factory, tg_user_id=tg_user_id, display_name="Unassigned Moderator"
    )
    # Deliberately no moderator_group_assignments row exists for this chat or moderator.

    update = make_message_update(
        5,
        chat_id=actors_chat_id,
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Sender"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None
    row = await fetch_message(telegram_chat_id=chat_pk, message_id=5)
    assert row is not None
    assert row["is_from_moderator"] is True
