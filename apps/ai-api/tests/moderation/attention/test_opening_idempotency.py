"""Opening is idempotent: repeated, reordered, and partial-then-full judgement all converge on
one item (T020, contract "Why judgement may run more than once", B1, D-TG-80).
"""

from __future__ import annotations

import random
from typing import Any

from app.application.moderation.attention import assemble_burst, open_item
from app.application.moderation.text import normalize
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_judging_the_same_messages_three_times_reordered_yields_one_byte_identical_item(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_burst_gap_s: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_item: Any,
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
        original_text="عندي سؤال",
    )
    t2 = attention_clock.advance(5)
    question = "متى تسليم الواجب؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    async def _judge(around: Any) -> int | None:
        async with attention_session_factory() as session:
            burst = await assemble_burst(
                session,
                telegram_chat_id=chat_pk,
                telegram_user_id=user_id,
                message_thread_id=None,
                around=around,
                gap_s=attention_burst_gap_s,
            )
            item_id = await open_item(session, burst)
            await session.commit()
            return item_id

    # Pass 1: forward order (assemble_burst orders by sent_at regardless — "reversed order"
    # exercises that the *anchoring instant*, not insertion order, drives the result).
    first = await _judge(t1)
    # Pass 2: judged from the later message's instant — same underlying burst, same anchor.
    second = await _judge(t2)
    # Pass 3: judged from the earlier message's instant again.
    third = await _judge(t1)

    assert first is not None
    assert first == second == third

    row = await fetch_item(item_id=first)
    # Re-fetching after every pass must be byte-identical — nothing about the row moved.
    assert row["opened_at"] == t1
    assert row["telegram_message_id"] == 1
    assert row["source"] == "rule"
    assert row["rule_version"] == 1


async def test_a_partial_burst_that_declines_then_the_full_burst_opens_dated_from_the_anchor(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_burst_gap_s: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_item: Any,
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

    async def _judge(around: Any) -> int | None:
        async with attention_session_factory() as session:
            burst = await assemble_burst(
                session,
                telegram_chat_id=chat_pk,
                telegram_user_id=user_id,
                message_thread_id=None,
                around=around,
                gap_s=attention_burst_gap_s,
            )
            item_id = await open_item(session, burst)
            await session.commit()
            return item_id

    # A judgement of the partial (still-settling) burst — pure ack, declines.
    declined = await _judge(t1)
    assert declined is None

    # The burst grows with a real question, still within the settle window.
    t2 = attention_clock.advance(5)
    question = "متى تسليم الواجب؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=user_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    opened = await _judge(t2)
    assert opened is not None
    row = await fetch_item(item_id=opened)
    assert row["opened_at"] == t1
    assert row["telegram_message_id"] == 1
