"""US6 — edits (`contracts/attention-rules.md` §3 E1-E5, D-TG-88, FR-022…FR-024, SC-024).

Mechanically, an edit is `apply_edit` clearing `attention_evaluated_at` on the edited message
(T079, exercised in `tests/moderation/actors/test_edits.py`) — the ordinary sweep does the rest.
This file exercises that "rest": `open_item`'s judgement of a burst that contains an edited,
now-unevaluated member, built directly the way this package's fixtures always do (T004), rather
than through `apply_edit` itself.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_an_edit_that_adds_a_question_opens_an_item_dated_from_the_edit(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_chat_id: int,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    sent_at = attention_clock.now()
    edited_at = attention_clock.advance(30)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=sent_at,
        # The stored text is already the *current* (post-edit) text — TG-M2's write-once column
        # holds no other version (E1) — with `edited_at` set, mirroring what `apply_edit` leaves
        # behind after clearing `attention_evaluated_at` (T079).
        original_text="when is the deadline?",
        edited_at=edited_at,
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=sent_at
    )

    assert item_id is not None
    item = await fetch_item(item_id=item_id)
    assert item["telegram_message_id"] == 1  # Telegram's own id of the (only) edited message
    assert item["opened_at"] == edited_at
    assert item["opened_at"] != sent_at


async def test_never_edited_burst_still_anchors_on_the_earliest_member(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_chat_id: int,
    attention_clock: Any,
) -> None:
    """Control: with no `edited_at` anywhere in the burst, B2's ordinary rule still applies —
    confirms the edit-anchor branch in `open_item` is additive, not a replacement."""
    chat_pk = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    sent_at = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=sent_at,
        original_text="when is the deadline?",
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=sent_at
    )

    assert item_id is not None
    item = await fetch_item(item_id=item_id)
    assert item["opened_at"] == sent_at


async def test_a_multi_message_burst_anchors_on_the_edited_member_not_the_earliest(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    attention_chat_id: int,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    first_sent_at = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=first_sent_at,
        original_text="hi",
    )

    second_sent_at = attention_clock.advance(3)
    edited_at = attention_clock.advance(20)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        telegram_user_id=student_id,
        sent_at=second_sent_at,
        original_text="when is the deadline?",
        edited_at=edited_at,
    )

    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=first_sent_at
    )

    assert item_id is not None
    item = await fetch_item(item_id=item_id)
    assert item["telegram_message_id"] == 2  # the edited member, not message 1
    assert item["opened_at"] == edited_at


@pytest.mark.parametrize("status", ["open", "answered", "dismissed", "expired"])
async def test_an_edit_to_a_burst_that_already_has_an_item_never_opens_or_alters_one(
    status: str,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    count_items: Any,
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_chat_id: int,
    attention_clock: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    sent_at = attention_clock.now()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=sent_at,
        original_text="when is the deadline?",
    )
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=sent_at
    )
    assert item_id is not None

    if status != "open":
        values: dict[str, Any] = {"status": status}
        if status == "answered":
            values.update(
                first_response_at=sent_at + timedelta(minutes=1),
                first_response_message_id=999,
                first_response_kind="group_message",
            )
        elif status in ("dismissed", "expired"):
            values.update(closed_at=sa.func.now(), close_reason=status)
        async with attention_session_factory() as session:
            await session.execute(
                attention_items.update().where(attention_items.c.id == item_id).values(**values)
            )
            await session.commit()

    before = await fetch_item(item_id=item_id)
    assert before["status"] == status

    # E5, mechanically: the edit clears `attention_evaluated_at` on the (only) burst member —
    # nothing else. The pre-edit text is never consulted (E1): only the current, already-
    # qualifying text and the presence of `edited_at` matter, neither of which changes here.
    edited_at = attention_clock.advance(120)
    async with attention_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE telegram_messages SET edited_at = :edited_at, "
                "attention_evaluated_at = NULL "
                "WHERE telegram_chat_id = :chat_pk AND message_id = 1"
            ),
            {"edited_at": edited_at, "chat_pk": chat_pk},
        )
        await session.commit()

    re_item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=sent_at
    )

    assert re_item_id == item_id  # E2: no item exists *elsewhere*, so this one is it — E4: as-is
    after = await fetch_item(item_id=item_id)
    assert after["status"] == status
    assert after["opened_at"] == before["opened_at"]
    assert await count_items(telegram_chat_id=chat_pk) == 1
