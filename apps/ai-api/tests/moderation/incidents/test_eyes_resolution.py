"""A moderator's 👀 resolves an incident (TG-M4.1, `docs/plan/telegram/tg-eyes-reaction-resolution-
plan.md` E1-E7).

Every case goes through `process_update_row` on a captured `message_reaction` event — the live
path — and reads the result from `moderation_incident_state`, `moderation_incident_evidence` and
`moderation_incident_assignee` exactly as the panel does. Nothing here computes a status.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.identities import map_moderator
from app.domain.moderation.incident import (
    RESOLVING_REACTION,
    allows_resolving_reaction,
    reaction_strength,
)
from app.infrastructure.models_moderation import (
    moderation_actions,
    moderation_incident_assignee,
    moderators,
)
from app.workers.tasks.moderation.process_update import process_update_row
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_POSTED = datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
_FLAGGED = _POSTED + timedelta(minutes=10)

_EYES = {"type": "emoji", "emoji": "👀"}
_THUMBS = {"type": "emoji", "emoji": "👍"}


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


# --- The pure rule (E1-E3) ----------------------------------------------------------------------


def test_the_resolving_reaction_is_the_standard_eyes_emoji() -> None:
    assert RESOLVING_REACTION == "\U0001f440"


@pytest.mark.parametrize(
    ("added", "active", "expected"),
    [
        ([_EYES], True, "confirmation"),
        ([_THUMBS, _EYES], True, "confirmation"),
        ([_THUMBS], True, "acknowledgement"),
        ([_EYES], False, "acknowledgement"),
        ([{"type": "custom_emoji", "custom_emoji_id": "5368324170671202286"}], True,
         "acknowledgement"),
        ([{"type": "paid"}], True, "acknowledgement"),
    ],
)
def test_reaction_strength(added: list[dict[str, str]], active: bool, expected: str) -> None:
    assert reaction_strength(added, moderator_is_active=active) == expected


@pytest.mark.parametrize(
    ("available", "expected"),
    [(None, True), ([_THUMBS, _EYES], True), ([_THUMBS], False), ([], False)],
)
def test_allows_resolving_reaction(available: list[dict[str, str]] | None, expected: bool) -> None:
    """E9: an omitted `available_reactions` is the platform's "all emoji reactions allowed"."""
    assert allows_resolving_reaction(available) is expected


# --- The live path ------------------------------------------------------------------------------


async def _moderator(
    session_factory: async_sessionmaker[AsyncSession], name: str
) -> dict[str, int]:
    tg_user_id = _rand_id()
    moderator_id = await map_moderator(session_factory, tg_user_id=tg_user_id, display_name=name)
    return {"tg_user_id": tg_user_id, "moderator_id": moderator_id}


async def _flagged_group(
    insert_chat: Any, insert_message: Any, insert_incident: Any
) -> tuple[int, int, int]:
    """A monitored group with one flagged message (id 1) — returns (chat_id, chat_pk, incident)."""
    chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_POSTED)
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_POSTED,
        detected_at=_FLAGGED,
        category="SPAM_OR_AD",
        severity="high",
    )
    return chat_id, chat_pk, incident_id


async def _react(
    session_factory: async_sessionmaker[AsyncSession],
    captured_update: Any,
    *,
    chat_id: int,
    by: dict[str, int],
    at: datetime,
    old: list[dict[str, str]] | None = None,
    new: list[dict[str, str]] | None = None,
    message_id: int = 1,
    process: bool = True,
) -> int:
    body = {
        "chat": {"id": chat_id},
        "message_id": message_id,
        "user": {"id": by["tg_user_id"], "is_bot": False, "first_name": "Mod"},
        "date": int(at.timestamp()),
        "old_reaction": old or [],
        "new_reaction": new or [],
    }
    update_row_id: int = await captured_update("message_reaction", body, chat_id=chat_id)
    if process:
        await process_update_row(session_factory, update_row_id)
    return update_row_id


