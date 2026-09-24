"""US6 extension — a supergroup promotion never loses or corrupts an item (FR-081, SC-022,
`plan.md`'s "Supergroup migration" row).

TG-M2's `repoint_for_migration` moves `moderator_group_assignments` off the superseded chat row
so ownership survives a promotion (`tests/moderation/actors/test_migration_repoint.py`). Its own
docstring explains why `attention_items` is **not** given the same treatment: `attention_items`
carries `fk_attention_message`, a composite FK on `(telegram_chat_id, telegram_message_id)` into
`telegram_messages`, and Telegram's per-chat message counter restarts at 1 under the new
supergroup id (research Finding 2, D-TG-71) — messages are never re-pointed (`group_history_chat_
ids`'s own docstring), so moving an item's `telegram_chat_id` alone would either violate that FK
outright or silently misattribute the anchor to an unrelated message.

What SC-022 actually requires — "keeps every open item and every closed item's timings" — is that
a migration event never deletes or mutates an existing item. This file proves exactly that: a
promotion changes `is_monitored` and ownership FKs, and touches `attention_items` not at all.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from app.application.moderation.assignments import repoint_for_migration
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _count_items(
    session_factory: async_sessionmaker[AsyncSession], *, telegram_chat_id: int
) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(attention_items)
                .where(attention_items.c.telegram_chat_id == telegram_chat_id)
            )
        ).scalar_one()


async def test_a_promotion_leaves_every_open_and_closed_item_exactly_where_it_was(
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
    old_chat_id = -_rand_id()
    new_chat_id = -_rand_id()
    old_pk = await insert_chat(chat_id=old_chat_id, is_monitored=True)
    await insert_chat(chat_id=new_chat_id, is_monitored=False)

    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator(display_name="Owner")

    # An item that stays open across the promotion.
    open_sent_at = attention_clock.now()
    await insert_message(
        telegram_chat_id=old_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=open_sent_at,
        original_text="when is the deadline?",
    )
    open_item_id = await judge_burst(
        telegram_chat_id=old_pk, telegram_user_id=student_id, around=open_sent_at
    )
    assert open_item_id is not None

    # An item already answered before the promotion — its timings must not move either.
    closed_sent_at = attention_clock.advance(200)
    await insert_message(
        telegram_chat_id=old_pk,
        message_id=2,
        telegram_user_id=student_id,
        sent_at=closed_sent_at,
        original_text="how do I submit?",
    )
    closed_item_id = await judge_burst(
        telegram_chat_id=old_pk, telegram_user_id=student_id, around=closed_sent_at
    )
    assert closed_item_id is not None
    assert closed_item_id != open_item_id

    reply_sent_at = closed_sent_at + timedelta(minutes=5)
    await insert_message(
        telegram_chat_id=old_pk,
        message_id=3,
        telegram_user_id=moderator["telegram_user_id"],
        sent_at=reply_sent_at,
        is_from_moderator=True,
        original_text="submit it on the portal",
        # A direct reply (rule (a), C1) resolves to *this* item regardless of which open item is
        # chronologically oldest — the still-open item from earlier in this test must stay as-is.
        reply_to_message_id=2,
    )
    closed_via_match = await match_message(telegram_chat_id=old_pk, message_id=3)
    assert closed_via_match == closed_item_id

    before_open = await fetch_item(item_id=open_item_id)
    before_closed = await fetch_item(item_id=closed_item_id)
    assert before_closed["status"] == "answered"

    await repoint_for_migration(
        attention_session_factory, old_chat_id=old_chat_id, new_chat_id=new_chat_id
    )

    after_open = await fetch_item(item_id=open_item_id)
    after_closed = await fetch_item(item_id=closed_item_id)

    # Untouched, byte-for-byte: no column of either item moves because of the migration.
    assert after_open == before_open
    assert after_closed == before_closed
    assert after_open["telegram_chat_id"] == old_pk
    assert after_open["status"] == "open"
    assert after_closed["telegram_chat_id"] == old_pk
    assert after_closed["status"] == "answered"
    assert after_closed["first_response_at"] == before_closed["first_response_at"]
    assert (
        after_closed["first_response_moderator_id"]
        == before_closed["first_response_moderator_id"]
    )

    assert await _count_items(attention_session_factory, telegram_chat_id=old_pk) == 2
