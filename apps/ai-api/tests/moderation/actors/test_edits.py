"""An edit touches exactly three columns and nothing else (FR-010, SC-005).

Contract assumed here (T019…T022, not yet written): `app.application.moderation.messages
.apply_edit(session_factory, *, update_row_id: int) -> int` is a targeted `UPDATE … SET
original_text, normalized_text, edited_at WHERE (telegram_chat_id, message_id)` and nothing
else — `contracts/message-derivation.md` §2(b). An edit for a message never derived matches zero
rows and is a no-op, not an error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.moderation.text import normalize
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_edited_message_update, make_message_update


async def test_edit_changes_only_text_normalized_text_and_edited_at(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import apply_edit, derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    original = make_message_update(
        1, chat_id=actors_chat_id, text="before edit", date=1_700_000_000
    )
    original_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=original
    )
    assert await derive_message(actors_session_factory, update_row_id=original_row_id) is not None

    before = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert before is not None

    edit = make_edited_message_update(
        2, chat_id=actors_chat_id, message_id=1, text="after edit", date=1_700_000_500
    )
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    matched = await apply_edit(actors_session_factory, update_row_id=edit_row_id)
    assert matched == 1

    after = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert after is not None

    # Changed:
    assert after["original_text"] == "after edit"
    assert after["normalized_text"] == normalize("after edit")
    assert after["edited_at"] == datetime.fromtimestamp(1_700_000_500, tz=UTC)

    # Unchanged — everything else, byte-identical to before the edit:
    assert after["sent_at"] == before["sent_at"]
    assert after["is_from_moderator"] == before["is_from_moderator"]
    assert after["telegram_user_id"] == before["telegram_user_id"]
    assert after["source_update_id"] == before["source_update_id"]
    assert after["sender_chat_id"] == before["sender_chat_id"]
    assert after["reply_to_message_id"] == before["reply_to_message_id"]
    assert after["is_service"] == before["is_service"]
    assert after["media_kind"] == before["media_kind"]
    assert after["id"] == before["id"]


async def test_edit_for_a_message_never_derived_is_a_no_op_not_an_error(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import apply_edit

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    edit = make_edited_message_update(
        1, chat_id=actors_chat_id, message_id=999, text="orphan edit"
    )
    edit_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=edit
    )

    matched = await apply_edit(actors_session_factory, update_row_id=edit_row_id)
    assert matched == 0

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=999)
    assert row is None
