"""US1 — every event is captured exactly once (FR-008, FR-010, FR-011, FR-012, FR-013,
SC-001, SC-002).

Drives `store_batch` directly against `injaz_ai_test`, with `schedule` replaced by a list
collector — no Redis, no dramatiq broker, no network.
"""

from __future__ import annotations

import sqlalchemy as sa
from app.application.moderation.ingest import store_batch
from app.infrastructure.models_moderation import telegram_updates
from app.providers.telegram.client import parse_update
from app.providers.telegram.models import TelegramUpdate
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


def _updates(*raws: dict) -> list[TelegramUpdate]:
    return [parse_update(raw) for raw in raws]


async def test_a_batch_of_three_stores_three_rows_and_schedules_three_jobs(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raws = [make_message_update(100), make_message_update(101), make_message_update(102)]
    scheduled: list[tuple[int, int]] = []

    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(*raws),
        schedule=lambda row_id, update_id: scheduled.append((row_id, update_id)),
    )

    assert len(stored) == 3
    assert len(scheduled) == 3
    assert {u.update_id for u in stored} == {100, 101, 102}
    assert {update_id for _row_id, update_id in scheduled} == {100, 101, 102}


async def test_the_same_batch_again_stores_nothing_and_schedules_nothing(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raws = [make_message_update(200), make_message_update(201)]
    await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(*raws),
        schedule=lambda *_a: None,
    )

    scheduled: list[tuple[int, int]] = []
    stored_again = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(*raws),
        schedule=lambda row_id, update_id: scheduled.append((row_id, update_id)),
    )

    assert stored_again == []
    assert scheduled == []


async def test_a_shuffled_batch_stores_all_and_leaves_update_id_ordering_recoverable(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raws = [make_message_update(update_id) for update_id in (303, 301, 302)]

    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(*raws),
        schedule=lambda *_a: None,
    )

    assert {u.update_id for u in stored} == {301, 302, 303}

    async with ingest_session_factory() as session:
        rows = (
            (
                await session.execute(
                    sa.select(telegram_updates.c.update_id)
                    .where(telegram_updates.c.bot_id == ingest_bot_id)
                    .order_by(telegram_updates.c.update_id)
                )
            )
            .scalars()
            .all()
        )

    assert list(rows) == [301, 302, 303]


async def test_an_unmodelled_kind_is_stored_as_unknown_and_a_chatless_update_stores_null_chat_id(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    unmodelled_raw = {"update_id": 500, "poll": {"id": "abc123", "question": "?"}}
    chatless_raw = {
        "update_id": 501,
        "callback_query": {"id": "cbq1", "from": {"id": 1, "is_bot": False}, "data": "x"},
    }

    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(unmodelled_raw, chatless_raw),
        schedule=lambda *_a: None,
    )

    assert len(stored) == 2  # neither is discarded

    async with ingest_session_factory() as session:
        rows = (
            await session.execute(
                sa.select(
                    telegram_updates.c.update_id,
                    telegram_updates.c.update_type,
                    telegram_updates.c.chat_id,
                ).where(telegram_updates.c.bot_id == ingest_bot_id)
            )
        ).all()

    by_update_id = {row.update_id: row for row in rows}
    assert by_update_id[500].update_type == "unknown"
    assert by_update_id[501].chat_id is None


async def test_the_platforms_own_timestamp_drives_ordering_and_received_at_is_not_substituted(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    raw = make_message_update(600)
    platform_date = raw["message"]["date"]

    stored = await store_batch(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(raw),
        schedule=lambda *_a: None,
    )

    async with ingest_session_factory() as session:
        row = (
            await session.execute(
                sa.select(telegram_updates.c.payload, telegram_updates.c.received_at).where(
                    telegram_updates.c.id == stored[0].id
                )
            )
        ).one()

    # The platform's own timestamp travels through untouched, in `payload` — ordering and
    # measurement read it from there (or from `update_id`), never from our storage clock.
    assert row.payload["message"]["date"] == platform_date
    # `received_at` is recorded separately and is never substituted with the platform's date.
    assert row.received_at is not None
    assert row.received_at.timestamp() != platform_date
