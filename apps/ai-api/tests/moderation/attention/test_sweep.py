"""T061 (US5): the sweep — messages older than the settle window with
`attention_evaluated_at IS NULL` are judged **without any delayed message ever being
delivered** (`contracts/attention-rules.md` §1 B4, research Finding 3); running it twice changes
nothing; a message the sweep judged and declined is marked evaluated and never revisited.

Every message here is planted directly via `insert_message` — no `derive_message`, so
`evaluate_attention`'s delayed dramatiq message is never scheduled at all, proving the sweep is
the authoritative path rather than a fallback that merely tolerates a missing one. `sent_at` is a
real wall-clock offset, mirroring `test_ageing.py`: the sweep's cutoff (`sent_at < now() -
gap_s`) is the database's own clock, not `attention_clock`.

`sweep_unjudged_bursts_once`/`_all` claim `injaz_ai_test`'s **whole** unjudged backlog, not just
this file's own rows — every other attention-package test's stray, never-evaluated message
(most of them `attention_clock`-dated, so real `sent_at < now()` for years) is a candidate too.
Each test here drains that pre-existing backlog first, mirroring `test_drain.py`'s own note about
the shared database, so its own counts are deterministic regardless of suite order.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.workers.tasks.moderation.sweep_unjudged_bursts import (
    sweep_unjudged_bursts_all,
    sweep_unjudged_bursts_once,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_GAP_S = 2


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _drain_existing_backlog(
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sweep_unjudged_bursts_all(attention_session_factory, gap_s=0)


async def test_a_settled_unjudged_question_is_opened_by_the_sweep_alone(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_item_by_anchor: Any,
    count_items: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    sent_at = datetime.now(UTC) - timedelta(seconds=_GAP_S + 1)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )

    handled = await sweep_unjudged_bursts_once(attention_session_factory, gap_s=_GAP_S)

    assert handled == 1
    assert await count_items(telegram_chat_id=chat_pk) == 1
    item = await fetch_item_by_anchor(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert item is not None
    assert item["opened_at"] == sent_at
    assert item["source"] == "rule"


async def test_running_the_sweep_twice_changes_nothing(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_item_by_anchor: Any,
    count_items: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    sent_at = datetime.now(UTC) - timedelta(seconds=_GAP_S + 1)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )

    first = await sweep_unjudged_bursts_all(attention_session_factory, gap_s=_GAP_S)
    item_after_first = await fetch_item_by_anchor(telegram_chat_id=chat_pk, telegram_message_id=1)

    second = await sweep_unjudged_bursts_all(attention_session_factory, gap_s=_GAP_S)
    item_after_second = await fetch_item_by_anchor(telegram_chat_id=chat_pk, telegram_message_id=1)

    assert first == 1
    assert second == 0
    assert await count_items(telegram_chat_id=chat_pk) == 1
    assert item_after_first == item_after_second


async def test_a_declined_message_is_marked_evaluated_and_never_revisited(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_message: Any,
    count_items: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    sent_at = datetime.now(UTC) - timedelta(seconds=_GAP_S + 1)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=student_id,
        original_text="شكرا",
    )

    first = await sweep_unjudged_bursts_once(attention_session_factory, gap_s=_GAP_S)
    assert first == 1
    assert await count_items(telegram_chat_id=chat_pk) == 0
    message = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert message is not None
    assert message["attention_evaluated_at"] is not None
    assert message["attention_item_id"] is None

    second = await sweep_unjudged_bursts_once(attention_session_factory, gap_s=_GAP_S)
    assert second == 0  # never revisited — no longer in the unjudged work list
