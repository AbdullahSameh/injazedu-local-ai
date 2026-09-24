"""Rule (b) closes only the oldest open item; rule (a) can close out of order; when a message
satisfies both, the direct reply wins (T034, T035, contract §4 C1-C3).
"""

from __future__ import annotations

import random
from typing import Any


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_three_open_items_one_plain_moderator_message_closes_only_the_oldest(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    moderator = await insert_moderator()
    students = [await insert_user(tg_user_id=_rand_id()) for _ in range(3)]

    t0 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t0,
        telegram_user_id=students[0],
        original_text="متى الاختبار؟",
    )
    item0 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=students[0], around=t0)

    t1 = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t1,
        telegram_user_id=students[1],
        original_text="وين رابط الزوم",
    )
    item1 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=students[1], around=t1)

    t2 = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t2,
        telegram_user_id=students[2],
        original_text="ليش الفيديو مش شغال؟",
    )
    item2 = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=students[2], around=t2)

    assert item0 is not None and item1 is not None and item2 is not None
    assert len({item0, item1, item2}) == 3

    t_mod = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=4,
        sent_at=t_mod,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="الجميع الرجاء الانتظار",
    )
    closed = await match_message(telegram_chat_id=chat_pk, message_id=4)
    assert closed == item0

    row0 = await fetch_item(item_id=item0)
    row1 = await fetch_item(item_id=item1)
    row2 = await fetch_item(item_id=item2)
    assert row0["status"] == "answered"
    assert row1["status"] == "open"
    assert row2["status"] == "open"

    # A direct reply to the second-oldest closes that one, out of order (C2).
    t_mod2 = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=5,
        sent_at=t_mod2,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=2,
        original_text="بعد نص ساعة",
    )
    closed2 = await match_message(telegram_chat_id=chat_pk, message_id=5)
    assert closed2 == item1

    row1_after = await fetch_item(item_id=item1)
    row2_after = await fetch_item(item_id=item2)
    assert row1_after["status"] == "answered"
    assert row1_after["first_response_kind"] == "direct_reply"
    assert row2_after["status"] == "open"


async def test_a_message_that_is_both_a_direct_reply_and_next_after_an_older_item_the_reply_wins(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    moderator = await insert_moderator()
    student_a = await insert_user(tg_user_id=_rand_id())
    student_b = await insert_user(tg_user_id=_rand_id())

    t0 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t0,
        telegram_user_id=student_a,
        original_text="متى الاختبار؟",
    )
    item_a = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_a, around=t0)

    t1 = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t1,
        telegram_user_id=student_b,
        original_text="وين رابط الزوم",
    )
    item_b = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_b, around=t1)

    assert item_a is not None and item_b is not None and item_a != item_b

    # A single moderator message directly replies to item_b's anchor while also being the plain
    # next message after item_a (the older item) — the direct reply wins (C1): only item_b closes.
    t_mod = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t_mod,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=2,
        original_text="بعد نص ساعة",
    )
    closed = await match_message(telegram_chat_id=chat_pk, message_id=3)
    assert closed == item_b

    row_a = await fetch_item(item_id=item_a)
    row_b = await fetch_item(item_id=item_b)
    assert row_a["status"] == "open"
    assert row_b["status"] == "answered"
    assert row_b["first_response_kind"] == "direct_reply"
