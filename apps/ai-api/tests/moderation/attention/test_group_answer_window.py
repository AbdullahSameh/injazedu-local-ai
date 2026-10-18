"""Rule (b) narrowed (`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 2,
operator decisions 2026-10-18). A moderator's message that is not a Telegram reply answers the
oldest open item only when it is sent within `MODERATION_GROUP_ANSWER_WINDOW_S` (30 minutes) of
that item's last burst message, and is neither a forward nor media-only. On day one, 5 of 8
"answered" items were closed hours later by promo posts, a closing announcement and a sticker.
A direct reply (rule (a)) is unchanged.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
from app.application.moderation.text import normalize
from app.domain.moderation.attention import may_answer_by_group_message

_WINDOW_S = 1800


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


# --- The pure, message-side condition -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "forwarded", "media_kind", "has_text", "expected"),
    [
        ("plain text", False, None, True, True),
        ("photo with a caption", False, "photo", True, True),
        ("forwarded post", True, None, True, False),
        ("forwarded photo with a caption", True, "photo", True, False),
        ("sticker", False, "sticker", False, False),
        ("photo with no caption", False, "photo", False, False),
    ],
)
def test_which_messages_may_answer_by_group_message(
    name: str, forwarded: bool, media_kind: str | None, has_text: bool, expected: bool
) -> None:
    assert (
        may_answer_by_group_message(forwarded=forwarded, media_kind=media_kind, has_text=has_text)
        is expected
    ), name


# --- The live matcher -----------------------------------------------------------------------------


async def _open_question(
    *,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    attention_clock: Any,
) -> tuple[int, int]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
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
    return chat_pk, item_id


async def test_a_moderator_message_within_the_window_answers(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, item_id = await _open_question(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        judge_burst=judge_burst,
        attention_clock=attention_clock,
    )
    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=attention_clock.advance(_WINDOW_S - 60),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="الأربعاء القادم",
    )

    assert await match_message(telegram_chat_id=chat_pk, message_id=2) == item_id
    assert (await fetch_item(item_id=item_id))["first_response_kind"] == "group_message"


async def test_a_late_broadcast_answers_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, item_id = await _open_question(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        judge_burst=judge_burst,
        attention_clock=attention_clock,
    )
    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=attention_clock.advance(_WINDOW_S + 60),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="استأذنكم بإغلاق المجموعة تصبحون على خير",
    )

    assert await match_message(telegram_chat_id=chat_pk, message_id=2) is None
    assert (await fetch_item(item_id=item_id))["status"] == "open"


async def test_a_direct_reply_after_the_window_still_answers(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, item_id = await _open_question(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        judge_burst=judge_burst,
        attention_clock=attention_clock,
    )
    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=attention_clock.advance(4 * 3600),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )

    assert await match_message(telegram_chat_id=chat_pk, message_id=2) == item_id
    assert (await fetch_item(item_id=item_id))["first_response_kind"] == "direct_reply"


@pytest.mark.parametrize(
    ("media_kind", "original_text", "entity_flags"),
    [
        ("sticker", None, None),
        (None, "اختبر مستواك في خمس دقائق", {"forwarded": True}),
    ],
    ids=["sticker", "forwarded post"],
)
async def test_a_sticker_or_a_forward_within_the_window_answers_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
    media_kind: str | None,
    original_text: str | None,
    entity_flags: dict[str, bool] | None,
) -> None:
    chat_pk, item_id = await _open_question(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        judge_burst=judge_burst,
        attention_clock=attention_clock,
    )
    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=attention_clock.advance(60),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        media_kind=media_kind,
        original_text=original_text,
        entity_flags=entity_flags,
    )

    assert await match_message(telegram_chat_id=chat_pk, message_id=2) is None
    assert (await fetch_item(item_id=item_id))["status"] == "open"


async def test_a_late_message_skips_the_stale_item_and_answers_the_recent_one(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
    fetch_item: Any,
    attention_clock: Any,
) -> None:
    chat_pk, stale_item_id = await _open_question(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        judge_burst=judge_burst,
        attention_clock=attention_clock,
    )
    other_student = await insert_user(tg_user_id=_rand_id())
    t2 = attention_clock.advance(2 * 3600)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t2,
        telegram_user_id=other_student,
        original_text="كيف اسجل؟",
    )
    recent_item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=other_student, around=t2
    )
    assert recent_item_id is not None
    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=attention_clock.advance(300),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="من صفحة التسجيل",
    )

    assert await match_message(telegram_chat_id=chat_pk, message_id=3) == recent_item_id
    assert (await fetch_item(item_id=stale_item_id))["status"] == "open"


# --- The open-time lookback (C10) -----------------------------------------------------------------


async def test_the_lookback_skips_an_ineligible_message_and_takes_the_next_eligible_one(
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
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )
    # Both stored before the item opens (a late judgement), so only the lookback can see them.
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t1 + timedelta(seconds=30),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        media_kind="sticker",
        original_text=None,
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=t1 + timedelta(seconds=60),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="الأربعاء القادم",
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)

    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert (row["status"], row["first_response_message_id"]) == ("answered", 3)


async def test_the_lookback_ignores_a_message_after_the_window(
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
    t1 = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=t1,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=t1 + timedelta(seconds=_WINDOW_S + 60),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        original_text="تصبحون على خير",
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=t1)

    assert item_id is not None
    assert (await fetch_item(item_id=item_id))["status"] == "open"
