"""Opening an incident, and readers over the incident lifecycle (`data-model.md` §1, §3,
`contracts/incident-lifecycle.md`).

`incident_state` and `incident_evidence` **read** the lifecycle and never compute it (lifecycle
contract N6): plain `SELECT`s from `moderation_incident_evidence` and `moderation_incident_state`
— the two views are the only definitions of linkage and derived state, read identically by the
PHP `ModerationIncident` model. No status, "first" moment or link is ever computed here.

`open_incident` (US1, lifecycle contract §1) is this milestone's one write path in Python — used
by today's tests and by TG-M5 tomorrow; the panel's `ModerationIncident::openOn` is the production
opener.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.assignments import responsible_at
from app.domain.moderation.incident import CATEGORIES, SEVERITIES
from app.infrastructure.models_moderation import (
    moderation_incident_evidence,
    moderation_incident_state,
    moderation_incidents,
    telegram_messages,
)

logger = logging.getLogger(__name__)


async def open_incident(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
    category: str,
    severity: str,
    opened_by_user_id: int,
    source: str = "operator",
) -> int | None:
    """Opens exactly one incident against a stored, non-service message (I1-I7): `opened_at` =
    the anchor's `sent_at`, `detected_at` = the database's `now()` at insert, and
    `responsible_moderator_id` = `responsible_at(chat, detected_at)` (I5) — the owner at the
    **flagging** moment, resolved via TG-M2's single definition in the same transaction so it
    reads the identical `now()` value `detected_at` is stamped with (D-TG-48).

    `ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING RETURNING id` (I2, R2): opening the
    same anchor twice is not an error — the second attempt returns `None`. Raises `ValueError` on
    a service message (FR-007) or an unrecognised label (I4). Writes nothing else and touches no
    attention item (I6, I7). Logs `incident_id` and `message_id` only (FR-081, N8).
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category!r}")
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity: {severity!r}")

    async with session_factory() as session:
        message = (
            await session.execute(
                sa.select(telegram_messages.c.sent_at, telegram_messages.c.is_service).where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.message_id == telegram_message_id,
                )
            )
        ).one()
        if message.is_service:
            raise ValueError("cannot open an incident on a service message")

        # Read once, within this transaction: Postgres' `now()` is `transaction_timestamp()`
        # (identical across every statement in one transaction), so the owner resolved below is
        # the owner at the exact instant this incident is stamped as detected — never a second,
        # separately-read clock value (mirrors `assignments.py`'s own rationale).
        detected_at = (await session.execute(sa.select(sa.func.now()))).scalar_one()

        responsible_moderator_id = await responsible_at(
            session, telegram_chat_id=telegram_chat_id, t=detected_at
        )

        insert_stmt = (
            pg_insert(moderation_incidents)
            .values(
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
                opened_at=message.sent_at,
                detected_at=detected_at,
                source=source,
                opened_by_user_id=opened_by_user_id,
                category=category,
                severity=severity,
                responsible_moderator_id=responsible_moderator_id,
            )
            .on_conflict_do_nothing(constraint="uq_incident_anchor")
            .returning(moderation_incidents.c.id)
        )
        result = await session.execute(insert_stmt)
        inserted_id = result.scalar_one_or_none()
        await session.commit()

    if inserted_id is not None:
        logger.info(
            "incident opened",
            extra={"incident_id": inserted_id, "message_id": telegram_message_id},
        )
    return inserted_id


async def incident_state(session: AsyncSession, incident_id: int) -> sa.RowMapping | None:
    """`SELECT * FROM moderation_incident_state WHERE incident_id = :id` — the status, moments
    and actors, exactly as the view derives them (lifecycle contract S1-S6)."""
    result = await session.execute(
        sa.select(moderation_incident_state).where(
            moderation_incident_state.c.incident_id == incident_id
        )
    )
    return result.mappings().one_or_none()


async def incident_evidence(session: AsyncSession, incident_id: int) -> Sequence[sa.RowMapping]:
    """`SELECT * FROM moderation_incident_evidence WHERE incident_id = :id`, ordered
    `(occurred_at, source_rank, evidence_id)` — D-TG-106's tie-break, the trail's own order."""
    result = await session.execute(
        sa.select(moderation_incident_evidence)
        .where(moderation_incident_evidence.c.incident_id == incident_id)
        .order_by(
            moderation_incident_evidence.c.occurred_at,
            moderation_incident_evidence.c.source_rank,
            moderation_incident_evidence.c.evidence_id,
        )
    )
    return result.mappings().all()
