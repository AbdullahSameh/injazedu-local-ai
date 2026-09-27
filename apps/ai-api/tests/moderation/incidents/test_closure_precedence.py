"""View-level precedence of a false-positive closure over every other kind of evidence (T048,
lifecycle contract §4 S1, §5 H1/H3/H7, FR-037, FR-041). Rows are inserted directly through
`conftest.py`'s `insert_action`, bypassing both applications' guarded writes — this package reads
`moderation_incident_state` only and computes nothing itself (contract N6).

⚠ The last test is the **probe 8** proof: a closure inserted over an already-**resolved** incident,
with no advisory lock and no status check first, *does* flip the status to
`closed_false_positive`. Nothing in the schema stops it — `ck_actions_strength` and friends
constrain one row's own shape, never the set of rows already there. That is exactly why
`App\\Models\\ModerationIncident`'s guard (lock → read `moderation_incident_state` → insert only if
H1 allows it) has to live on the model, not merely be "usually followed" by callers: this test is
what happens when it is skipped.
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


async def test_a_panel_false_positive_closes_an_open_incident_with_reason_and_account(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)

    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        action_strength=None,
        occurred_at=_DETECTED_AT + timedelta(minutes=5),
        panel_user_id=42,
        moderation_incident_id=incident_id,
        note="Reported in error — not spam.",
    )

    state = await read_state(incident_id)
    assert state["status"] == "closed_false_positive"
    assert state["closed_by_user_id"] == 42
    assert state["close_reason"] == "Reported in error — not spam."


async def test_a_ban_recorded_after_the_closure_leaves_it_closed_but_lists_the_ban(
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

    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        action_strength=None,
        occurred_at=_DETECTED_AT + timedelta(minutes=5),
        panel_user_id=42,
        moderation_incident_id=incident_id,
        note="Reported in error.",
    )
    ban_update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_DETECTED_AT + timedelta(minutes=10),
        subject_telegram_user_id=sender_id,
        source_update_id=ban_update_id,
    )

    state = await read_state(incident_id)
    assert state["status"] == "closed_false_positive"
    evidence = await read_evidence(incident_id)
    ban_rows = [row for row in evidence if row["kind"] == "ban"]
    assert len(ban_rows) == 1


async def test_panel_resolve_resolves_by_confirmation_crediting_no_moderator(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    read_state: Any,
) -> None:
    chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)

    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_resolve",
        action_strength="confirmation",
        occurred_at=_DETECTED_AT + timedelta(minutes=5),
        panel_user_id=7,
        moderation_incident_id=incident_id,
        note="Confirmed with the group owner — the message was already gone.",
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "panel_resolve"
    assert state["resolved_by_moderator_id"] is None
    assert state["resolved_by_user_id"] == 7


async def test_probe_8_a_closure_over_a_resolved_incident_without_the_guard_changes_status(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """Documents why the guard (lock, then read the view, then insert-if-allowed) has to live on
    `ModerationIncident` and not be left to callers: inserted with no lock and no prior status
    check, a false-positive closure *does* land over an already-resolved incident and flips its
    status — the database has no constraint that stops it (probe 8)."""
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
    assert (await read_state(incident_id))["status"] == "resolved"

    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        action_strength=None,
        occurred_at=_DETECTED_AT + timedelta(minutes=10),
        panel_user_id=99,
        moderation_incident_id=incident_id,
        note="Inserted with no guard, no lock, no prior status check.",
    )

    state = await read_state(incident_id)
    assert state["status"] == "closed_false_positive"
