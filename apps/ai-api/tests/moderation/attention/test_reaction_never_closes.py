"""A reaction never closes an item (T038, contract §4 C5) — the milestone's most tempting wrong
implementation. `message_reaction` updates are captured but never derived into `telegram_messages`
(`app/workers/tasks/moderation/process_update.py`), so there is no row for any matcher to see;
this test proves the whole pipeline leaves the item untouched end to end.
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize
from app.infrastructure.models_moderation import telegram_updates
from app.workers.tasks.moderation.process_update import process_update_row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_message_reaction_from_a_mapped_moderator_leaves_the_item_open_and_changes_nothing(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_bot_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "متى الاختبار؟"
    t_question = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_question,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None
    before = await fetch_item(item_id=item_id)

    async with attention_session_factory() as session:
        update_row_id = (
            await session.execute(
                telegram_updates.insert()
                .values(
                    bot_id=attention_bot_id,
                    update_id=_rand_id(),
                    update_type="message_reaction",
                    chat_id=chat_id,
                    payload={
                        "message_reaction": {
                            "chat": {"id": chat_id},
                            "message_id": 1,
                            "user": {"id": moderator["telegram_user_id"]},
                            "new_reaction": [{"type": "emoji", "emoji": "✅"}],
                        }
                    },
                )
                .returning(telegram_updates.c.id)
            )
        ).scalar_one()
        await session.commit()

    await process_update_row(attention_session_factory, update_row_id)

    after = await fetch_item(item_id=item_id)
    assert after == before
    assert after["status"] == "open"
    assert after["first_response_at"] is None
