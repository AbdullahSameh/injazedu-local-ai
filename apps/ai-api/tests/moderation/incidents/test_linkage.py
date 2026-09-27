"""Membership evidence resolving incidents, read from `moderation_incident_evidence` /
`moderation_incident_state` only (T040, lifecycle contract §3-§4 L1-L7, S1-S6, FR-026...FR-033,
FR-049, SC-004, SC-007, SC-008, SC-015). Incidents and evidence are built directly through
`conftest.py`, bypassing US3's own code (`tasks.md` Phase 5 depends on Phase 2 only) — this
package computes nothing itself; every assertion reads the views.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _new_incident(
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    *,
    message_id: int = 1,
    chat_pk: int | None = None,
    sender_telegram_user_id: int | None,
) -> tuple[int, int]:
    if chat_pk is None:
        chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=message_id,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_telegram_user_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=message_id,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )
    return chat_pk, incident_id


async def test_a_ban_with_no_prior_evidence_resolves_directly(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk, incident_id = await _new_incident(
        insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
    )
    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "ban"
    assert state["first_acknowledgement_at"] is None


async def test_a_restriction_after_an_acknowledgement_resolves_and_keeps_the_acknowledgement(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk, incident_id = await _new_incident(
        insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
    )
    mod = await insert_moderator()
    ack_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=1,
        source_update_id=ack_update_id,
    )
    restrict_update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="restriction",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=10),
        subject_telegram_user_id=sender_id,
        source_update_id=restrict_update_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "restriction"
    assert state["first_acknowledgement_at"] is not None


async def test_one_ban_resolves_three_incidents(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk = await insert_chat(chat_id=-_rand_id())
    incident_ids = []
    for message_id in (1, 2, 3):
        _, incident_id = await _new_incident(
            insert_chat,
            insert_message,
            insert_incident,
            message_id=message_id,
            chat_pk=chat_pk,
            sender_telegram_user_id=sender_id,
        )
        incident_ids.append(incident_id)

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    for incident_id in incident_ids:
        state = await read_state(incident_id)
        assert state["status"] == "resolved"
        assert state["resolution_kind"] == "ban"


async def test_a_ban_of_a_different_member_a_different_group_or_before_opened_at_does_not_link(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    other_id = await insert_user(tg_user_id=_rand_id())
    chat_pk, incident_id = await _new_incident(
        insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
    )
    other_chat_pk = await insert_chat(chat_id=-_rand_id())

    different_member = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=other_id,
        source_update_id=different_member,
    )
    different_group = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=other_chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=sender_id,
        source_update_id=different_group,
    )
    before_flag = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT - timedelta(minutes=1),
        subject_telegram_user_id=sender_id,
        source_update_id=before_flag,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"


async def test_enforcement_by_a_non_owner_moderator_credits_that_moderator(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
    fetch_incident: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk, incident_id = await _new_incident(
        insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
    )
    non_owner_mod = await insert_moderator(display_name="Non-owner Mod")

    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        actor_telegram_user_id=non_owner_mod["telegram_user_id"],
        actor_moderator_id=non_owner_mod["moderator_id"],
        subject_telegram_user_id=sender_id,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolved_by_moderator_id"] == non_owner_mod["moderator_id"]
    incident = await fetch_incident(incident_id=incident_id)
    assert incident["responsible_moderator_id"] != non_owner_mod["moderator_id"]


async def test_enforcement_by_an_unmapped_admin_a_bot_or_anonymously_resolves_crediting_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    for actor_is_anonymous in (False, True):
        sender_id = await insert_user(tg_user_id=_rand_id())
        chat_pk, incident_id = await _new_incident(
            insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
        )
        performer_id = await insert_user(tg_user_id=_rand_id())
        update_row_id = await captured_update("chat_member", {}, chat_id=None)
        await insert_action(
            telegram_chat_id=chat_pk,
            action_type="ban",
            action_strength="enforcement",
            occurred_at=_OPENED_AT + timedelta(minutes=5),
            actor_telegram_user_id=performer_id,
            actor_moderator_id=None,
            actor_is_anonymous=actor_is_anonymous,
            subject_telegram_user_id=sender_id,
            source_update_id=update_row_id,
        )

        state = await read_state(incident_id)
        assert state["status"] == "resolved"
        assert state["resolved_by_moderator_id"] is None
        assert state["resolved_by_telegram_user_id"] == performer_id


async def test_an_unban_afterwards_is_listed_with_null_strength_and_stays_resolved(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
    read_evidence: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    chat_pk, incident_id = await _new_incident(
        insert_chat, insert_message, insert_incident, sender_telegram_user_id=sender_id
    )
    ban_update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=sender_id,
        source_update_id=ban_update_id,
    )
    unban_update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reversal",
        action_strength=None,
        occurred_at=_OPENED_AT + timedelta(minutes=10),
        subject_telegram_user_id=sender_id,
        source_update_id=unban_update_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    evidence = await read_evidence(incident_id)
    reversal_rows = [row for row in evidence if row["kind"] == "reversal"]
    assert len(reversal_rows) == 1
    assert reversal_rows[0]["strength"] is None


async def test_an_anchor_sent_on_behalf_of_a_chat_never_links_membership_evidence(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """An anchor with `telegram_user_id IS NULL` (channel-sent) can never satisfy branch (c)'s
    `a.subject_telegram_user_id = m.telegram_user_id` — equality with NULL is never true — however
    the ban's own subject is chosen (L7)."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        sender_chat_id=-_rand_id(),
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )
    subject_id = await insert_user(tg_user_id=_rand_id())
    update_row_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_OPENED_AT + timedelta(minutes=5),
        subject_telegram_user_id=subject_id,
        source_update_id=update_row_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "open"
