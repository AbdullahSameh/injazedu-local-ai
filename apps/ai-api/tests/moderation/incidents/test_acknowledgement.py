"""Acknowledgement, read from `moderation_incident_state` only (T032, lifecycle contract
§3-§4, FR-012, FR-016, FR-021...FR-025, the first clarification). Incidents and evidence are
built directly through `conftest.py`, bypassing US1/US3's own code (`tasks.md` Phase 4 depends
on Phase 2 only) — this package computes nothing itself; every assertion reads the view.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


_OPENED_AT = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC)


async def _new_incident(
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    *,
    sender_telegram_user_id: int | None = None,
) -> tuple[int, int]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_telegram_user_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )
    return chat_pk, incident_id


async def test_a_moderators_direct_reply_acknowledges(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=_OPENED_AT + timedelta(minutes=5),
        telegram_user_id=mod["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
    )

    state = await read_state(incident_id)
    assert state["status"] == "acknowledged"
    assert state["acknowledgement_kind"] == "reply"
    assert state["acknowledged_by_moderator_id"] == mod["moderator_id"]


async def test_a_moderators_reaction_acknowledges(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    update_row_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "acknowledged"
    assert state["acknowledgement_kind"] == "reaction"
    assert state["acknowledged_by_moderator_id"] == mod["moderator_id"]


async def test_a_moderators_plain_non_reply_message_does_not_acknowledge(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=_OPENED_AT + timedelta(minutes=5),
        telegram_user_id=mod["telegram_user_id"],
        is_from_moderator=True,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"


async def test_a_non_moderators_reply_does_not_acknowledge(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    student_id = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=_OPENED_AT + timedelta(minutes=5),
        telegram_user_id=student_id,
        is_from_moderator=False,
        reply_to_message_id=1,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"


async def test_the_senders_own_reaction_does_not_acknowledge(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    mod = await insert_moderator()
    chat_pk, incident_id = await _new_incident(
        insert_chat,
        insert_message,
        insert_incident,
        sender_telegram_user_id=mod["telegram_user_id"],
    )
    update_row_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"


async def test_evidence_at_or_before_opened_at_does_not_acknowledge(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    update_row_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=_OPENED_AT,
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"


async def test_two_acknowledgements_inserted_latest_first_report_the_earlier_moment(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    earlier = _OPENED_AT + timedelta(minutes=5)
    later = _OPENED_AT + timedelta(minutes=20)

    later_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=later,
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=later_update_id,
    )
    earlier_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=earlier,
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=earlier_update_id,
    )

    state = await read_state(incident_id)
    assert state["first_acknowledgement_at"] == earlier


async def test_a_reaction_after_posting_but_before_flagging_acknowledges_at_its_own_moment(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
    mod = await insert_moderator()
    pre_flag_moment = _OPENED_AT + timedelta(minutes=10)
    assert _OPENED_AT < pre_flag_moment < _DETECTED_AT

    update_row_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=pre_flag_moment,
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "acknowledged"
    assert state["first_acknowledgement_at"] == pre_flag_moment
