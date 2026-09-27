"""Evidence derivation from captured events (`contracts/incident-lifecycle.md` §2, D-TG-108…
D-TG-112).

Phase 4 (US2) adds `derive_reaction_evidence`, from `message_reaction`. Phase 5 (US3) adds
`derive_membership_evidence`, from `chat_member`, sharing this module. Both mirror
`messages.derive_message`'s shape exactly: everything is resolved from the captured event's own
`telegram_updates.payload`, gated on the chat's `is_monitored`, and inserted at most once per
event (`uq_moderation_actions_source_update`, `ON CONFLICT ... DO NOTHING` — V13, R1), so
re-interpreting an event through `process_update` or `rederive_chat.py --with-evidence` (R3) is
always harmless. Identities go through TG-M2's `upsert_identity`; moderator status through its
`_is_declared_moderator` / `identities.moderator_id_for`, reused rather than restated (D-TG-110).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.identities import moderator_id_for, upsert_identity
from app.application.moderation.locks import incident_lock
from app.application.moderation.messages import _display_name_for
from app.domain.moderation.incident import (
    added_reactions,
    classify_membership_change,
    is_anonymous_performer,
)
from app.infrastructure.models_moderation import (
    moderation_actions,
    telegram_chats,
    telegram_updates,
)

logger = logging.getLogger(__name__)


async def _fetch_update(session: AsyncSession, update_row_id: int) -> Any:
    result = await session.execute(
        sa.select(telegram_updates).where(telegram_updates.c.id == update_row_id)
    )
    return result.mappings().one()


async def _chat_surrogate_and_monitored(session: AsyncSession, chat_id: int) -> tuple[int, bool]:
    result = await session.execute(
        sa.select(telegram_chats.c.id, telegram_chats.c.is_monitored).where(
            telegram_chats.c.chat_id == chat_id
        )
    )
    row = result.one()
    return row.id, row.is_monitored


async def derive_reaction_evidence(
    session_factory: async_sessionmaker[AsyncSession], *, update_row_id: int
) -> int | None:
    """Derives at most one `moderation_actions` row of `action_type='reaction'` from the captured
    `message_reaction` event at `telegram_updates.id == update_row_id`
    (`contracts/incident-lifecycle.md` §2.2).

    Gated on the chat's `is_monitored`, exactly as `derive_message`. Records nothing when the
    event names no `user` — an anonymous `actor_chat` reaction names no person (V8) — when
    `added_reactions` (the reaction-identity delta, V7) is empty, or when the reacting user is not
    a declared moderator at recording time (V9): nobody else's reaction is evidence of anything.
    `actor_moderator_id` is resolved once, here, and — because a `moderation_actions` row is never
    updated (V14) — is never recomputed afterwards.

    `ON CONFLICT ON CONSTRAINT uq_moderation_actions_source_update DO NOTHING` (V13, R1): at most
    one row per captured event, however often it is reprocessed. **No lock** (lifecycle contract
    H4): two acknowledgements racing are two harmless rows. Logs `update_id` and `chat_id` only
    (N8).
    """
    async with session_factory() as session:
        update_row = await _fetch_update(session, update_row_id)
        body: dict[str, Any] = update_row["payload"].get("message_reaction") or {}

        chat_pk, is_monitored = await _chat_surrogate_and_monitored(
            session, update_row["chat_id"]
        )
        if not is_monitored:
            return None

        user = body.get("user")
        if not isinstance(user, dict):
            return None

        added = added_reactions(body.get("old_reaction") or [], body.get("new_reaction") or [])
        if not added:
            return None

        occurred_at = datetime.fromtimestamp(body["date"], tz=UTC)
        actor_telegram_user_id = await upsert_identity(
            session,
            tg_user_id=user["id"],
            username=user.get("username"),
            display_name=_display_name_for(user),
            is_bot=bool(user.get("is_bot", False)),
            observed_at=occurred_at,
        )
        actor_moderator_id = await moderator_id_for(
            session, telegram_user_id=actor_telegram_user_id
        )
        if actor_moderator_id is None:
            await session.commit()
            return None

        insert_stmt = (
            pg_insert(moderation_actions)
            .values(
                telegram_chat_id=chat_pk,
                action_type="reaction",
                action_strength="acknowledgement",
                occurred_at=occurred_at,
                actor_telegram_user_id=actor_telegram_user_id,
                actor_moderator_id=actor_moderator_id,
                target_message_id=body["message_id"],
                source_update_id=update_row_id,
                detail={"added": list(added)},
            )
            .on_conflict_do_nothing(constraint="uq_moderation_actions_source_update")
            .returning(moderation_actions.c.id)
        )
        result = await session.execute(insert_stmt)
        inserted_id = result.scalar_one_or_none()
        await session.commit()

    if inserted_id is not None:
        logger.info(
            "reaction evidence recorded",
            extra={"update_id": update_row_id, "chat_id": chat_pk},
        )
    return inserted_id


def _classify_membership_update(body: dict[str, Any]) -> tuple[str, str | None] | None:
    """Reads `from`, `old_chat_member`, `new_chat_member` from a captured `ChatMemberUpdated`
    payload (Bot API 10.3) and classifies it through `domain.incident.classify_membership_change`
    — the payload-reading wrapper `test_membership_classifier.py`'s Finding-4 cases prove against
    the reference shape, not only the bare classifier (D-TG-108). Pure: dict access only, no I/O.
    """
    performer = body["from"]
    subject = body["new_chat_member"]["user"]
    return classify_membership_change(
        body["old_chat_member"],
        body["new_chat_member"],
        performed_by_subject=performer["id"] == subject["id"],
    )


async def derive_membership_evidence(
    session_factory: async_sessionmaker[AsyncSession], *, update_row_id: int
) -> int | None:
    """Derives at most one `moderation_actions` row — `ban`, `expulsion`, `restriction` or
    `reversal` — from the captured `chat_member` event at `telegram_updates.id ==
    update_row_id` (`contracts/incident-lifecycle.md` §2.1).

    Gated on the chat's `is_monitored`, exactly as `derive_reaction_evidence`. Records nothing
    when `_classify_membership_update` returns `None` — performed by the member themselves (V2),
    or a pair that is not evidence (V3's last row). Performer and subject are both resolved
    through TG-M2's `upsert_identity`; `actor_moderator_id` is resolved once, here, from the
    performer, and — because a row is never updated (V14) — is never recomputed afterwards.
    `actor_is_anonymous` is set when the performer is the platform's anonymous-administrator
    account (D-TG-109).

    Takes `incident_lock` **before** the insert (lifecycle contract H4): a membership change can
    resolve an incident, so it must serialise against a concurrent panel closure. Reaction inserts
    do not take it, but this one does. `ON CONFLICT ON CONSTRAINT
    uq_moderation_actions_source_update DO NOTHING` (V13, R1): at most one row per captured event,
    however often it is reprocessed. Logs `update_id` and `chat_id` only (N8).
    """
    async with session_factory() as session:
        update_row = await _fetch_update(session, update_row_id)
        body: dict[str, Any] = update_row["payload"].get("chat_member") or {}

        chat_pk, is_monitored = await _chat_surrogate_and_monitored(
            session, update_row["chat_id"]
        )
        if not is_monitored:
            return None

        classification = _classify_membership_update(body)
        if classification is None:
            await session.commit()
            return None
        kind, strength = classification

        occurred_at = datetime.fromtimestamp(body["date"], tz=UTC)
        performer = body["from"]
        subject = body["new_chat_member"]["user"]

        performer_telegram_user_id = await upsert_identity(
            session,
            tg_user_id=performer["id"],
            username=performer.get("username"),
            display_name=_display_name_for(performer),
            is_bot=bool(performer.get("is_bot", False)),
            observed_at=occurred_at,
        )
        subject_telegram_user_id = await upsert_identity(
            session,
            tg_user_id=subject["id"],
            username=subject.get("username"),
            display_name=_display_name_for(subject),
            is_bot=bool(subject.get("is_bot", False)),
            observed_at=occurred_at,
        )
        actor_moderator_id = await moderator_id_for(
            session, telegram_user_id=performer_telegram_user_id
        )

        detail: dict[str, Any] = {
            "old_status": body["old_chat_member"].get("status"),
            "new_status": body["new_chat_member"].get("status"),
        }
        until_date = body["new_chat_member"].get("until_date")
        if until_date is not None:
            detail["until_date"] = until_date

        async with incident_lock(session):
            insert_stmt = (
                pg_insert(moderation_actions)
                .values(
                    telegram_chat_id=chat_pk,
                    action_type=kind,
                    action_strength=strength,
                    occurred_at=occurred_at,
                    actor_telegram_user_id=performer_telegram_user_id,
                    actor_moderator_id=actor_moderator_id,
                    actor_is_anonymous=is_anonymous_performer(performer),
                    subject_telegram_user_id=subject_telegram_user_id,
                    source_update_id=update_row_id,
                    detail=detail,
                )
                .on_conflict_do_nothing(constraint="uq_moderation_actions_source_update")
                .returning(moderation_actions.c.id)
            )
            result = await session.execute(insert_stmt)
            inserted_id = result.scalar_one_or_none()
        await session.commit()

    if inserted_id is not None:
        logger.info(
            "membership evidence recorded",
            extra={"update_id": update_row_id, "chat_id": chat_pk},
        )
    return inserted_id
