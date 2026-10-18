"""The no-links rule at derivation (`docs/plan/telegram/tg-day-one-investigation-and-link-rule-
plan.md` Step 1). A regular member's link opens exactly one incident (`source = 'rule'`) in the
same transaction that stores the message, on the live path only — whatever the model later says.
An edit that adds a link opens one too. Re-derivation and a replayed edit are history: they
record the flags and open nothing.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderation_incidents
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_edited_message_update, make_message_update

_URL = [{"type": "url", "offset": 0, "length": 19}]
_TEXT_LINK = [{"type": "text_link", "offset": 0, "length": 4, "url": "https://example.com"}]


async def _incidents(
    session_factory: async_sessionmaker[AsyncSession], chat_pk: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(moderation_incidents).where(
                    moderation_incidents.c.telegram_chat_id == chat_pk
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def _derive(
    session_factory: async_sessionmaker[AsyncSession],
    insert_captured_update: Any,
    *,
    bot_id: int,
    chat_id: int,
    update: dict[str, Any],
    schedule_classification: bool = True,
) -> int | None:
    from app.application.moderation.messages import derive_message

    row_id = await insert_captured_update(bot_id=bot_id, chat_id=chat_id, update=update)
    return await derive_message(
        session_factory, update_row_id=row_id, schedule_classification=schedule_classification
    )


async def test_a_members_link_opens_one_rule_incident(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1, chat_id=actors_chat_id, text="https://example.com", entities=_URL
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    [incident] = await _incidents(actors_session_factory, chat_pk)
    assert incident["telegram_message_id"] == 1
    assert incident["source"] == "rule"
    assert incident["rule_version"] == 1
    assert incident["category"] == "OTHER"
    assert incident["severity"] == "low"
    assert incident["opened_by_user_id"] is None
    assert incident["message_classification_id"] is None


async def test_a_hidden_text_link_opens_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(1, chat_id=actors_chat_id, text="هنا", entities=_TEXT_LINK)

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_a_link_in_a_media_caption_opens_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1, chat_id=actors_chat_id, text=None, caption="https://example.com", media_kind="photo"
    )
    update["message"]["caption_entities"] = _URL

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_a_members_forwarded_link_opens_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1, chat_id=actors_chat_id, text="https://example.com", entities=_URL
    )
    update["message"]["forward_origin"] = {"type": "hidden_user", "sender_user_name": "X"}

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_a_bots_link_opens_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="https://example.com",
        entities=_URL,
        from_user={"id": 777, "is_bot": True, "first_name": "Bot"},
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_a_declared_moderators_link_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = actors_bot_id  # unique per test, never a sender in another test
    await map_moderator(actors_session_factory, tg_user_id=tg_user_id, display_name="Moderator")
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="https://example.com",
        entities=_URL,
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Mod"},
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert await _incidents(actors_session_factory, chat_pk) == []


async def test_an_anonymous_administrators_link_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="https://example.com",
        entities=_URL,
        from_user={"id": 1087968824, "is_bot": True, "username": "GroupAnonymousBot"},
        sender_chat={"id": actors_chat_id, "type": "supergroup"},
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert await _incidents(actors_session_factory, chat_pk) == []


async def test_the_linked_channels_automatic_forward_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="https://example.com",
        entities=_URL,
        from_user=None,
        sender_chat={"id": -1009876, "type": "channel"},
        is_automatic_forward=True,
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert await _incidents(actors_session_factory, chat_pk) == []


async def test_a_message_without_a_link_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(1, chat_id=actors_chat_id, text="احد يعرف قروب رخصة؟")

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
    )

    assert await _incidents(actors_session_factory, chat_pk) == []


async def test_a_duplicate_delivery_opens_nothing_more(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1, chat_id=actors_chat_id, text="https://example.com", entities=_URL
    )

    for _ in range(2):
        await _derive(
            actors_session_factory,
            insert_captured_update,
            bot_id=actors_bot_id,
            chat_id=actors_chat_id,
            update=dict(update, update_id=update["update_id"] + _),
        )

    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_re_derivation_is_history_and_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        1, chat_id=actors_chat_id, text="https://example.com", entities=_URL
    )

    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=update,
        schedule_classification=False,
    )

    assert await _incidents(actors_session_factory, chat_pk) == []


async def test_an_edit_that_adds_a_link_opens_one_and_the_flag_sticks(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import apply_edit

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=make_message_update(1, chat_id=actors_chat_id, text="سؤال عادي"),
    )
    edit = make_edited_message_update(
        2, chat_id=actors_chat_id, message_id=1, text="https://example.com"
    )
    edit["edited_message"]["entities"] = _URL
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    assert await apply_edit(actors_session_factory, update_row_id=edit_row_id) == 1

    [incident] = await _incidents(actors_session_factory, chat_pk)
    assert (incident["source"], incident["rule_version"]) == ("rule", 1)
    message = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert message is not None
    assert message["entity_flags"]["has_url"] is True

    # A later edit that removes the link keeps the observation: the flag records "ever carried".
    removal = make_edited_message_update(
        3, chat_id=actors_chat_id, message_id=1, text="سؤال عادي"
    )
    removal_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=removal
    )
    await apply_edit(actors_session_factory, update_row_id=removal_row_id)
    message = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert message is not None
    assert message["entity_flags"]["has_url"] is True
    assert len(await _incidents(actors_session_factory, chat_pk)) == 1


async def test_a_replayed_edit_records_the_flag_and_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import apply_edit

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=make_message_update(1, chat_id=actors_chat_id, text="سؤال عادي"),
        schedule_classification=False,
    )
    edit = make_edited_message_update(
        2, chat_id=actors_chat_id, message_id=1, text="https://example.com"
    )
    edit["edited_message"]["entities"] = _URL
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    await apply_edit(actors_session_factory, update_row_id=edit_row_id, open_incidents=False)

    assert await _incidents(actors_session_factory, chat_pk) == []
    message = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert message is not None
    assert message["entity_flags"]["has_url"] is True


async def test_a_moderators_edit_that_adds_a_link_opens_nothing(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    from app.application.moderation.messages import apply_edit

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    tg_user_id = actors_bot_id
    await map_moderator(actors_session_factory, tg_user_id=tg_user_id, display_name="Moderator")
    moderator = {"id": tg_user_id, "is_bot": False, "first_name": "Mod"}
    await _derive(
        actors_session_factory,
        insert_captured_update,
        bot_id=actors_bot_id,
        chat_id=actors_chat_id,
        update=make_message_update(1, chat_id=actors_chat_id, text="اعلان", from_user=moderator),
    )
    edit = make_edited_message_update(
        2, chat_id=actors_chat_id, message_id=1, text="https://example.com", from_user=moderator
    )
    edit["edited_message"]["entities"] = _URL
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    await apply_edit(actors_session_factory, update_row_id=edit_row_id)

    assert await _incidents(actors_session_factory, chat_pk) == []
