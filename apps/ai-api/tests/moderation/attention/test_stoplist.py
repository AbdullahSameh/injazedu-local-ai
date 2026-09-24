"""The acknowledgement stoplist beats every other signal, including reply-to-moderator (T017,
contract §2.2 condition 3, R1, C-R1).
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.text import normalize


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_burst_of_pure_thanks_opens_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())

    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=user_id,
        original_text="شكرا",
    )
    t2 = attention_clock.advance(5)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text="جزاك الله خير",
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=t2)
    assert item_id is None


async def test_direct_reply_to_moderator_saying_ok_opens_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> None:
    """The stoplist must beat the reply-to-moderator signal, or every thanks in every group
    would open an item (C-R1)."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    moderator_user_id = await insert_user(tg_user_id=_rand_id())
    student_user_id = await insert_user(tg_user_id=_rand_id())

    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=attention_clock.now(),
        telegram_user_id=moderator_user_id,
        is_from_moderator=True,
        original_text="تم الحل",
    )
    reply_at = attention_clock.advance(5)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=student_user_id,
        reply_to_message_id=1,
        original_text="تمام",
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_user_id, around=reply_at
    )
    assert item_id is None


async def test_bare_emoji_and_short_messages_open_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())

    cases = ["👍", "👍👍👍👍", "لا"]
    for index, text in enumerate(cases):
        user_id = await insert_user(tg_user_id=_rand_id())
        at = attention_clock.advance(60)
        await insert_message(
            telegram_chat_id=chat_pk,
            message_id=100 + index,
            sent_at=at,
            telegram_user_id=user_id,
            original_text=text,
            normalized_text=normalize(text),
        )
        item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=at)
        assert item_id is None, f"{text!r} unexpectedly opened an item"


async def test_captionless_photo_opens_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    user_id = await insert_user(tg_user_id=_rand_id())
    at = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=at,
        telegram_user_id=user_id,
        original_text=None,
        normalized_text=None,
        media_kind="photo",
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=user_id, around=at)
    assert item_id is None
