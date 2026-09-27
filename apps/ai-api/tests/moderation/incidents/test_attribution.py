"""Attribution: `responsible_moderator_id = responsible_at(chat, detected_at)` — the owner at the
**flagging** moment, never `opened_at` (T021, lifecycle contract I5, FR-046...FR-048, SC-012).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.assignments import handover, open_assignment, responsible_at
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def test_a_handover_between_posting_and_flagging_attributes_to_the_incoming_owner(
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
    # Posted while the incumbent owned the group.
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
    )
    # Ownership changes before the flag.
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
    assert row["responsible_moderator_id"] == successor["moderator_id"]


async def test_a_reassignment_after_flagging_leaves_attribution_unmoved(
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

    # Reassigning the group afterwards must never move the already-flagged incident.
    await handover(
        incident_session_factory, telegram_chat_id=chat_pk, moderator_id=successor["moderator_id"]
    )

    row = await fetch_incident(incident_id=incident_id)
    assert row["responsible_moderator_id"] == incumbent["moderator_id"]


async def test_no_primary_at_detection_attributes_to_null(
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


async def test_valid_from_inclusive_valid_to_exclusive_at_the_detection_instant(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    fetch_incident: Any,
) -> None:
    """Exercises the exact predicate `open_incident` calls (`responsible_at`) at the incident's
    own `detected_at`, positioned by direct insert since neither `open_assignment` nor
    `handover` lets a caller choose `valid_from`/`valid_to` in advance of an unknown `now()`."""
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
        resolved = await responsible_at(session, telegram_chat_id=chat_pk, t=detected_at)
    assert resolved == incoming["moderator_id"]
