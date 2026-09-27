"""T022 — research **Finding 1**: the platform puts a fake `from` on every message sent on
behalf of a chat, a shape TG-M2's own test never sent (`from_user=None` there). With the real
payload — both a fake `from` **and** `sender_chat` — the unfixed `derive_message` stores both
`telegram_user_id` and `sender_chat_id`, and `ck_telegram_messages_sender` rejects the row.

Fix (D-TG-99, operator item 2, approved): when `sender_chat` is present, `from` is ignored
entirely — no identity upsert, `telegram_user_id` stays NULL.
"""

from __future__ import annotations

from typing import Any

from app.application.moderation import messages as messages_module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update

# The Bot API's compatibility placeholder for a message sent on behalf of a chat — the platform's
# own fake `from`, present on every such message (research Finding 1's reference quote).
_FAKE_FROM = {
    "id": 1087968824,
    "is_bot": True,
    "first_name": "Group",
    "username": "GroupAnonymousBot",
}


async def test_a_real_channel_post_carries_both_a_fake_from_and_sender_chat(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    monkeypatch: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    sent = []
    monkeypatch.setattr(
        messages_module.evaluate_attention,
        "send_with_options",
        lambda *a, **kw: sent.append((a, kw)),
    )

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="channel announcement",
        from_user=_FAKE_FROM,
        sender_chat={"id": -5001, "type": "channel"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["telegram_user_id"] is None
    assert row["sender_chat_id"] == -5001
    assert row["is_from_moderator"] is False

    async with actors_session_factory() as session:
        from app.infrastructure.models_moderation import telegram_users

        placeholder = (
            await session.execute(
                select(telegram_users).where(telegram_users.c.tg_user_id == _FAKE_FROM["id"])
            )
        ).mappings().one_or_none()
    assert placeholder is None

    assert sent == []


async def test_an_ordinary_message_with_a_real_sender_is_unchanged(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(2, chat_id=actors_chat_id, text="hello")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=2)
    assert row is not None
    assert row["telegram_user_id"] is not None
    assert row["sender_chat_id"] is None
