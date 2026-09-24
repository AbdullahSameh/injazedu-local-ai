"""The open-time lookback (T036, contract §4.1 C10): a moderator can answer inside the settle
window, before the item exists — no test of "a reply closes an item" reaches this path, since the
reply is stored before the item does.
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_question_then_a_reply_within_the_settle_window_judged_later_has_the_right_gap(
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

    # The reply is stored 20 seconds later — still well inside the settle window — and no
    # `match_response` is ever run for it: at the moment it was captured, no item existed yet for
    # it to resolve against, exactly as live traffic would leave it (C10's premise).
    t_reply = attention_clock.advance(20)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="بعد اسبوعين",
    )

    # Judged at T+90s, once the burst has settled.
    attention_clock.advance(70)
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "answered"
    assert row["first_response_kind"] == "direct_reply"
    assert row["first_response_at"] == t_reply
    assert (row["first_response_at"] - row["opened_at"]).total_seconds() == 20


async def test_a_question_then_a_plain_group_reply_within_the_settle_window_is_answered_on_open(
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

    question = "وين رابط الزوم"
    t_question = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_question,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    t_reply = attention_clock.advance(45)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="https://zoom.example/x",
    )

    attention_clock.advance(45)
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "answered"
    assert row["first_response_kind"] == "group_message"
    assert row["first_response_at"] == t_reply
