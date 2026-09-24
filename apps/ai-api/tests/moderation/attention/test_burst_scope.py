"""Burst scope: threads, `sender_chat`, service announcements, and unmeasured chats (T019, T023,
contract §1, §2.2 condition 1-2).
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_different_thread_starts_a_new_burst(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())
    question = "متى الاختبار؟"

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        message_thread_id=100,
        original_text=question,
        normalized_text=normalize(question),
    )
    t2 = attention_clock.advance(5)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        message_thread_id=200,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_1 = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=user_id, message_thread_id=100, around=t1
    )
    item_2 = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=user_id, message_thread_id=200, around=t2
    )

    assert item_1 is not None
    assert item_2 is not None
    assert item_1 != item_2
    row_1 = await fetch_item(item_id=item_1)
    row_2 = await fetch_item(item_id=item_2)
    assert row_1["telegram_message_id"] == 1
    assert row_2["telegram_message_id"] == 2


async def test_null_thread_matches_only_null_never_a_numbered_thread(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())
    question = "متى الاختبار؟"

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        message_thread_id=None,
        original_text=question,
        normalized_text=normalize(question),
    )
    t2 = attention_clock.advance(5)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        message_thread_id=100,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_null = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=user_id, message_thread_id=None, around=t1
    )
    assert item_null is not None
    row_null = await fetch_item(item_id=item_null)
    # Only message #1 (no thread) is in the burst — message #2 (thread 100) never joined it.
    assert row_null["telegram_message_id"] == 1


async def test_a_sender_chat_message_forms_no_burst(
    insert_chat: Any,
    insert_message: Any,
    attention_clock: Any,
) -> None:
    """A message posted by a `sender_chat` (a channel, not a person) has no `telegram_user_id`
    and so cannot be looked up as a burst's sender at all — this milestone's judgement is only
    ever scheduled/invoked with a real sender (`app.application.moderation.messages`)."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    row_id = await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=attention_clock.now(),
        telegram_user_id=None,
        sender_chat_id=-5001,
        original_text="إعلان من القناة",
    )
    assert row_id is not None  # stored — just never forms a burst (no telegram_user_id to key on)


async def test_a_service_announcement_in_the_burst_suppresses_the_item(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())
    question = "متى الاختبار؟"

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        is_service=True,
        original_text=None,
        normalized_text=None,
    )
    t2 = attention_clock.advance(5)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t2)
    assert item_id is None


async def test_a_burst_in_an_unmeasured_chat_opens_nothing_but_is_still_marked_evaluated(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_message: Any,
    attention_clock: Any,
) -> None:
    """T023: the sweep's authoritative work list is `attention_evaluated_at IS NULL`
    (D-TG-72) — a message in an unmeasured chat must still be stamped, or it is revisited
    forever."""
    chat_pk = await insert_chat(chat_id=-_rand_id(), is_monitored=False)
    user_id = await insert_user(tg_user_id=_rand_id())
    question = "متى الاختبار؟"

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t1)
    assert item_id is None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    assert row["attention_evaluated_at"] is not None
    assert row["attention_item_id"] is None
