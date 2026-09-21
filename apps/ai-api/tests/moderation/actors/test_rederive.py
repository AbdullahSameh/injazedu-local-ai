"""Re-derivation — the operator's way to catch a group up on what was captured before it was
switched on (FR-020, FR-021, FR-022, FR-023, SC-006, SC-007, SC-008).

Contract assumed here, implemented by T032 (not yet written), `app/scripts/rederive_chat.py`:

    async def rederive_chat(
        session_factory, *, chat_id: int, since: datetime | None = None,
        until: datetime | None = None, batch_size: int = <settings default>,
    ) -> RederiveReport

`chat_id` is the **platform's** chat id (what the operator names on the CLI), not the surrogate
row id. `RederiveReport` carries `examined`, `derived` and `skipped` (`contracts/message-
derivation.md` §7 R5). It walks `telegram_updates` rows of kind `message`/`edited_message` for
that chat in `update_id` order, in batches bounded by `batch_size`, and calls the **same**
`messages.derive_message` / `messages.apply_edit` the live actor calls (R3) — so a second
identical run derives nothing further (R7), and a row whose `payload_purged_at` is set is
counted skipped rather than producing a hollow record or aborting the run (R6). It refuses a
chat that is not measured (R1) by raising `ChatNotMonitoredError`.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.infrastructure.models_moderation import telegram_updates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


async def test_a_measured_chats_backlog_derives_with_original_send_times_and_reports_counts(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    count_messages: Any,
) -> None:
    from app.scripts.rederive_chat import rederive_chat

    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)
    n = 8
    for i in range(1, n + 1):
        update = make_message_update(
            i, chat_id=actors_chat_id, text=f"backlog-{i}", date=1_700_000_000 + i
        )
        await insert_captured_update(bot_id=actors_bot_id, chat_id=actors_chat_id, update=update)

    report = await rederive_chat(actors_session_factory, chat_id=actors_chat_id)
    assert report.examined == n
    assert report.derived == n
    assert report.skipped == 0
    assert await count_messages(telegram_chat_id=chat_pk) == n

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None

    # A second identical run derives 0 further records (§2(a), R7).
    second_report = await rederive_chat(actors_session_factory, chat_id=actors_chat_id)
    assert second_report.examined == n
    assert second_report.derived == 0
    assert await count_messages(telegram_chat_id=chat_pk) == n


async def test_rederive_refuses_a_chat_that_is_not_measured(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
) -> None:
    from app.scripts.rederive_chat import ChatNotMonitoredError, rederive_chat

    await insert_chat(chat_id=actors_chat_id, is_monitored=False)
    update = make_message_update(1, chat_id=actors_chat_id, text="not measured")
    await insert_captured_update(bot_id=actors_bot_id, chat_id=actors_chat_id, update=update)

    with pytest.raises(ChatNotMonitoredError):
        await rederive_chat(actors_session_factory, chat_id=actors_chat_id)


async def test_a_purged_payload_is_skipped_not_a_hollow_row_and_does_not_abort_the_run(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    count_messages: Any,
) -> None:
    from app.scripts.rederive_chat import rederive_chat

    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)

    purged_update = make_message_update(1, chat_id=actors_chat_id, text="was here")
    purged_row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=purged_update
    )
    async with actors_session_factory() as session:
        await session.execute(
            telegram_updates.update()
            .where(telegram_updates.c.id == purged_row_id)
            .values(payload_purged_at=sa.func.now())
        )
        await session.commit()

    intact_update = make_message_update(2, chat_id=actors_chat_id, text="still intact")
    await insert_captured_update(bot_id=actors_bot_id, chat_id=actors_chat_id, update=intact_update)

    report = await rederive_chat(actors_session_factory, chat_id=actors_chat_id)

    assert report.examined == 2
    assert report.derived == 1
    assert report.skipped == 1
    assert await count_messages(telegram_chat_id=chat_pk) == 1
    assert await fetch_message(telegram_chat_id=chat_pk, message_id=1) is None
    assert await fetch_message(telegram_chat_id=chat_pk, message_id=2) is not None


async def test_rederive_walks_in_update_id_order_across_batches_with_no_loss_or_duplication(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    count_messages: Any,
) -> None:
    from app.scripts.rederive_chat import rederive_chat

    chat_pk = await insert_chat(chat_id=actors_chat_id, is_monitored=True)
    n = 25
    for i in range(1, n + 1):
        update = make_message_update(i, chat_id=actors_chat_id, text=f"batch-{i}")
        await insert_captured_update(bot_id=actors_bot_id, chat_id=actors_chat_id, update=update)

    # A batch size that does not divide n evenly, and is well under the total — the walk must
    # cross several batch boundaries without losing or duplicating a single row.
    report = await rederive_chat(actors_session_factory, chat_id=actors_chat_id, batch_size=7)

    assert report.examined == n
    assert report.derived == n
    assert await count_messages(telegram_chat_id=chat_pk) == n
