"""A backlog of not-yet-interpreted captured records is handed over in the platform's assigned
order, all interpreted, zero duplicates (FR-013, SC-024).

This exercises `app.workers.tasks.moderation.process_update.process_update_row` — the per-row
function the `process_update` actor calls (T023 fills in its body to dispatch by kind: `message`
→ `derive_message`, `edited_message` → `apply_edit`) — called directly over a backlog in
`update_id` order, the same way live capture schedules one call per stored row.

Deliberately **not** `drain_pending_updates` (D-TG-64, T024): that actor reconciles the
`processed_at IS NULL` backlog left by a crashed worker with a direct `UPDATE …
SET processed_at`, and stays exactly as TG-M1 left it — it is not extended into a re-derivation
engine. The recovery path for anything it swallows unread is the operator's deliberate
`rederive_chat` command (US2), not this actor. This test's subject is the interpreting step
itself handling volume in order, not that reconciliation sweep.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


async def test_a_backlog_of_100_is_interpreted_in_order_with_zero_duplicates(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    count_messages: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    n = 120
    row_ids: list[int] = []
    for i in range(1, n + 1):
        update = make_message_update(i, chat_id=actors_chat_id, text=f"backlog-{i}")
        row_ids.append(
            await insert_captured_update(
                bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
            )
        )

    # Handed over in the platform's assigned order — update_id ascending, matching row_ids
    # insertion order (each make_message_update(i, ...) carries update_id=i).
    for row_id in row_ids:
        await process_update_row(actors_session_factory, row_id)

    assert await count_messages(telegram_chat_id=chat_pk) == n

    # A second pass over the identical backlog derives nothing new (§2(a) — insert-only).
    for row_id in row_ids:
        await process_update_row(actors_session_factory, row_id)

    assert await count_messages(telegram_chat_id=chat_pk) == n
