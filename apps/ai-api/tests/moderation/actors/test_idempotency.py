"""Idempotency (FR-002, SC-001) and `sent_at`'s provenance (FR-003, SC-002).

Same contract assumed as `test_derivation.py`: `app.application.moderation.messages
.derive_message(session_factory, *, update_row_id: int) -> int | None`, INSERT-ONLY per
`contracts/message-derivation.md` §2(a) — `ON CONFLICT (telegram_chat_id, message_id) DO
NOTHING RETURNING id`, so a repeat call returns `None` and leaves the row untouched.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.actors.conftest import make_message_update


async def test_deriving_the_same_event_three_times_yields_one_byte_identical_row(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    update = make_message_update(1, chat_id=actors_chat_id, text="idempotent")
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    first = await derive_message(actors_session_factory, update_row_id=row_id)
    assert first is not None
    row_after_first = await fetch_message(telegram_chat_id=chat_pk, message_id=1)

    second = await derive_message(actors_session_factory, update_row_id=row_id)
    third = await derive_message(actors_session_factory, update_row_id=row_id)
    assert second is None
    assert third is None

    row_after_repeat = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row_after_repeat == row_after_first


async def test_a_shuffled_batch_derives_the_same_rows_as_an_ordered_one(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
    count_messages: Any,
) -> None:
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    n = 12
    row_ids: list[int] = []
    for i in range(1, n + 1):
        update = make_message_update(i, chat_id=actors_chat_id, text=f"msg-{i}")
        row_ids.append(
            await insert_captured_update(
                bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
            )
        )

    ordered = list(row_ids)
    for rid in ordered:
        assert await derive_message(actors_session_factory, update_row_id=rid) is not None
    assert await count_messages(telegram_chat_id=chat_pk) == n

    rows_after_ordered = [
        await fetch_message(telegram_chat_id=chat_pk, message_id=i) for i in range(1, n + 1)
    ]

    shuffled = list(row_ids)
    random.Random(7).shuffle(shuffled)
    for rid in shuffled:
        # every one of these is a repeat — DO NOTHING every time — so the count must not move
        await derive_message(actors_session_factory, update_row_id=rid)
    assert await count_messages(telegram_chat_id=chat_pk) == n

    rows_after_shuffled = [
        await fetch_message(telegram_chat_id=chat_pk, message_id=i) for i in range(1, n + 1)
    ]
    assert rows_after_shuffled == rows_after_ordered


async def test_sent_at_comes_from_the_platforms_date_never_received_at_or_now(
    actors_session_factory: async_sessionmaker[AsyncSession],
    actors_bot_id: int,
    actors_chat_id: int,
    insert_chat: Any,
    insert_captured_update: Any,
    fetch_message: Any,
) -> None:
    """FR-003, SC-002: a fixture whose platform `date` and wall-clock capture time differ by a
    known, large amount — `sent_at` must reflect only the former."""
    from app.application.moderation.messages import derive_message

    chat_pk = await insert_chat(chat_id=actors_chat_id)
    platform_epoch = 1_600_000_000  # 2020-09-13T12:26:40Z — far from "now" at insertion time
    update = make_message_update(1, chat_id=actors_chat_id, text="clock skew", date=platform_epoch)
    row_id = await insert_captured_update(
        bot_id=actors_bot_id, chat_id=actors_chat_id, update=update
    )

    before_derive = datetime.now(UTC)
    assert await derive_message(actors_session_factory, update_row_id=row_id) is not None

    row = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert row is not None
    expected_sent_at = datetime.fromtimestamp(platform_epoch, tz=UTC)
    assert row["sent_at"] == expected_sent_at
    assert row["sent_at"] != row["created_at"]
    # sanity: the wall clock at derivation time is nowhere near the platform's stamp
    assert (before_derive - expected_sent_at).total_seconds() > 3600
