"""The six message shapes derived correctly, none discarded (FR-001, FR-004…FR-007, FR-009,
SC-004), plus the NULL-vs-`''` text distinction (FR-009).

Contract assumed here, implemented by T019…T022 (not yet written):

- `app.application.moderation.messages.derive_message(session_factory, *, update_row_id: int)
  -> int | None` — reads the `telegram_updates` row `update_row_id` (kind `message`), resolves
  the sender, resolves the `telegram_chats` surrogate for the update's platform chat id, and
  INSERT-ONLYs one `telegram_messages` row (`ON CONFLICT (telegram_chat_id, message_id) DO
  NOTHING RETURNING id`). Returns the inserted id, or `None` when the row already existed.
- `app.application.moderation.messages.apply_edit(session_factory, *, update_row_id: int) ->
  int` — reads the `telegram_updates` row `update_row_id` (kind `edited_message`) and issues the
  targeted `UPDATE … SET original_text, normalized_text, edited_at`. Returns rows matched (0 or
  1) — see `contracts/message-derivation.md` §2.

Every test operates on a chat inserted with `is_monitored=True` (`insert_chat`'s default): the
measurement gate is US2's concern (T025), not this story's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.moderation.text import normalize
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import (
    make_edited_message_update,
    make_message_update,
    make_service_message_update,
)


async def test_plain_message_derives_with_sender_and_text(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(1, chat_id=actors_chat_id, text="hello")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["telegram_user_id"] is not None
    assert row["sender_chat_id"] is None
    assert row["original_text"] == "hello"
    assert row["normalized_text"] == normalize("hello")
    assert row["is_service"] is False
    assert row["source_update_id"] == row_id


async def test_reply_to_a_message_never_captured_stores_the_target_id(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        2, chat_id=actors_chat_id, text="re: something", reply_to_message_id=999_999
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=2)
    assert row is not None
    assert row["reply_to_message_id"] == 999_999


async def test_anonymous_admin_or_channel_post_has_no_personal_sender(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(
        3,
        chat_id=actors_chat_id,
        text="announcement",
        from_user=None,
        sender_chat={"id": -5001, "type": "channel"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=3)
    assert row is not None
    assert row["telegram_user_id"] is None
    assert row["sender_chat_id"] == -5001
    # ck_telegram_messages_moderator_needs_user (D-TG-60): no personal sender, so never flagged.
    assert row["is_from_moderator"] is False


async def test_service_announcement_is_flagged_and_carries_no_text(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_service_message_update(4, chat_id=actors_chat_id, new_chat_title="New Title")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=4)
    assert row is not None
    assert row["is_service"] is True
    assert row["original_text"] is None
    assert row["normalized_text"] is None


async def test_media_with_no_text_stores_null_text_never_empty_string(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(5, chat_id=actors_chat_id, text=None, media_kind="photo")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    inserted_id = await derive_message(actors_session_factory, update_row_id=row_id)
    assert inserted_id is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=5)
    assert row is not None
    assert row["original_text"] is None
    assert row["normalized_text"] is None
    assert row["media_kind"] == "photo"


async def test_edited_message_updates_the_existing_row(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import apply_edit, derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    original = make_message_update(6, chat_id=actors_chat_id, text="original", date=1_700_000_000)
    original_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=original
    )
    assert await derive_message(actors_session_factory, update_row_id=original_row_id) is not None

    edit = make_edited_message_update(
        7, chat_id=actors_chat_id, message_id=6, text="edited", date=1_700_000_100
    )
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    matched = await apply_edit(actors_session_factory, update_row_id=edit_row_id)
    assert matched == 1

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=6)
    assert row is not None
    assert row["original_text"] == "edited"
    assert row["normalized_text"] == normalize("edited")
    assert row["edited_at"] == datetime.fromtimestamp(1_700_000_100, tz=UTC)


async def test_diacritics_only_text_normalises_to_empty_string_not_null(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    """FR-009: a message may legitimately normalise to `''` (never confused with the "no text
    at all" case, which stores NULL — see `test_media_with_no_text_stores_null_text_never_empty
    _string` above). A run of tashkeel marks alone — no letters, no digits — normalises away to
    nothing under TG-M0's seven-step normaliser (`app/application/moderation/text.py` step 4)."""
    from app.application.moderation.messages import derive_message

    diacritics_only = "ِّ"  # kasra + shadda — TASHKEEL_RE territory, no letters
    assert normalize(diacritics_only) == ""  # sanity-checks the premise this test relies on

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(8, chat_id=actors_chat_id, text=diacritics_only)
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=8)
    assert row is not None
    assert row["original_text"] == diacritics_only
    assert row["normalized_text"] == ""
