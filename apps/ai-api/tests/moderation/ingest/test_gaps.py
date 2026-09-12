"""US3 — a window that was not observed is marked as not observed: `downtime` (FR-021, FR-022,
FR-023, FR-025, SC-005, SC-006, SC-007).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from app.application.moderation.ingest import record_downtime_if_any, record_poll_outcome
from app.infrastructure.models_moderation import ingestion_gaps, ingestion_state
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MIN_SILENCE_S = 300  # MODERATION_GAP_MIN_SILENCE_S default


async def _seed_last_success(
    session_factory: async_sessionmaker[AsyncSession], bot_id: int, *, ago_s: float
) -> None:
    """Creates the bot's `ingestion_state` row via a real (empty) poll outcome, then backdates
    `last_success_at` directly — the fastest way to simulate "N seconds of silence" in a test."""
    await record_poll_outcome(
        session_factory, bot_id=bot_id, bot_username=None, allowed_updates=["message"], stored=[]
    )
    backdated = datetime.now(UTC) - timedelta(seconds=ago_s)
    async with session_factory() as session:
        await session.execute(
            ingestion_state.update()
            .where(ingestion_state.c.bot_id == bot_id)
            .values(last_success_at=backdated)
        )
        await session.commit()


async def _gap_rows(session_factory: async_sessionmaker[AsyncSession], bot_id: int) -> list:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(ingestion_gaps)
                .where(ingestion_gaps.c.bot_id == bot_id)
                .order_by(ingestion_gaps.c.id)
            )
        ).all()


async def test_a_stop_longer_than_the_minimum_produces_exactly_one_downtime_row(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_last_success(ingest_session_factory, ingest_bot_id, ago_s=_MIN_SILENCE_S + 60)

    await record_downtime_if_any(
        ingest_session_factory, bot_id=ingest_bot_id, min_silence_s=_MIN_SILENCE_S
    )

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert len(rows) == 1
    assert rows[0].reason == "downtime"


async def test_a_pause_shorter_than_the_minimum_produces_zero_rows(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_last_success(ingest_session_factory, ingest_bot_id, ago_s=_MIN_SILENCE_S - 60)

    await record_downtime_if_any(
        ingest_session_factory, bot_id=ingest_bot_id, min_silence_s=_MIN_SILENCE_S
    )

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert rows == []


async def test_a_window_longer_than_24h_is_marked_unrecoverable(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_last_success(ingest_session_factory, ingest_bot_id, ago_s=25 * 3600)

    await record_downtime_if_any(
        ingest_session_factory, bot_id=ingest_bot_id, min_silence_s=_MIN_SILENCE_S
    )

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert len(rows) == 1
    assert rows[0].unrecoverable is True


async def test_every_row_carries_bounds_and_two_adjacent_downtimes_stay_two_rows(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_last_success(ingest_session_factory, ingest_bot_id, ago_s=_MIN_SILENCE_S + 10)
    await record_downtime_if_any(
        ingest_session_factory, bot_id=ingest_bot_id, min_silence_s=_MIN_SILENCE_S
    )

    # A second, later stop — never merged with the first.
    await _seed_last_success(ingest_session_factory, ingest_bot_id, ago_s=_MIN_SILENCE_S + 10)
    await record_downtime_if_any(
        ingest_session_factory, bot_id=ingest_bot_id, min_silence_s=_MIN_SILENCE_S
    )

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert len(rows) == 2
    for row in rows:
        assert row.gap_start_at is not None
        assert row.gap_end_at is not None
        assert row.reason == "downtime"
        assert row.detected_at is not None


@pytest.mark.skip(
    reason="open_gaps is asserted against the health block US5 builds (T068); tasks.md T044"
)
async def test_open_gaps_is_visible_in_the_health_report() -> None:
    ...
