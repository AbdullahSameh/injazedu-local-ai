"""Ties are broken by `(sent_at, message_id)`, both from Telegram (T040, contract §4 C9) — so the
answer is the same on every re-derivation, rather than whichever transaction committed first.
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_two_moderator_messages_with_identical_sent_at_pick_the_lower_message_id(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator_a = await insert_moderator(display_name="A")
    moderator_b = await insert_moderator(display_name="B")

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

    # Both stored — before the item exists — with the identical `sent_at`. Stored in descending
    # message_id order, so a naive "first inserted" resolution would pick the wrong one.
    tie_at = attention_clock.advance(20)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=tie_at,
        telegram_user_id=moderator_b["telegram_user_id"],
        is_from_moderator=True,
        original_text="من ب",
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=tie_at,
        telegram_user_id=moderator_a["telegram_user_id"],
        is_from_moderator=True,
        original_text="من ا",
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None

    row = await fetch_item(item_id=item_id)
    assert row["first_response_message_id"] == 2
    assert row["first_response_moderator_id"] == moderator_a["moderator_id"]

    # Re-running the judgement (idempotent) reaches the same answer.
    again = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert again == item_id
    row_again = await fetch_item(item_id=item_id)
    assert row_again == row
