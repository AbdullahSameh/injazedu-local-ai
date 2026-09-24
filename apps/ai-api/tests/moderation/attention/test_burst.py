"""Burst formation: the gap, the anchor, and non-absorption across senders (T018, contract §1).
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_three_messages_inside_the_window_open_one_item_dated_from_the_first(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
    attention_burst_gap_s: int,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        original_text="عندي سؤال",
    )
    t2 = attention_clock.advance(10)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text="بخصوص الواجب",
    )
    question = "متى تسليم الواجب؟"
    t3 = attention_clock.advance(10)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t3,
        telegram_user_id=user_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk,
        telegram_user_id=user_id,
        around=t3,
        gap_s=attention_burst_gap_s,
    )
    assert item_id is not None
    item = await fetch_item(item_id=item_id)
    assert item["opened_at"] == t1
    assert item["telegram_message_id"] == 1


async def test_the_same_three_messages_spread_beyond_the_window_open_two_items(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
    attention_burst_gap_s: int,
    count_items: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        original_text="متى تسليم الواجب؟",
        normalized_text=normalize("متى تسليم الواجب؟"),
    )
    t2 = attention_clock.advance(attention_burst_gap_s + 30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text="ازاي احل السؤال التاني؟",
        normalized_text=normalize("ازاي احل السؤال التاني؟"),
    )
    t3 = attention_clock.advance(attention_burst_gap_s + 30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t3,
        telegram_user_id=user_id,
        original_text="ليش الفيديو مش شغال؟",
        normalized_text=normalize("ليش الفيديو مش شغال؟"),
    )

    item_1 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t1)
    item_2 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t2)
    item_3 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t3)

    assert item_1 is not None
    assert item_2 is not None
    assert item_3 is not None
    assert len({item_1, item_2, item_3}) == 3
    assert await count_items(telegram_chat_id=chat_pk) == 3


async def test_two_interleaved_senders_open_two_items_neither_absorbing_the_others_messages(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
    attention_burst_gap_s: int,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_a = await insert_user(tg_user_id=_rand_id())
    student_b = await insert_user(tg_user_id=_rand_id())

    question_a = "متى الاختبار؟"
    question_b = "وين رابط الزوم"

    t_a1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_a1,
        telegram_user_id=student_a,
        original_text=question_a,
        normalized_text=normalize(question_a),
    )
    t_b1 = attention_clock.advance(3)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_b1,
        telegram_user_id=student_b,
        original_text=question_b,
        normalized_text=normalize(question_b),
    )
    t_a2 = attention_clock.advance(3)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t_a2,
        telegram_user_id=student_a,
        original_text="اليوم الجمعة؟",
        normalized_text=normalize("اليوم الجمعة؟"),
    )

    item_a = await judge_burst(
        telegram_chat_id=chat_pk,
        telegram_user_id=student_a,
        around=t_a1,
        gap_s=attention_burst_gap_s,
    )
    item_b = await judge_burst(
        telegram_chat_id=chat_pk,
        telegram_user_id=student_b,
        around=t_b1,
        gap_s=attention_burst_gap_s,
    )

    assert item_a is not None
    assert item_b is not None
    assert item_a != item_b

    row_a = await fetch_item(item_id=item_a)
    row_b = await fetch_item(item_id=item_b)
    assert row_a["opened_at"] == t_a1
    assert row_a["telegram_message_id"] == 1
    assert row_b["opened_at"] == t_b1
    assert row_b["telegram_message_id"] == 2
