"""A group is measured only when someone decides it is (FR-019, FR-024, SC-003).

Contract assumed here, implemented by T031 (not yet written): `messages.derive_message` gates
derivation on the chat's `is_monitored` — an unmeasured chat derives nothing and the captured
event is still marked handled (`contracts/message-derivation.md` §6). Capture is unconditional
and derivation is opt-in, which is what makes catching a group up later (US2's re-derivation
command) possible, and what keeps the bot's mere presence in a group from being mistaken for
consent to measure the people in it.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.models_moderation import telegram_chats, telegram_updates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


async def test_captured_event_for_unmonitored_chat_produces_no_derived_state(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    fetch_user: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=False)
    sender_tg_user_id = 900_000_001
    update = make_message_update(
        1,
        chat_id=actors_chat_id,
        text="unmeasured",
        from_user={"id": sender_tg_user_id, "is_bot": False, "first_name": "Unseen"},
    )
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    await process_update_row(actors_session_factory, row_id)

    assert await fetch_message(telegram_chat_id=chat_pk, message_id=1) is None
    assert await fetch_user(tg_user_id=sender_tg_user_id) is None

    async with actors_session_factory() as session:
        processed_at = (
            await session.execute(
                select(telegram_updates.c.processed_at).where(telegram_updates.c.id == row_id)
            )
        ).scalar_one()
    assert processed_at is not None


async def test_switching_measurement_off_leaves_already_derived_rows_intact(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)

    first_update = make_message_update(1, chat_id=actors_chat_id, text="while measured")
    first_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=first_update
    )
    await process_update_row(actors_session_factory, first_row_id)

    before_switch_off = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert before_switch_off is not None

    async with actors_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.id == chat_pk)
            .values(is_monitored=False)
        )
        await session.commit()

    second_update = make_message_update(2, chat_id=actors_chat_id, text="after switch-off")
    second_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=second_update
    )
    await process_update_row(actors_session_factory, second_row_id)

    assert await fetch_message(telegram_chat_id=chat_pk, message_id=2) is None
    after_switch_off = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert after_switch_off == before_switch_off
