"""US2 — a restart resumes; it does not restart, and it does not lose (FR-006, FR-015…FR-018,
SC-003, SC-004).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from app.application.moderation.ingest import (
    StoredUpdate,
    next_offset,
    record_poll_outcome,
    store_batch,
)
from app.infrastructure.models_moderation import ingestion_state, telegram_updates
from app.providers.telegram.client import parse_update
from app.providers.telegram.models import TelegramUpdate
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


def _updates(*raws: dict) -> list[TelegramUpdate]:
    return [parse_update(raw) for raw in raws]


async def _cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    updates: list[TelegramUpdate],
    allowed_updates: tuple[str, ...] = ("message",),
) -> list[StoredUpdate]:
    """One full poll cycle: store, then record — the order `telegram_main.py`'s loop will use."""
    stored = await store_batch(
        session_factory, bot_id=bot_id, updates=updates, schedule=lambda *_a: None
    )
    await record_poll_outcome(
        session_factory,
        bot_id=bot_id,
        bot_username="injaz_test_bot",
        allowed_updates=list(allowed_updates),
        stored=stored,
    )
    return stored


async def test_after_a_restart_capture_asks_only_for_events_after_the_stored_position(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(make_message_update(1000), make_message_update(1001)),
    )

    # "Restart": a fresh read of the position, no in-memory state carried over.
    offset = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
    assert offset == 1002

    # The redelivered old batch (as Telegram would if the offset weren't honoured) plus one new
    # event: previously stored events are neither redelivered as new nor duplicated.
    stored_again = await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(
            make_message_update(1000), make_message_update(1001), make_message_update(1002)
        ),
    )
    assert {u.update_id for u in stored_again} == {1002}


async def test_the_subscription_set_is_re_asserted_on_restart(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(make_message_update(1100)),
        allowed_updates=("message",),
    )
    # A later restart widens the subscription set — chat_member/message_reaction need admin
    # rights *and* explicit allowed_updates; they are never delivered by default.
    await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(make_message_update(1101)),
        allowed_updates=("message", "chat_member", "message_reaction"),
    )

    async with ingest_session_factory() as session:
        row = (
            await session.execute(
                sa.select(ingestion_state.c.allowed_updates).where(
                    ingestion_state.c.bot_id == ingest_bot_id
                )
            )
        ).one()

    assert set(row.allowed_updates) == {"message", "chat_member", "message_reaction"}


async def test_a_third_poll_that_fails_to_store_advances_the_position_only_to_the_second(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(make_message_update(1200)),
    )
    await _cycle(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        updates=_updates(make_message_update(1201)),
    )

    # A malformed kind violates `ck_telegram_updates_type` — the whole statement rolls back
    # atomically (one statement, no read-then-write window to partially fail within).
    bad_update = parse_update(make_message_update(1202))
    bad_update.kind = "not-a-real-kind"

    with pytest.raises(IntegrityError):
        await store_batch(
            ingest_session_factory,
            bot_id=ingest_bot_id,
            updates=[bad_update],
            schedule=lambda *_a: None,
        )

    offset = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
    assert offset == 1201 + 1  # only the first two polls ever committed


async def test_the_store_being_unavailable_leaves_the_position_unmoved_and_retries_once(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    updates = _updates(make_message_update(1400), make_message_update(1401))

    def _unavailable_session_factory() -> AsyncSession:
        raise ConnectionError("store unavailable (simulated)")

    with pytest.raises(ConnectionError):
        await store_batch(
            _unavailable_session_factory,
            bot_id=ingest_bot_id,
            updates=updates,
            schedule=lambda *_a: None,
        )

    offset = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
    assert offset is None  # nothing was ever recorded; the position never moved

    # Retry once the store is back: the redelivered batch stores exactly once.
    stored = await _cycle(ingest_session_factory, bot_id=ingest_bot_id, updates=updates)
    assert {u.update_id for u in stored} == {1400, 1401}

    stored_again = await _cycle(ingest_session_factory, bot_id=ingest_bot_id, updates=updates)
    assert stored_again == []


async def test_across_every_partial_failure_interleaving_the_position_never_runs_ahead(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    good = [parse_update(make_message_update(uid)) for uid in range(1500, 1510)]
    bad = parse_update(make_message_update(1510))
    bad.kind = "not-a-real-kind"

    # Every interleaving this milestone must handle identically: solo successes, a multi-row
    # success, and a failure both alone and right after a success.
    plan = [
        [good[0]],
        [good[1], good[2]],
        [bad],
        [good[3]],
        [bad],
        [good[4], good[5]],
    ]

    for batch in plan:
        offset_before = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
        try:
            stored = await store_batch(
                ingest_session_factory,
                bot_id=ingest_bot_id,
                updates=batch,
                schedule=lambda *_a: None,
            )
        except IntegrityError:
            offset_after = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
            assert offset_after == offset_before  # a failed store never moves the position
            continue

        await record_poll_outcome(
            ingest_session_factory,
            bot_id=ingest_bot_id,
            bot_username=None,
            allowed_updates=["message"],
            stored=stored,
        )

        async with ingest_session_factory() as session:
            actual_max = (
                await session.execute(
                    sa.select(sa.func.max(telegram_updates.c.update_id)).where(
                        telegram_updates.c.bot_id == ingest_bot_id
                    )
                )
            ).scalar_one()

        offset_after = await next_offset(ingest_session_factory, bot_id=ingest_bot_id)
        assert offset_after is not None
        assert offset_after - 1 == actual_max  # at, never ahead of, what is stored
