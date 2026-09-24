"""T067-T069 (US6): the exact arithmetic behind every figure on the Live Attention Queue's
figures table (`contracts/attention-metrics.md` §2-§4), read through
`app.application.moderation.metrics` — median, p90 and max against hand computation, p90
suppression below `MODERATION_PERCENTILE_MIN_SAMPLES`, NULL vs 0, the unanswered count's
exclusion of `dismissed`, and the `opened_at`-based half-open period window (never `created_at`).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.application.moderation.metrics import (
    first_response_time_stats,
    unanswered_stats,
)
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _insert_item(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
    opened_at: datetime,
    status: str = "open",
    frt_seconds: float | None = None,
    responsible_moderator_id: int | None = None,
) -> None:
    values: dict[str, Any] = {
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": telegram_message_id,
        "opened_at": opened_at,
        "source": "rule",
        "rule_version": 1,
        "status": status,
        "responsible_moderator_id": responsible_moderator_id,
    }
    if frt_seconds is not None:
        values["first_response_message_id"] = telegram_message_id + 9_000
        values["first_response_at"] = opened_at + timedelta(seconds=frt_seconds)
        values["first_response_kind"] = "group_message"
    await session.execute(attention_items.insert().values(**values))


async def _seed_message_and_item(
    session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    *,
    telegram_chat_id: int,
    message_id: int,
    sent_at: datetime,
    student_id: int,
    status: str = "open",
    frt_seconds: float | None = None,
) -> None:
    await insert_message(
        telegram_chat_id=telegram_chat_id,
        message_id=message_id,
        sent_at=sent_at,
        telegram_user_id=student_id,
    )
    async with session_factory() as session:
        await _insert_item(
            session,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=message_id,
            opened_at=sent_at,
            status=status,
            frt_seconds=frt_seconds,
        )
        await session.commit()


async def test_median_p90_and_max_match_hand_computation(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    period_start = datetime(2026, 3, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    frts = [60.0, 120.0, 180.0, 240.0, 300.0, 360.0, 420.0, 480.0, 540.0, 900.0]
    for index, frt in enumerate(frts, start=1):
        await _seed_message_and_item(
            attention_session_factory,
            insert_chat,
            insert_user,
            insert_message,
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            student_id=student_id,
            status="answered",
            frt_seconds=frt,
        )

    async with attention_session_factory() as session:
        stats = await first_response_time_stats(
            session,
            period_from=period_start,
            period_to=period_start + timedelta(hours=1),
            min_samples=10,
            chat_id=chat_id,
        )

    assert stats["answered"] == 10
    sorted_frts = sorted(frts)
    # percentile_cont interpolation, 1-based rank RN = 1 + p*(N-1).
    expected_median = (sorted_frts[4] + sorted_frts[5]) / 2  # p=0.5, N=10 -> RN=5.5
    expected_p90 = sorted_frts[8] + 0.1 * (sorted_frts[9] - sorted_frts[8])  # p=0.9 -> RN=9.1
    assert stats["median_frt"] == pytest.approx(expected_median)
    assert stats["p90_frt"] == pytest.approx(expected_p90)
    assert stats["p90_suppressed"] is False
    assert stats["max_frt"] == pytest.approx(max(frts))


async def test_open_expired_and_dismissed_items_contribute_no_value_to_frt(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    period_start = datetime(2026, 3, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    for index, status in enumerate(["open", "expired", "dismissed"], start=1):
        await _seed_message_and_item(
            attention_session_factory,
            insert_chat,
            insert_user,
            insert_message,
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            student_id=student_id,
            status=status,
        )

    async with attention_session_factory() as session:
        stats = await first_response_time_stats(
            session,
            period_from=period_start,
            period_to=period_start + timedelta(hours=1),
            min_samples=1,
            chat_id=chat_id,
        )

    # Zero answered items: NULL, not 0 (M8) — not counted, not treated as instant.
    assert stats["answered"] == 0
    assert stats["median_frt"] is None
    assert stats["p90_frt"] is None
    assert stats["max_frt"] is None


async def test_unanswered_counts_open_and_expired_and_excludes_dismissed_from_both_sides(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    period_start = datetime(2026, 3, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    statuses = ["open", "open", "expired", "dismissed", "answered"]
    for index, status in enumerate(statuses, start=1):
        await _seed_message_and_item(
            attention_session_factory,
            insert_chat,
            insert_user,
            insert_message,
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            student_id=student_id,
            status=status,
            frt_seconds=30.0 if status == "answered" else None,
        )

    async with attention_session_factory() as session:
        stats = await unanswered_stats(
            session,
            period_from=period_start,
            period_to=period_start + timedelta(hours=1),
            chat_id=chat_id,
        )

    # unanswered = open(2) + expired(1) = 3; dismissed(1) is out of both numerator and
    # denominator; opened = everything except dismissed = 4.
    assert stats["unanswered"] == 3
    assert stats["expired"] == 1
    assert stats["opened"] == 4
    assert stats["unanswered_share"] == pytest.approx(3 / 4)


async def test_p90_is_suppressed_below_the_sample_floor(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    period_start = datetime(2026, 3, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    # Measured (contract §2 M6): four samples yield an authoritative-looking p90 built from four
    # points — the suppression exists precisely for this shape.
    for index, frt in enumerate([60.0, 120.0, 180.0, 900.0], start=1):
        await _seed_message_and_item(
            attention_session_factory,
            insert_chat,
            insert_user,
            insert_message,
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            student_id=student_id,
            status="answered",
            frt_seconds=frt,
        )

    async with attention_session_factory() as session:
        stats = await first_response_time_stats(
            session,
            period_from=period_start,
            period_to=period_start + timedelta(hours=1),
            min_samples=10,
            chat_id=chat_id,
        )

    assert stats["answered"] == 4
    assert stats["p90_suppressed"] is True
    assert stats["p90_frt"] is None
    # The median and max are still reported — only p90 is suppressed.
    assert stats["median_frt"] is not None


async def test_zero_rows_yield_null_not_zero(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_chat_id: int,
) -> None:
    async with attention_session_factory() as session:
        stats = await first_response_time_stats(
            session,
            period_from=datetime(2026, 1, 1, tzinfo=UTC),
            period_to=datetime(2026, 1, 2, tzinfo=UTC),
            min_samples=10,
            chat_id=attention_chat_id,
        )
        unanswered = await unanswered_stats(
            session,
            period_from=datetime(2026, 1, 1, tzinfo=UTC),
            period_to=datetime(2026, 1, 2, tzinfo=UTC),
            chat_id=attention_chat_id,
        )

    assert stats["answered"] == 0
    assert stats["median_frt"] is None
    assert stats["p90_frt"] is None
    assert stats["max_frt"] is None
    assert unanswered["opened"] == 0
    assert unanswered["unanswered_share"] is None


async def test_period_selection_uses_opened_at_never_created_at(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    # `created_at` is `server_default now()` — whatever "now" the test runs at. `opened_at` is
    # deliberately set years in the past, in a window that does not include "now". If the query
    # used `created_at` this item would appear in a query for "today"; using `opened_at` (M1) it
    # never does, and it does appear in a query for its own, old, window.
    old_opened_at = datetime(2020, 6, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())
    await _seed_message_and_item(
        attention_session_factory,
        insert_chat,
        insert_user,
        insert_message,
        telegram_chat_id=chat_id,
        message_id=1,
        sent_at=old_opened_at,
        student_id=student_id,
        status="open",
    )

    async with attention_session_factory() as session:
        today_window = await unanswered_stats(
            session,
            period_from=datetime.now(UTC) - timedelta(days=1),
            period_to=datetime.now(UTC) + timedelta(days=1),
            chat_id=chat_id,
        )
        old_window = await unanswered_stats(
            session,
            period_from=old_opened_at - timedelta(minutes=1),
            period_to=old_opened_at + timedelta(minutes=1),
            chat_id=chat_id,
        )

    assert today_window["opened"] == 0
    assert old_window["opened"] == 1


async def test_period_boundary_is_inclusive_at_start_exclusive_at_end(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    boundary = datetime(2026, 4, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())

    # One item opened exactly at the boundary (included, since it is the period's start), one
    # opened one second earlier (excluded from a period starting at the boundary).
    await _seed_message_and_item(
        attention_session_factory,
        insert_chat,
        insert_user,
        insert_message,
        telegram_chat_id=chat_id,
        message_id=1,
        sent_at=boundary,
        student_id=student_id,
    )
    await _seed_message_and_item(
        attention_session_factory,
        insert_chat,
        insert_user,
        insert_message,
        telegram_chat_id=chat_id,
        message_id=2,
        sent_at=boundary - timedelta(seconds=1),
        student_id=student_id,
    )

    async with attention_session_factory() as session:
        starting_at_boundary = await unanswered_stats(
            session,
            period_from=boundary,
            period_to=boundary + timedelta(hours=1),
            chat_id=chat_id,
        )
        ending_at_boundary = await unanswered_stats(
            session,
            period_from=boundary - timedelta(hours=1),
            period_to=boundary,
            chat_id=chat_id,
        )

    # Moving the boundary by one second moves exactly the one item on that side of it (M2).
    assert starting_at_boundary["opened"] == 1
    assert ending_at_boundary["opened"] == 1
