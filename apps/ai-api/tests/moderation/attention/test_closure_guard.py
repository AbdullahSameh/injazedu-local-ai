"""The guarded close (T039, contract §4 C8, FR-033, FR-035): a second closer updates zero rows, a
dismissed or expired item is never closed, and re-running the matcher changes nothing.
"""

from __future__ import annotations

import random
from typing import Any

from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _open_item(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> tuple[int, int, int]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    t_question = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t_question,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t_question
    )
    assert item_id is not None
    return chat_pk, student_id, item_id


async def test_a_second_closer_updates_zero_rows_and_leaves_the_first_response_untouched(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, _student_id, item_id = await _open_item(
        insert_chat, insert_user, insert_message, judge_burst, attention_clock
    )
    first_moderator = await insert_moderator(display_name="First")
    second_moderator = await insert_moderator(display_name="Second")

    t_first = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_first,
        telegram_user_id=first_moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    first_result = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert first_result == item_id

    t_second = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t_second,
        telegram_user_id=second_moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="بل الخميس",
    )
    second_result = await match_message(telegram_chat_id=chat_pk, message_id=3)
    assert second_result is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "answered"
    assert row["first_response_message_id"] == 2
    assert row["first_response_at"] == t_first
    assert row["first_response_moderator_id"] == first_moderator["moderator_id"]


async def test_a_dismissed_item_is_never_closed(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, _student_id, item_id = await _open_item(
        insert_chat, insert_user, insert_message, judge_burst, attention_clock
    )
    moderator = await insert_moderator()

    async with attention_session_factory() as session:
        await session.execute(
            attention_items.update()
            .where(attention_items.c.id == item_id)
            .values(
                status="dismissed",
                closed_at=attention_clock.now(),
                close_reason="not_a_question",
            )
        )
        await session.commit()

    t_reply = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    result = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert result is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "dismissed"
    assert row["first_response_at"] is None


async def test_an_expired_item_is_never_closed(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, _student_id, item_id = await _open_item(
        insert_chat, insert_user, insert_message, judge_burst, attention_clock
    )
    moderator = await insert_moderator()

    async with attention_session_factory() as session:
        await session.execute(
            attention_items.update()
            .where(attention_items.c.id == item_id)
            .values(status="expired", closed_at=attention_clock.now(), close_reason="expired")
        )
        await session.commit()

    t_reply = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    result = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert result is None

    row = await fetch_item(item_id=item_id)
    assert row["status"] == "expired"
    assert row["first_response_at"] is None


async def test_rerunning_the_matcher_over_the_same_message_changes_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, _student_id, item_id = await _open_item(
        insert_chat, insert_user, insert_message, judge_burst, attention_clock
    )
    moderator = await insert_moderator()

    t_reply = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t_reply,
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    first = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert first == item_id
    row_after_first = await fetch_item(item_id=item_id)

    second = await match_message(telegram_chat_id=chat_pk, message_id=2)
    assert second is None
    row_after_second = await fetch_item(item_id=item_id)

    assert row_after_first == row_after_second
