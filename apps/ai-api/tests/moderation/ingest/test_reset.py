"""US3 — the identifier-reset protocol. A jump under the stall window is a real loss; at or
beyond it, Telegram renumbered and nothing was lost (FR-019's one exception, FR-024, D-TG-33,
`contracts/telegram-provider.md` §5, `contracts/ingestion-guarantees.md` G4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from app.application.moderation.ingest import (
    StoredUpdate,
    record_identifier_jump_if_any,
    record_poll_outcome,
    record_reset_outcome,
    resync_after_stall,
    store_batch,
)
from app.infrastructure.models_moderation import ingestion_gaps, ingestion_state
from app.providers.telegram.client import TelegramClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import FakeTelegramTransport, make_message_update

_STALL_WINDOW_S = 691200  # MODERATION_STALL_RESYNC_S default, 8 days


async def _seed_state(
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: int,
    *,
    last_update_id: int,
    event_ago_s: float,
) -> None:
    await record_poll_outcome(
        session_factory,
        bot_id=bot_id,
        bot_username=None,
        allowed_updates=["message"],
        stored=[StoredUpdate(id=1, update_id=last_update_id, chat_id=None)],
    )
    backdated = datetime.now(UTC) - timedelta(seconds=event_ago_s)
    async with session_factory() as session:
        await session.execute(
            ingestion_state.update()
            .where(ingestion_state.c.bot_id == bot_id)
            .values(last_event_at=backdated)
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


async def test_a_jump_with_recent_last_event_at_writes_one_update_id_jump_row(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_state(ingest_session_factory, ingest_bot_id, last_update_id=100, event_ago_s=60)

    reason = await record_identifier_jump_if_any(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        incoming_update_ids=[140],
        stall_window_s=_STALL_WINDOW_S,
    )

    assert reason == "update_id_jump"
    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert len(rows) == 1
    assert rows[0].reason == "update_id_jump"
    assert rows[0].unrecoverable is True


async def test_a_jump_with_last_event_at_older_than_a_week_is_not_an_update_id_jump(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    await _seed_state(
        ingest_session_factory,
        ingest_bot_id,
        last_update_id=100,
        event_ago_s=_STALL_WINDOW_S + 60,
    )

    # The same observable as the test above — id 140 where 101 was expected — but here
    # `last_event_at` is stale: this is Telegram's renumbering, not a loss, and must not be
    # recorded as one (D-TG-33).
    reason = await record_identifier_jump_if_any(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        incoming_update_ids=[140],
        stall_window_s=_STALL_WINDOW_S,
    )

    assert reason != "update_id_jump"
    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    assert all(row.reason != "update_id_jump" for row in rows)


async def test_reset_end_to_end_position_moves_backwards_and_writes_update_id_reset(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    fake_transport: FakeTelegramTransport,
) -> None:
    # Empty polls have already been happening; last_event_at is 9 days old.
    await _seed_state(
        ingest_session_factory, ingest_bot_id, last_update_id=500, event_ago_s=9 * 86400
    )

    fake_transport.enqueue_ok("getUpdates", [make_message_update(7)])
    client = TelegramClient("test-token", transport=fake_transport.transport)

    resynced = await resync_after_stall(
        ingest_session_factory,
        client,
        bot_id=ingest_bot_id,
        allowed_updates=["message"],
        limit=100,
        timeout_s=30,
        stall_window_s=_STALL_WINDOW_S,
    )

    assert resynced is not None
    method, params = fake_transport.calls[-1]
    assert method == "getUpdates"
    assert "offset" not in params  # the re-sync omits offset entirely — never a negative offset

    stored = await store_batch(
        ingest_session_factory, bot_id=ingest_bot_id, updates=resynced, schedule=lambda *_a: None
    )
    assert {u.update_id for u in stored} == {7}

    await record_reset_outcome(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        bot_username=None,
        allowed_updates=["message"],
        stored=stored,
    )

    async with ingest_session_factory() as session:
        row = (
            await session.execute(
                sa.select(ingestion_state.c.last_update_id).where(
                    ingestion_state.c.bot_id == ingest_bot_id
                )
            )
        ).one()
    assert row.last_update_id == 7  # the position moved backwards from 500

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    reset_rows = [r for r in rows if r.reason == "update_id_reset"]
    assert len(reset_rows) == 1
    assert reset_rows[0].unrecoverable is False


async def test_update_id_reset_is_not_treated_as_missing_data(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    fake_transport: FakeTelegramTransport,
) -> None:
    await _seed_state(
        ingest_session_factory, ingest_bot_id, last_update_id=500, event_ago_s=9 * 86400
    )
    fake_transport.enqueue_ok("getUpdates", [make_message_update(7)])
    client = TelegramClient("test-token", transport=fake_transport.transport)

    resynced = await resync_after_stall(
        ingest_session_factory,
        client,
        bot_id=ingest_bot_id,
        allowed_updates=["message"],
        limit=100,
        timeout_s=30,
        stall_window_s=_STALL_WINDOW_S,
    )
    assert resynced is not None

    rows = await _gap_rows(ingest_session_factory, ingest_bot_id)
    reset_rows = [r for r in rows if r.reason == "update_id_reset"]
    assert len(reset_rows) == 1
    # A report window overlapping this row must not be marked incomplete — the column that
    # decides that is `unrecoverable`, and it must be false, never inferred from the row's mere
    # presence.
    assert reset_rows[0].unrecoverable is False
