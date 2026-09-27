"""`derive_reaction_evidence`, dispatched through `process_update_row` on a captured
`message_reaction` event (T031, lifecycle contract §2.2 V7-V10, D-TG-110, FR-011, FR-013, FR-015,
FR-019): a declared moderator's added reaction records one row; nobody else's reaction is
evidence of anything; `processed_at` is set in every case.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderation_actions, telegram_updates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _actions_for_update(
    session_factory: async_sessionmaker[AsyncSession], source_update_id: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        result = await session.execute(
            sa.select(moderation_actions).where(
                moderation_actions.c.source_update_id == source_update_id
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def _processed_at(
    session_factory: async_sessionmaker[AsyncSession], update_row_id: int
) -> Any:
    async with session_factory() as session:
        result = await session.execute(
            sa.select(telegram_updates.c.processed_at).where(
                telegram_updates.c.id == update_row_id
            )
        )
        return result.scalar_one()


def _reaction_body(
    *,
    chat_id: int,
    message_id: int,
    date: datetime,
    user: dict[str, Any] | None = None,
    actor_chat: dict[str, Any] | None = None,
    old_reaction: list[dict[str, Any]] | None = None,
    new_reaction: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "chat": {"id": chat_id},
        "message_id": message_id,
        "date": int(date.timestamp()),
        "old_reaction": old_reaction or [],
        "new_reaction": new_reaction if new_reaction is not None else [],
    }
    if user is not None:
        body["user"] = user
    if actor_chat is not None:
        body["actor_chat"] = actor_chat
    return body


async def test_a_declared_moderators_added_reaction_records_one_row(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    mod_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=mod_tg_id, display_name="Mod")

    date = datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC)
    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=date,
        user={"id": mod_tg_id, "is_bot": False, "first_name": "Mod"},
        new_reaction=[{"type": "emoji", "emoji": "✅"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    rows = await _actions_for_update(incident_session_factory, update_row_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["action_type"] == "reaction"
    assert row["action_strength"] == "acknowledgement"
    assert row["actor_moderator_id"] is not None
    assert row["target_message_id"] == 1
    assert row["occurred_at"] == date
    assert row["detail"]["added"] == [{"type": "emoji", "emoji": "✅"}]


async def test_a_non_moderators_reaction_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    non_mod_tg_id = _rand_id()

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": non_mod_tg_id, "is_bot": False, "first_name": "Student"},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_an_anonymous_reaction_with_actor_chat_and_no_user_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        actor_chat={"id": chat_id},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_a_removal_only_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    mod_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=mod_tg_id, display_name="Mod")

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": mod_tg_id, "is_bot": False, "first_name": "Mod"},
        old_reaction=[{"type": "emoji", "emoji": "👍"}],
        new_reaction=[],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_an_unmeasured_chat_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id, is_monitored=False)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    mod_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=mod_tg_id, display_name="Mod")

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": mod_tg_id, "is_bot": False, "first_name": "Mod"},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_the_same_event_processed_three_times_yields_one_row(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    mod_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=mod_tg_id, display_name="Mod")

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": mod_tg_id, "is_bot": False, "first_name": "Mod"},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)
    await process_update_row(incident_session_factory, update_row_id)
    await process_update_row(incident_session_factory, update_row_id)

    assert len(await _actions_for_update(incident_session_factory, update_row_id)) == 1


async def test_becoming_a_moderator_after_the_event_records_nothing_that_was_not_already_absent(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    """The gate is evaluated at recording time (V9): the first, un-mapped run records nothing —
    there is nothing for a later mapping to retroactively change. A subsequent run, after the
    reactor is mapped, evaluates the same event freshly and records it, exactly as re-derivation
    is meant to (R3-R5) — not a second copy of a fact already recorded."""
    from app.application.moderation.evidence import derive_reaction_evidence

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    reactor_tg_id = _rand_id()

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": reactor_tg_id, "is_bot": False, "first_name": "Later Mod"},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    first_result = await derive_reaction_evidence(
        incident_session_factory, update_row_id=update_row_id
    )
    assert first_result is None
    assert await _actions_for_update(incident_session_factory, update_row_id) == []

    await map_moderator(
        incident_session_factory, tg_user_id=reactor_tg_id, display_name="Later Mod"
    )

    second_result = await derive_reaction_evidence(
        incident_session_factory, update_row_id=update_row_id
    )
    assert second_result is not None
    rows = await _actions_for_update(incident_session_factory, update_row_id)
    assert len(rows) == 1
    assert rows[0]["actor_moderator_id"] is not None


async def test_processed_at_is_set_in_every_case(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    )
    non_mod_tg_id = _rand_id()

    body = _reaction_body(
        chat_id=chat_id,
        message_id=1,
        date=datetime(2026, 1, 10, 7, 0, 0, tzinfo=UTC),
        user={"id": non_mod_tg_id, "is_bot": False, "first_name": "Student"},
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
    )
    update_row_id = await captured_update("message_reaction", body, chat_id=chat_id)

    assert await _processed_at(incident_session_factory, update_row_id) is None
    await process_update_row(incident_session_factory, update_row_id)
    assert await _processed_at(incident_session_factory, update_row_id) is not None
