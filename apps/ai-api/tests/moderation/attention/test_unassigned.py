"""A chat with no primary owner at `opened_at` still opens the item — NULL is a real answer,
never the current owner (T022, contract §5 A2).
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_chat_with_no_primary_still_opens_the_item_with_null_responsible(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    # Deliberately no moderator_group_assignments row at all for this chat.

    question = "متى الاختبار؟"
    at = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=at,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=at)
    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert row["responsible_moderator_id"] is None
    assert row["status"] == "open"
