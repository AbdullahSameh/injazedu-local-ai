"""Attribution, amended by TG-M2.1 (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md`
G1, F1, amending lifecycle contract I5). An incident is opened assigned to nobody, and
`responsible_moderator_id` is no longer written. It counts in the figures of everyone on the group's
team at the **flagging** moment, never at `opened_at`, so our own detection latency is never
charged to a person (T021, FR-046...FR-048, SC-012).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.assignments import handover, open_assignment, team_at
from app.application.moderation.metrics import incident_outcome_stats
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _flagged_for(
    session_factory: async_sessionmaker[AsyncSession], moderator_id: int, around: datetime
) -> int:
    """How many incidents count in this moderator's "my groups" figures around `around` (F1)."""
    async with session_factory() as session:
        stats = await incident_outcome_stats(
            session,
            period_from=around - timedelta(hours=1),
            period_to=around + timedelta(hours=1),
            max_age_s=3600,
            moderator_id=moderator_id,
        )
    flagged: int = stats["flagged"]
    return flagged


async def test_a_handover_between_posting_and_flagging_counts_for_the_incoming_member(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_moderator: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    incumbent = await insert_moderator(display_name="Incumbent")
    successor = await insert_moderator(display_name="Successor")

    await open_assignment(
        incident_session_factory, telegram_chat_id=chat_pk, moderator_id=incumbent["moderator_id"]
    )
    # Posted while the incumbent was the group's team.
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
    )
    # The team changes before the flag.
    await handover(
        incident_session_factory, telegram_chat_id=chat_pk, moderator_id=successor["moderator_id"]
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None
    row = await fetch_incident(incident_id=incident_id)
    assert row["responsible_moderator_id"] is None  # G1: nothing assigned at creation
    detected_at = row["detected_at"]
    assert await _flagged_for(incident_session_factory, successor["moderator_id"], detected_at) == 1
    assert await _flagged_for(incident_session_factory, incumbent["moderator_id"], detected_at) == 0


async def test_a_reassignment_after_flagging_leaves_the_figures_unmoved(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_moderator: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    incumbent = await insert_moderator(display_name="Incumbent")
    successor = await insert_moderator(display_name="Successor")

    await open_assignment(
        incident_session_factory, telegram_chat_id=chat_pk, moderator_id=incumbent["moderator_id"]
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None

    # Reassigning the group afterwards must never move the already-flagged incident (O5).
    await handover(
        incident_session_factory, telegram_chat_id=chat_pk, moderator_id=successor["moderator_id"]
    )

    detected_at = (await fetch_incident(incident_id=incident_id))["detected_at"]
    assert await _flagged_for(incident_session_factory, incumbent["moderator_id"], detected_at) == 1
    assert await _flagged_for(incident_session_factory, successor["moderator_id"], detected_at) == 0


async def test_no_team_at_detection_counts_for_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    fetch_incident: Any,
) -> None:
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None
    row = await fetch_incident(incident_id=incident_id)
    assert row["responsible_moderator_id"] is None
    async with incident_session_factory() as session:
        assert await team_at(session, telegram_chat_id=chat_pk, t=row["detected_at"]) == []


async def test_valid_from_inclusive_valid_to_exclusive_at_the_detection_instant(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    fetch_incident: Any,
) -> None:
    """Exercises `team_at` and F1's predicate at the incident's own `detected_at`, positioned
    by direct insert since neither `open_assignment` nor `handover` lets a caller choose
    `valid_from`/`valid_to` in advance of an unknown `now()`."""
    from app.application.moderation.incidents import open_incident

    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
    )

    incident_id = await open_incident(
        incident_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="low",
        opened_by_user_id=1,
    )
    assert incident_id is not None
    detected_at = (await fetch_incident(incident_id=incident_id))["detected_at"]

    outgoing = await insert_moderator(display_name="Outgoing")
    incoming = await insert_moderator(display_name="Incoming")
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=outgoing["moderator_id"],
        valid_from=detected_at - timedelta(days=1),
        valid_to=detected_at,
    )
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=incoming["moderator_id"],
        valid_from=detected_at,
        valid_to=None,
    )

    async with incident_session_factory() as session:
        team = await team_at(session, telegram_chat_id=chat_pk, t=detected_at)
    assert team == [incoming["moderator_id"]]
    assert await _flagged_for(incident_session_factory, incoming["moderator_id"], detected_at) == 1
    assert await _flagged_for(incident_session_factory, outgoing["moderator_id"], detected_at) == 0
