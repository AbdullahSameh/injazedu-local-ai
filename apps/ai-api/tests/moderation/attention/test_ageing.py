"""T059-T060 (US5): the ageing sweep (`contracts/attention-rules.md` §6 G2-G4, D-TG-87) — an
item past the ceiling becomes `expired` with the moment recorded; one short of it is untouched;
a second run changes nothing; a `dismissed` and an `answered` item are never expired. An expired
item is counted unanswered, contributes no response time, is excluded from the open queue, and
is never reopened by a much later moderator message (G3, G4).

`opened_at < now() - max_age_s` is a real database `now()` (G2, D-TG-87) — not the package's
`attention_clock` fixture, which exists for the burst/matching layer's *stored* timestamps, never
for this predicate. So this file opens items with `opened_at` at real wall-clock offsets and uses
a small `max_age_s` to keep the test fast rather than faking the database's own clock. Opening
through `judge_burst` (rather than inserting `attention_items` rows by hand) also stamps the
anchor message's `attention_item_id`, so the direct-reply resolution in the last test is exercised
faithfully, mirroring `test_closure_guard.py`'s pattern.

`expire_stale_items_once` sweeps `injaz_ai_test`'s **whole** `attention_items` table, not just
this file's own rows — every other attention-package test that opens an item via `judge_burst`
and never closes it (most of them `attention_clock`-dated, so a real `opened_at` from months ago)
is a stale `open` item too. Each test here drains that pre-existing backlog first, mirroring
`test_sweep.py`'s own note, so its own counts are deterministic regardless of suite order.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.infrastructure.models_moderation import attention_items
from app.workers.tasks.moderation.expire_stale_items import expire_stale_items_once
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MAX_AGE_S = 5


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _drain_existing_backlog(
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await expire_stale_items_once(attention_session_factory, max_age_s=0)


async def _open_item_at(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    *,
    opened_at: datetime,
) -> tuple[int, int, int]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=opened_at,
        telegram_user_id=student_id,
        original_text="متى الاختبار؟",
    )
    item_id = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=opened_at
    )
    assert item_id is not None
    return chat_pk, student_id, item_id


async def _set_status(
    attention_session_factory: async_sessionmaker[AsyncSession], *, item_id: int, **values: Any
) -> None:
    async with attention_session_factory() as session:
        await session.execute(
            attention_items.update().where(attention_items.c.id == item_id).values(**values)
        )
        await session.commit()


async def _fetch_item(
    attention_session_factory: async_sessionmaker[AsyncSession], *, item_id: int
) -> dict[str, Any]:
    async with attention_session_factory() as session:
        row = (
            await session.execute(sa.select(attention_items).where(attention_items.c.id == item_id))
        ).mappings().one()
        return dict(row)


async def test_an_item_past_the_ceiling_expires_with_the_moment_recorded(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )

    count = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    assert count == 1

    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["status"] == "expired"
    assert row["close_reason"] == "expired"
    assert row["closed_at"] is not None


async def test_an_item_one_short_of_the_ceiling_is_untouched(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S - 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )

    count = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    assert count == 0

    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["status"] == "open"
    assert row["closed_at"] is None


async def test_a_second_run_changes_nothing(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )

    first = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    row_after_first = await _fetch_item(attention_session_factory, item_id=item_id)

    second = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    row_after_second = await _fetch_item(attention_session_factory, item_id=item_id)

    assert first == 1
    assert second == 0
    assert row_after_first == row_after_second


async def test_a_dismissed_item_is_never_expired(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )
    await _set_status(
        attention_session_factory,
        item_id=item_id,
        status="dismissed",
        close_reason="not_a_question",
        closed_at=opened_at + timedelta(seconds=1),
    )

    count = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    assert count == 0

    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["status"] == "dismissed"
    assert row["close_reason"] == "not_a_question"


async def test_an_answered_item_is_never_expired(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    await _drain_existing_backlog(attention_session_factory)
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )
    await _set_status(
        attention_session_factory,
        item_id=item_id,
        status="answered",
        first_response_message_id=2,
        first_response_at=opened_at + timedelta(seconds=1),
        first_response_kind="group_message",
    )

    count = await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    assert count == 0

    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["status"] == "answered"


async def test_an_expired_item_is_counted_unanswered_and_contributes_no_response_time(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
) -> None:
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    _chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )

    async def _unanswered_count() -> int:
        async with attention_session_factory() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(attention_items)
                    .where(
                        attention_items.c.id == item_id,
                        attention_items.c.status.in_(["open", "expired"]),
                    )
                )
            ).scalar_one()

    async def _open_queue_count() -> int:
        async with attention_session_factory() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(attention_items)
                    .where(attention_items.c.id == item_id, attention_items.c.status == "open")
                )
            ).scalar_one()

    assert await _unanswered_count() == 1  # counted as unanswered while open, per G3
    assert await _open_queue_count() == 1  # and in the "still waiting" picture while open

    await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)

    assert await _unanswered_count() == 1  # still counted unanswered after expiry (G3)
    assert await _open_queue_count() == 0  # but no longer pins the oldest-waiting figure

    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["first_response_at"] is None  # contributes no response time


async def test_an_expired_item_is_not_reopened_by_a_much_later_moderator_message(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    judge_burst: Any,
    match_message: Any,
) -> None:
    opened_at = datetime.now(UTC) - timedelta(seconds=_MAX_AGE_S + 1)
    chat_pk, _student_id, item_id = await _open_item_at(
        insert_chat, insert_user, insert_message, judge_burst, opened_at=opened_at
    )
    await expire_stale_items_once(attention_session_factory, max_age_s=_MAX_AGE_S)
    assert (await _fetch_item(attention_session_factory, item_id=item_id))["status"] == "expired"

    moderator = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=datetime.now(UTC),
        telegram_user_id=moderator["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="الأربعاء القادم",
    )
    result = await match_message(telegram_chat_id=chat_pk, message_id=2)

    assert result is None
    row = await _fetch_item(attention_session_factory, item_id=item_id)
    assert row["status"] == "expired"
    assert row["first_response_at"] is None
