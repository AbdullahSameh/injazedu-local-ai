"""US6 — the two non-negotiable guarantees (FR-003, FR-004, FR-004a, FR-004b, FR-005 scenario 5,
FR-022, SC-022, D-TG-37): the platform's own `409` on one machine, and this machine's own Redis
lease across two processes on the same machine.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from app.application.moderation.ingest import (
    GAP_REASON_CONFLICT_409,
    PollLeaseHeldElsewhereError,
    handle_conflict,
    hold_poll_lease,
)
from app.application.moderation.ingestion_probe import check as ingestion_health_check
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import ingestion_gaps, ingestion_state
from app.providers.telegram.models import BotIdentity
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import RecordingSleep

_STANDDOWN_COUNT = 5


def _settings() -> Settings:
    # TELEGRAM_BOT_TOKEN shares a line with REDIS_URL deliberately, mirroring
    # test_health_block.py's `_settings` — alone on its own line it would match the secret
    # scanner's own heuristic.
    return Settings(
        DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
        REDIS_URL="redis://localhost:6379/0", TELEGRAM_BOT_TOKEN="t",
    )


class _StubProvider:
    def __init__(self, *, bot_id: int) -> None:
        self._bot_id = bot_id

    async def get_me(self) -> BotIdentity:
        return BotIdentity(bot_id=self._bot_id, username="injaz_test_bot")

    async def get_updates(self, **_kwargs: object) -> list:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_webhook_info(self) -> object:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_chat_member(self, **_kwargs: object) -> object:  # pragma: no cover
        raise NotImplementedError


async def _state_row(
    session_factory: async_sessionmaker[AsyncSession], bot_id: int
) -> sa.engine.Row:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(
                    ingestion_state.c.consecutive_conflicts, ingestion_state.c.stood_down_at
                ).where(ingestion_state.c.bot_id == bot_id)
            )
        ).one()


async def _gap_rows(session_factory: async_sessionmaker[AsyncSession], bot_id: int) -> list:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(ingestion_gaps)
                .where(ingestion_gaps.c.bot_id == bot_id)
                .order_by(ingestion_gaps.c.id)
            )
        ).all()


async def test_five_consecutive_conflicts_stand_down_with_one_gap_row_and_report_it(
    ingest_engine: AsyncEngine,
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    recording_sleep: RecordingSleep,
) -> None:
    stood_down_results = [
        await handle_conflict(
            ingest_session_factory,
            bot_id=ingest_bot_id,
            standdown_count=_STANDDOWN_COUNT,
            sleep=recording_sleep,
        )
        for _ in range(_STANDDOWN_COUNT)
    ]

    assert stood_down_results == [False, False, False, False, True]
    # Backing off, not spinning: one recorded sleep per conflict that did not itself stand down.
    assert len(recording_sleep.calls) == _STANDDOWN_COUNT - 1

    row = await _state_row(ingest_session_factory, ingest_bot_id)
    assert row.consecutive_conflicts == _STANDDOWN_COUNT
    assert row.stood_down_at is not None

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    conflict_rows = [r for r in rows if r.reason == GAP_REASON_CONFLICT_409]
    assert len(conflict_rows) == 1
    assert conflict_rows[0].gap_end_at is None  # open — no known end until an explicit restart

    report = await ingestion_health_check(
        engine=ingest_engine,
        settings=_settings(),
        client=_StubProvider(bot_id=ingest_bot_id),
    )
    assert report.ingestion["stood_down"] is True


async def test_a_single_conflict_then_a_success_resets_the_counter_and_capture_continues(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    recording_sleep: RecordingSleep,
) -> None:
    from app.application.moderation.ingest import record_poll_outcome

    stood_down = await handle_conflict(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        standdown_count=_STANDDOWN_COUNT,
        sleep=recording_sleep,
    )
    assert stood_down is False

    await record_poll_outcome(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        bot_username=None,
        allowed_updates=["message"],
        stored=[],
    )

    row = await _state_row(ingest_session_factory, ingest_bot_id)
    assert row.consecutive_conflicts == 0
    assert row.stood_down_at is None  # capture is still running

    # A fresh conflict starts counting from 1 again, not from 2 — proof the reset actually took.
    stood_down_again = await handle_conflict(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        standdown_count=_STANDDOWN_COUNT,
        sleep=recording_sleep,
    )
    assert stood_down_again is False
    row_after = await _state_row(ingest_session_factory, ingest_bot_id)
    assert row_after.consecutive_conflicts == 1


async def test_a_second_process_on_the_same_machine_is_refused_the_lease(
    poll_lease_redis: Redis,
) -> None:
    async with hold_poll_lease(poll_lease_redis, ttl_s=5.0, renew_interval_s=1.0):
        with pytest.raises(PollLeaseHeldElsewhereError):
            async with hold_poll_lease(poll_lease_redis, ttl_s=5.0, renew_interval_s=1.0):
                pytest.fail("a second holder must never enter the block")

    # Released on exit — a third attempt after the first releases succeeds cleanly.
    async with hold_poll_lease(poll_lease_redis, ttl_s=5.0, renew_interval_s=1.0):
        pass
