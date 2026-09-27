"""T063 — the re-derivation proof: captured `chat_member` and `message_reaction` events marked
`processed_at` before this milestone's derivation code existed are never revisited by ordinary
processing (FR-083); `rederive_chat_evidence` (T064) is the only path that catches them up,
reporting `recorded` and `incidents_changed` read from `moderation_incident_state` before and
after (D-TG-128, lifecycle contract R3-R5); a second run over the same range reports zero and
changes nothing (FR-084, FR-085, SC-019).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.application.moderation.identities import map_moderator
from app.infrastructure.models_moderation import moderation_actions
from app.scripts.rederive_chat import rederive_chat_evidence
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 10, 6, 30, 0, tzinfo=UTC)


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


def _chat_member_ban_body(
    *, performer_tg_id: int, subject_tg_id: int, date: datetime
) -> dict[str, Any]:
    return {
        "from": {"id": performer_tg_id, "is_bot": False, "first_name": "Mod"},
        "date": int(date.timestamp()),
        "old_chat_member": {
            "user": {"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
            "status": "member",
            "is_member": True,
        },
        "new_chat_member": {
            "user": {"id": subject_tg_id, "is_bot": False, "first_name": "Student"},
            "status": "kicked",
            "is_member": False,
            "until_date": 0,
        },
    }


def _reaction_ack_body(
    *, chat_id: int, message_id: int, mod_tg_id: int, date: datetime
) -> dict[str, Any]:
    return {
        "chat": {"id": chat_id},
        "message_id": message_id,
        "date": int(date.timestamp()),
        "user": {"id": mod_tg_id, "is_bot": False, "first_name": "Mod"},
        "old_reaction": [],
        "new_reaction": [{"type": "emoji", "emoji": "✅"}],
    }


async def test_rederive_evidence_catches_up_pre_milestone_events_and_is_idempotent(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    captured_update: Any,
    read_state: Any,
    fetch_incident: Any,
) -> None:
    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)

    subject_tg_id = _rand_id()
    subject_surrogate = await insert_user(tg_user_id=subject_tg_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=subject_surrogate,
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    before_state = await read_state(incident_id)
    assert before_state["status"] == "open"

    mod_tg_id = _rand_id()
    await map_moderator(incident_session_factory, tg_user_id=mod_tg_id, display_name="Mod")

    # Both events are "already processed" — marked as TG-M1's ingestion actor left them, before
    # this milestone's derivation code existed. Nothing in ordinary operation revisits them.
    already_processed_at = datetime(2026, 1, 11, 0, 0, 0, tzinfo=UTC)
    reaction_update_id = await captured_update(
        "message_reaction",
        _reaction_ack_body(
            chat_id=chat_id,
            message_id=1,
            mod_tg_id=mod_tg_id,
            date=_OPENED_AT + timedelta(minutes=5),
        ),
        chat_id=chat_id,
        processed_at=already_processed_at,
    )
    ban_update_id = await captured_update(
        "chat_member",
        _chat_member_ban_body(
            performer_tg_id=mod_tg_id,
            subject_tg_id=subject_tg_id,
            date=_OPENED_AT + timedelta(minutes=10),
        ),
        chat_id=chat_id,
        processed_at=already_processed_at,
    )

    # FR-083: being marked processed produced no evidence under the pre-milestone code, and
    # nothing has re-derived it yet.
    assert await _actions_for_update(incident_session_factory, reaction_update_id) == []
    assert await _actions_for_update(incident_session_factory, ban_update_id) == []
    still_open = await read_state(incident_id)
    assert still_open["status"] == "open"

    first_report = await rederive_chat_evidence(incident_session_factory, chat_id=chat_id)
    assert first_report.recorded == 2
    assert first_report.incidents_changed == 1

    reaction_rows = await _actions_for_update(incident_session_factory, reaction_update_id)
    assert len(reaction_rows) == 1
    assert reaction_rows[0]["action_type"] == "reaction"
    ban_rows = await _actions_for_update(incident_session_factory, ban_update_id)
    assert len(ban_rows) == 1
    assert ban_rows[0]["action_type"] == "ban"

    after_state = await read_state(incident_id)
    assert after_state["status"] == "resolved"
    assert after_state["resolution_kind"] == "ban"
    assert after_state["first_acknowledgement_at"] is not None

    # FR-084, FR-085, SC-019: a second run over the same range reports zero and changes nothing —
    # no incident, label or panel act is created, altered or removed.
    second_report = await rederive_chat_evidence(incident_session_factory, chat_id=chat_id)
    assert second_report.recorded == 0
    assert second_report.incidents_changed == 0

    assert len(await _actions_for_update(incident_session_factory, reaction_update_id)) == 1
    assert len(await _actions_for_update(incident_session_factory, ban_update_id)) == 1
    incident_row = await fetch_incident(incident_id=incident_id)
    assert incident_row["category"] == "SPAM_OR_AD"
    assert incident_row["severity"] == "low"

    async with incident_session_factory() as session:
        panel_acts = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderation_actions)
                .where(moderation_actions.c.moderation_incident_id == incident_id)
            )
        ).scalar_one()
    assert panel_acts == 0


async def test_a_purged_payload_is_skipped(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    captured_update: Any,
) -> None:
    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)

    subject_tg_id = _rand_id()
    subject_surrogate = await insert_user(tg_user_id=subject_tg_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=subject_surrogate,
    )
    await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    update_row_id = await captured_update(
        "chat_member",
        _chat_member_ban_body(
            performer_tg_id=_rand_id(),
            subject_tg_id=subject_tg_id,
            date=_OPENED_AT + timedelta(minutes=5),
        ),
        chat_id=chat_id,
    )
    async with incident_session_factory() as session:
        await session.execute(
            sa.text("UPDATE telegram_updates SET payload_purged_at = now() WHERE id = :id"),
            {"id": update_row_id},
        )
        await session.commit()

    report = await rederive_chat_evidence(incident_session_factory, chat_id=chat_id)
    assert report.recorded == 0
    assert report.incidents_changed == 0
    assert await _actions_for_update(incident_session_factory, update_row_id) == []
