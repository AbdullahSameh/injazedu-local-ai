"""`derive_membership_evidence`, dispatched through `process_update_row` on a captured
`chat_member` event (T039, lifecycle contract §2.1 V1-V6, D-TG-108, D-TG-109, FR-010, FR-013,
FR-014, FR-019): a ban records one enforcement row crediting a declared moderator when the
performer is one; a voluntary leave records nothing; `processed_at` is set in every case.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderation_actions
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


def _chat_member_body(
    *,
    performer: dict[str, Any],
    subject: dict[str, Any],
    date: datetime,
    old_status: str,
    new_status: str,
    old_is_member: bool = True,
    new_is_member: bool = True,
    until_date: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "from": performer,
        "date": int(date.timestamp()),
        "old_chat_member": {"user": subject, "status": old_status, "is_member": old_is_member},
        "new_chat_member": {"user": subject, "status": new_status, "is_member": new_is_member},
    }
    if until_date is not None:
        body["new_chat_member"]["until_date"] = until_date
    return body


async def test_a_ban_records_one_enforcement_row(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    await insert_chat(chat_id=chat_id)
    performer_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=performer_tg_id, display_name="Mod")
    subject_tg_id = _rand_id()

    date = datetime(2026, 1, 10, 10, 12, 0, tzinfo=UTC)
    body = _chat_member_body(
        performer={"id": performer_tg_id, "is_bot": False, "first_name": "Mod"},
        subject={"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
        date=date,
        old_status="member",
        new_status="kicked",
        until_date=0,
    )
    update_row_id = await captured_update("chat_member", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    rows = await _actions_for_update(incident_session_factory, update_row_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["action_type"] == "ban"
    assert row["action_strength"] == "enforcement"
    assert row["occurred_at"] == date
    assert row["actor_moderator_id"] is not None
    assert row["subject_telegram_user_id"] is not None
    assert row["detail"]["old_status"] == "member"
    assert row["detail"]["new_status"] == "kicked"
    assert row["detail"]["until_date"] == 0


async def test_a_voluntary_leave_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    await insert_chat(chat_id=chat_id)
    member_tg_id = _rand_id()

    member = {"id": member_tg_id, "is_bot": False, "first_name": "Member"}
    body = _chat_member_body(
        performer=member,
        subject=member,
        date=datetime(2026, 1, 10, 10, 12, 0, tzinfo=UTC),
        old_status="member",
        new_status="left",
        new_is_member=False,
    )
    update_row_id = await captured_update("chat_member", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_an_unmeasured_chat_records_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    await insert_chat(chat_id=chat_id, is_monitored=False)
    performer_tg_id = _rand_id()
    subject_tg_id = _rand_id()

    body = _chat_member_body(
        performer={"id": performer_tg_id, "is_bot": False, "first_name": "Mod"},
        subject={"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
        date=datetime(2026, 1, 10, 10, 12, 0, tzinfo=UTC),
        old_status="member",
        new_status="kicked",
    )
    update_row_id = await captured_update("chat_member", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    assert await _actions_for_update(incident_session_factory, update_row_id) == []


async def test_performer_group_anonymous_bot_is_recorded_as_anonymous(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    await insert_chat(chat_id=chat_id)
    subject_tg_id = _rand_id()

    body = _chat_member_body(
        performer={"id": 1087968824, "is_bot": True, "username": "GroupAnonymousBot"},
        subject={"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
        date=datetime(2026, 1, 10, 10, 12, 0, tzinfo=UTC),
        old_status="member",
        new_status="restricted",
    )
    update_row_id = await captured_update("chat_member", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)

    rows = await _actions_for_update(incident_session_factory, update_row_id)
    assert len(rows) == 1
    assert rows[0]["actor_is_anonymous"] is True
    assert rows[0]["actor_moderator_id"] is None


async def test_the_same_event_processed_three_times_yields_one_row(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    captured_update: Any,
) -> None:
    from app.workers.tasks.moderation.process_update import process_update_row

    chat_id = -_rand_id()
    await insert_chat(chat_id=chat_id)
    performer_tg_id = _rand_id()
    subject_tg_id = _rand_id()

    body = _chat_member_body(
        performer={"id": performer_tg_id, "is_bot": False, "first_name": "Admin"},
        subject={"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
        date=datetime(2026, 1, 10, 10, 12, 0, tzinfo=UTC),
        old_status="member",
        new_status="restricted",
    )
    update_row_id = await captured_update("chat_member", body, chat_id=chat_id)

    await process_update_row(incident_session_factory, update_row_id)
    await process_update_row(incident_session_factory, update_row_id)
    await process_update_row(incident_session_factory, update_row_id)

    assert len(await _actions_for_update(incident_session_factory, update_row_id)) == 1