async def _rows(
    session_factory: async_sessionmaker[AsyncSession], update_row_id: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        result = await session.execute(
            sa.select(moderation_actions).where(
                moderation_actions.c.source_update_id == update_row_id
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def test_eyes_first_resolves_an_open_incident_directly(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
    read_evidence: Any,
) -> None:
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Zainab")
    at = _FLAGGED + timedelta(minutes=3)

    update_row_id = await _react(
        incident_session_factory, captured_update, chat_id=chat_id, by=mod, at=at, new=[_EYES]
    )

    [row] = await _rows(incident_session_factory, update_row_id)
    assert (row["action_type"], row["action_strength"]) == ("reaction", "confirmation")
    assert row["detail"]["added"] == [_EYES]
    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolved_at"] == at
    assert state["first_confirmation_at"] == at
    assert state["first_acknowledgement_at"] is None
    assert (state["resolution_kind"], state["resolution_strength"]) == ("reaction", "confirmation")
    assert state["resolved_by_moderator_id"] == mod["moderator_id"]
    assert [(e["kind"], e["strength"]) for e in await read_evidence(incident_id)] == [
        ("reaction", "confirmation")
    ]


async def test_one_moderator_acknowledges_and_another_resolves_each_is_recorded(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_assignment: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """Requirement 2: the resolver is the one who 👀'd, even though a colleague acted first — and
    the first act still decides the assignment (TG-M2.1 G-rules)."""
    chat_id, chat_pk, incident_id = await _flagged_group(
        insert_chat, insert_message, insert_incident
    )
    ahmed = await _moderator(incident_session_factory, "Ahmed")
    zainab = await _moderator(incident_session_factory, "Zainab")
    for member in (ahmed, zainab):
        await insert_assignment(
            telegram_chat_id=chat_pk,
            moderator_id=member["moderator_id"],
            valid_from=_POSTED - timedelta(days=1),
        )

    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=ahmed,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_THUMBS],
    )
    assert (await read_state(incident_id))["status"] == "acknowledged"
    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=zainab,
        at=_FLAGGED + timedelta(minutes=4),
        new=[_EYES],
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["acknowledged_by_moderator_id"] == ahmed["moderator_id"]
    assert state["resolved_by_moderator_id"] == zainab["moderator_id"]
    async with incident_session_factory() as session:
        assignee = (
            await session.execute(
                sa.select(moderation_incident_assignee).where(
                    moderation_incident_assignee.c.incident_id == incident_id
                )
            )
        ).mappings().one()
    assert (assignee["assigned_moderator_id"], assignee["assigned_via"]) == (
        ahmed["moderator_id"],
        "reaction",
    )


async def test_changing_thumbs_to_eyes_resolves(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Mod")

    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_THUMBS],
    )
    changed = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=2),
        old=[_THUMBS],
        new=[_EYES],
    )

    [row] = await _rows(incident_session_factory, changed)
    assert row["action_strength"] == "confirmation"
    assert (await read_state(incident_id))["status"] == "resolved"


async def test_changing_or_removing_eyes_never_reverses_the_resolution(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Mod")
    resolved_at = _FLAGGED + timedelta(minutes=1)

    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=resolved_at,
        new=[_EYES],
    )
    swapped = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=2),
        old=[_EYES],
        new=[_THUMBS],
    )
    removed = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=3),
        old=[_THUMBS],
        new=[],
    )
    again = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=4),
        new=[_EYES],
    )

    assert [r["action_strength"] for r in await _rows(incident_session_factory, swapped)] == [
        "acknowledgement"
    ]
    assert await _rows(incident_session_factory, removed) == []
    assert [r["action_strength"] for r in await _rows(incident_session_factory, again)] == [
        "confirmation"
    ]
    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolved_at"] == resolved_at


async def test_the_same_eyes_event_processed_three_times_records_one_row(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Mod")
    update_row_id = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_EYES],
    )
    for _ in range(2):
        await process_update_row(incident_session_factory, update_row_id)

    assert len(await _rows(incident_session_factory, update_row_id)) == 1
    assert (await read_state(incident_id))["status"] == "resolved"


