"""A message whose `sent_at` is not strictly after `opened_at` closes nothing, in every storage
order (T037, contract §4 C4).
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_reply_stored_before_the_question_with_sent_at_not_after_opened_at_closes_nothing(
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
    moderator = await insert_moderator()

    t_question = attention_clock.now()
    t_reply = t_question - timedelta(seconds=5)  # not strictly after opened_at

    # Stored before the question — insertion order matches storage order here.
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="لا يوجد أسئلة بعد",
    )
    question = "متى الاختبار؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_question,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"
    assert row["first_response_at"] is None


async def test_a_reply_stored_after_the_question_with_sent_at_not_after_opened_at_closes_nothing(
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
    moderator = await insert_moderator()

    t_question = attention_clock.now()
    t_reply = t_question - timedelta(seconds=5)  # not strictly after opened_at

    # Stored after the question — storage order reversed from the previous test, same instants.
    question = "متى الاختبار؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_question,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="لا يوجد أسئلة بعد",
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"
    assert row["first_response_at"] is None
