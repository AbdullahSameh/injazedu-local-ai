"""The anchor is `(telegram_chat_id, telegram_message_id)`, not `telegram_message_id` alone
(T015, research Finding 2, D-TG-71).

Telegram numbers messages per chat from 1, so two different chats' own message `#2` must open
**two** rows. Under the source plan's stated `UNIQUE (telegram_message_id)`, this collides: the
second insert is swallowed by `ON CONFLICT … DO NOTHING`, silently landing on the first chat's
item. A single-chat test cannot see this bug — this one is built to see it.
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_two_chats_own_message_2_each_open_their_own_item(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item_by_anchor: Any,
    attention_clock: Any,
) -> None:
    chat_a = -_rand_id()
    chat_b = -_rand_id()
    chat_a_pk = await insert_chat(chat_id=chat_a)
    chat_b_pk = await insert_chat(chat_id=chat_b)
    user_a = await insert_user(tg_user_id=_rand_id())
    user_b = await insert_user(tg_user_id=_rand_id())

    question = "متى تبدأ المحاضرة؟"

    # Each chat's own message #2 — Telegram numbers messages per chat from 1, so both chats
    # legitimately have a row with this same `message_id`, on different senders and chats.
    at_a = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_a_pk,
        message_id=2,
        sent_at=at_a,
        telegram_user_id=user_a,
        original_text=question,
        normalized_text=normalize(question),
    )

    at_b = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_b_pk,
        message_id=2,
        sent_at=at_b,
        telegram_user_id=user_b,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_a = await judge_burst(
        telegram_chat_id=chat_a_pk, telegram_user_id=user_a, around=at_a
    )
    item_b = await judge_burst(
        telegram_chat_id=chat_b_pk, telegram_user_id=user_b, around=at_b
    )

    assert item_a is not None
    assert item_b is not None
    assert item_a != item_b

    row_a = await fetch_item_by_anchor(telegram_chat_id=chat_a_pk, telegram_message_id=2)
    row_b = await fetch_item_by_anchor(telegram_chat_id=chat_b_pk, telegram_message_id=2)
    assert row_a is not None
    assert row_b is not None
    assert row_a["id"] == item_a
    assert row_b["id"] == item_b