async def test_a_deactivated_moderators_eyes_only_acknowledges(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """E3: a reaction needs no admin rights, so someone who left must not close incidents."""
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Former")
    async with incident_session_factory() as session:
        await session.execute(
            sa.update(moderators)
            .where(moderators.c.id == mod["moderator_id"])
            .values(is_active=False)
        )
        await session.commit()

    update_row_id = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_EYES],
    )

    [row] = await _rows(incident_session_factory, update_row_id)
    assert row["action_strength"] == "acknowledgement"
    assert (await read_state(incident_id))["status"] == "acknowledged"


async def test_a_non_moderators_eyes_changes_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    student = {"tg_user_id": _rand_id(), "moderator_id": 0}

    update_row_id = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=student,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_EYES],
    )

    assert await _rows(incident_session_factory, update_row_id) == []
    assert (await read_state(incident_id))["status"] == "open"


async def test_eyes_on_another_message_leaves_the_incident_open(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """E2: it must be on the flagged message itself."""
    chat_id, chat_pk, incident_id = await _flagged_group(
        insert_chat, insert_message, insert_incident
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=_POSTED + timedelta(minutes=1)
    )
    mod = await _moderator(incident_session_factory, "Mod")

    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_EYES],
        message_id=2,
    )

    assert (await read_state(incident_id))["status"] == "open"


async def test_eyes_before_the_flag_resolves_at_the_reactions_moment(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    """E6: a moderator who handled it before the model flagged it."""
    chat_id, _, incident_id = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Mod")
    at = _POSTED + timedelta(minutes=2)

    await _react(
        incident_session_factory, captured_update, chat_id=chat_id, by=mod, at=at, new=[_EYES]
    )

    state = await read_state(incident_id)
    assert state["status"] == "resolved"
    assert state["resolved_at"] == at < _FLAGGED


async def test_eyes_after_not_a_violation_is_listed_and_changes_nothing(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
    read_evidence: Any,
) -> None:
    chat_id, chat_pk, incident_id = await _flagged_group(
        insert_chat, insert_message, insert_incident
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        occurred_at=_FLAGGED + timedelta(minutes=1),
        panel_user_id=1,
        moderation_incident_id=incident_id,
        note="a course announcement",
    )
    mod = await _moderator(incident_session_factory, "Mod")

    await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=2),
        new=[_EYES],
    )

    assert (await read_state(incident_id))["status"] == "closed_false_positive"
    assert [e["kind"] for e in await read_evidence(incident_id)] == [
        "panel_false_positive",
        "reaction",
    ]


# --- The lock (E4) ------------------------------------------------------------------------------


async def test_eyes_waits_for_the_incident_lock_and_thumbs_does_not(
    incident_session_factory: async_sessionmaker[AsyncSession],
    incident_sync_engine: Any,
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    captured_update: Any,
) -> None:
    """A confirming reaction serialises against a panel closure (H4); an acknowledging one never
    waits for it."""
    chat_id, _, _ = await _flagged_group(insert_chat, insert_message, insert_incident)
    mod = await _moderator(incident_session_factory, "Mod")
    eyes = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=1),
        new=[_EYES],
        process=False,
    )
    thumbs = await _react(
        incident_session_factory,
        captured_update,
        chat_id=chat_id,
        by=mod,
        at=_FLAGGED + timedelta(minutes=2),
        old=[_EYES],
        new=[_EYES, _THUMBS],
        process=False,
    )

    holder = incident_sync_engine.connect()
    try:
        holder.execute(text("SELECT pg_advisory_lock(hashtext('moderation:incidents'))"))

        await asyncio.wait_for(process_update_row(incident_session_factory, thumbs), timeout=5)
        assert len(await _rows(incident_session_factory, thumbs)) == 1

        waiting = asyncio.create_task(process_update_row(incident_session_factory, eyes))
        await asyncio.sleep(0.5)
        assert not waiting.done()
        assert await _rows(incident_session_factory, eyes) == []
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(hashtext('moderation:incidents'))"))
        holder.close()

    await asyncio.wait_for(waiting, timeout=5)
    [row] = await _rows(incident_session_factory, eyes)
    assert row["action_strength"] == "confirmation"
