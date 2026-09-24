"""What closes an item, and what does not (T032, T033, T041, contract §4).
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from app.application.moderation.assignments import open_assignment
from app.application.moderation.identities import map_moderator
from app.application.moderation.text import normalize
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_direct_reply_to_any_burst_message_closes_the_item_with_kind_direct_reply(
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
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id == item_id

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "answered"
    assert row["first_response_kind"] == "direct_reply"
    assert row["first_response_message_id"] == 2
    assert row["first_response_at"] == reply_at


async def test_a_plain_next_moderator_message_in_the_same_chat_and_thread_closes_with_group_message(
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
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "وين رابط الزوم"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(120)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="https://zoom.example/x",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id == item_id

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "answered"
    assert row["first_response_kind"] == "group_message"
    assert row["first_response_message_id"] == 2


async def test_a_moderator_message_in_a_different_thread_closes_nothing(
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
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        message_thread_id=10,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, message_thread_id=10, around=t1
    )
    assert item_id is not None

    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        message_thread_id=20,
        original_text="رد في ثريد مختلف",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"


async def test_a_moderator_message_in_a_different_chat_closes_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_a = await insert_chat(chat_id=-_rand_id())
    chat_b = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_a,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_a, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_b,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="رد في مجموعة أخرى",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_b, message_id=2)
    assert closed_item_id is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"


async def test_a_message_from_a_non_moderator_closes_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    other_student_id = await insert_user(tg_user_id=_rand_id())

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=other_student_id,
        is_from_moderator=False,
        reply_to_message_id=1,
        original_text="أنا كمان أبغى أعرف",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"


async def test_a_message_from_a_bot_closes_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    """A bot is never `is_from_moderator = true` — `derive_message` refuses to set it for one —
    so this is the same guarantee as the non-moderator case, exercised against a bot sender."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    bot_id = await insert_user(tg_user_id=_rand_id(), is_bot=True)

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=bot_id,
        is_from_moderator=False,
        reply_to_message_id=1,
        original_text="/help",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"


async def test_response_moment_is_the_replys_sent_at_and_the_gap_matches_hand_computation(
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
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator()

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    reply_at = attention_clock.advance(8 * 60)  # the runbook's own 8-minute smoke test
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    await match_message(telegram_chat_id=chat_pk, message_id=2)

    row = await fetch_item(item_id=item_id)
    assert row["first_response_at"] == reply_at
    assert (row["first_response_at"] - row["opened_at"]).total_seconds() == 8 * 60


async def test_first_response_moderator_id_separate_from_responsible_when_colleague_answers(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    fetch_assignment: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    responsible = await insert_moderator(display_name="Responsible")
    colleague = await insert_moderator(display_name="Colleague")

    assignment_id = await open_assignment(
        attention_session_factory,
        telegram_chat_id=chat_pk,
        moderator_id=responsible["moderator_id"],
    )
    # `open_assignment` stamps `valid_from` from the database's own `now()`, not from
    # `attention_clock` (T021's pattern) — the question must fall after it.
    assignment = await fetch_assignment(assignment_id=assignment_id)
    t1 = assignment["valid_from"] + timedelta(seconds=5)
    attention_clock.set(t1)
    question = "متى الاختبار؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert row["responsible_moderator_id"] == responsible["moderator_id"]

    reply_at = attention_clock.advance(60)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=colleague["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    await match_message(telegram_chat_id=chat_pk, message_id=2)

    row = await fetch_item(item_id=item_id)
    assert row["responsible_moderator_id"] == responsible["moderator_id"]
    assert row["first_response_moderator_id"] == colleague["moderator_id"]


async def test_a_message_from_someone_not_a_moderator_at_send_time_closes_nothing_even_if_mapped(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    future_moderator_tg_id = _rand_id()
    future_moderator_user_id = await insert_user(tg_user_id=future_moderator_tg_id)

    question = "متى الاختبار؟"
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)
    assert item_id is not None

    # Sent while this person was not yet a moderator — `is_from_moderator` is stored `False`,
    # exactly as `derive_message` would have resolved it at that instant (TG-M2's write-once
    # rule, FR-029).
    reply_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=future_moderator_user_id,
        is_from_moderator=False,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )

    # Mapped as a moderator only afterwards.
    await map_moderator(
        attention_session_factory,
        tg_user_id=future_moderator_tg_id,
        display_name="Now a moderator",
    )

    closed_item_id = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert closed_item_id is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "open"
