"""Message derivation — the two write modes (`contracts/message-derivation.md`, `data-model.md`
§2).

Phase 3 (US1) adds `derive_message` (INSERT-ONLY, D-TG-49) and `apply_edit` (a targeted UPDATE of
text and edit time only, D-TG-50). Both take the captured event's own `telegram_updates.id` and
resolve everything else from its stored `payload` — the same shape `process_update` dispatches
from and `rederive_chat.py` (US2) walks, so there is exactly one derivation code path (contract
R3). Phase 4 (US2) adds the measurement gate. Phase 5 (US3) resolves `is_from_moderator` at
insert, from whether the sender is a declared, mapped moderator at that moment
(`contracts/message-derivation.md` §5) — never recomputed, since §2(a)'s insert-only write never
touches an existing row again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.identities import upsert_identity
from app.application.moderation.text import normalize
from app.infrastructure.config import load_settings
from app.infrastructure.models_moderation import (
    moderators,
    telegram_chats,
    telegram_messages,
    telegram_updates,
)
from app.workers.tasks.moderation.evaluate_attention import evaluate_attention
from app.workers.tasks.moderation.match_response import match_response

# Coarse, in priority order. An entry here is stored as its own key name; anything present that
# isn't one of these, isn't text/a caption, and isn't a recognised service field is content this
# domain does not model — 'other' (data-model.md §2, "no CHECK on media_kind").
_MEDIA_KIND_FIELDS = (
    "photo",
    "video",
    "document",
    "voice",
    "audio",
    "sticker",
    "animation",
    "video_note",
    "contact",
    "location",
    "venue",
    "poll",
    "dice",
    "game",
    "invoice",
    "successful_payment",
)

# Presence of any of these marks a service announcement (FR-006) — never a person speaking.
_SERVICE_FIELDS = (
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "new_chat_members",
    "left_chat_member",
    "group_chat_created",
    "supergroup_chat_created",
    "channel_chat_created",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    "pinned_message",
    "message_auto_delete_timer_changed",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_scheduled",
    "video_chat_participants_invited",
    "forum_topic_created",
    "forum_topic_closed",
    "forum_topic_reopened",
    "forum_topic_edited",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    "write_access_allowed",
    "proximity_alert_triggered",
    "boost_added",
)

_URL_ENTITY_TYPES = frozenset({"url", "text_link"})
_MENTION_ENTITY_TYPES = frozenset({"mention", "text_mention"})
_FORWARD_FIELDS = (
    "forward_date",
    "forward_from",
    "forward_from_chat",
    "forward_sender_name",
    "forward_origin",
    "is_automatic_forward",
)


def _is_service(body: dict[str, Any]) -> bool:
    return any(field in body for field in _SERVICE_FIELDS)


def _media_kind(body: dict[str, Any]) -> str | None:
    for field in _MEDIA_KIND_FIELDS:
        if field in body:
            return field
    if body.get("text") is None and body.get("caption") is None and not _is_service(body):
        return "other"
    return None


def _entity_flags(body: dict[str, Any]) -> dict[str, bool]:
    entities = body.get("entities") or body.get("caption_entities") or []
    types = {e.get("type") for e in entities if isinstance(e, dict)}
    return {
        "has_url": bool(types & _URL_ENTITY_TYPES),
        "has_phone": "phone_number" in types,
        "has_mention": bool(types & _MENTION_ENTITY_TYPES),
        "forwarded": any(body.get(field) for field in _FORWARD_FIELDS),
    }


def _text_and_normalized(body: dict[str, Any]) -> tuple[str | None, str | None]:
    original_text = body.get("text")
    if original_text is None:
        original_text = body.get("caption")
    normalized_text = normalize(original_text) if original_text is not None else None
    return original_text, normalized_text


def _display_name_for(from_user: dict[str, Any]) -> str | None:
    first_name = from_user.get("first_name")
    last_name = from_user.get("last_name")
    if not first_name:
        return None
    return f"{first_name} {last_name}".strip() if last_name else first_name


async def _fetch_update(session: AsyncSession, update_row_id: int) -> Any:
    result = await session.execute(
        sa.select(telegram_updates).where(telegram_updates.c.id == update_row_id)
    )
    return result.mappings().one()


async def _chat_surrogate(session: AsyncSession, chat_id: int) -> int:
    result = await session.execute(
        sa.select(telegram_chats.c.id).where(telegram_chats.c.chat_id == chat_id)
    )
    chat_pk: int = result.scalar_one()
    return chat_pk


async def _chat_surrogate_and_monitored(session: AsyncSession, chat_id: int) -> tuple[int, bool]:
    result = await session.execute(
        sa.select(telegram_chats.c.id, telegram_chats.c.is_monitored).where(
            telegram_chats.c.chat_id == chat_id
        )
    )
    row = result.one()
    return row.id, row.is_monitored


async def _is_declared_moderator(session: AsyncSession, *, telegram_user_id: int) -> bool:
    """Whether `telegram_user_id` (the `telegram_users` surrogate id) is a declared, mapped
    moderator right now — `is_active` is deliberately not checked: it gates availability for new
    *assignments* only (FR-030), not this flag (`contracts/message-derivation.md` §5)."""
    result = await session.execute(
        sa.select(sa.literal(True))
        .select_from(moderators)
        .where(moderators.c.telegram_user_id == telegram_user_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def derive_message(
    session_factory: async_sessionmaker[AsyncSession], *, update_row_id: int
) -> int | None:
    """Derives one `telegram_messages` row from the captured `message` event at
    `telegram_updates.id == update_row_id` — INSERT-ONLY (`contracts/message-derivation.md`
    §2(a)): `ON CONFLICT (telegram_chat_id, message_id) DO NOTHING RETURNING id`. Never
    `DO UPDATE`, for any field (D-TG-49) — an existing row is left entirely alone, which is what
    makes this idempotent and keeps `is_from_moderator` write-once.

    Gated on the chat's `is_monitored` (`contracts/message-derivation.md` §6): an unmeasured
    chat produces no message row and no sender identity. Capture is unconditional and
    derivation is opt-in — the caller still marks the captured event handled either way.

    Returns the inserted row's id, or `None` when the row already existed or the chat is not
    measured.
    """
    async with session_factory() as session:
        update_row = await _fetch_update(session, update_row_id)
        body: dict[str, Any] = update_row["payload"].get(update_row["update_type"]) or {}

        chat_pk, is_monitored = await _chat_surrogate_and_monitored(
            session, update_row["chat_id"]
        )
        if not is_monitored:
            return None

        sent_at = datetime.fromtimestamp(body["date"], tz=UTC)

        from_user = body.get("from")
        telegram_user_id: int | None = None
        is_from_moderator = False
        if isinstance(from_user, dict):
            is_bot = bool(from_user.get("is_bot", False))
            telegram_user_id = await upsert_identity(
                session,
                tg_user_id=from_user["id"],
                username=from_user.get("username"),
                display_name=_display_name_for(from_user),
                is_bot=is_bot,
                observed_at=sent_at,
            )
            # is_from_moderator is resolved here, at insert, and never recomputed (FR-032,
            # FR-033, D-TG-49/D-TG-60): a bot sender is always false, whatever the mapping says.
            if not is_bot:
                is_from_moderator = await _is_declared_moderator(
                    session, telegram_user_id=telegram_user_id
                )

        sender_chat = body.get("sender_chat")
        sender_chat_id = sender_chat.get("id") if isinstance(sender_chat, dict) else None

        reply_to = body.get("reply_to_message")
        reply_to_message_id = reply_to.get("message_id") if isinstance(reply_to, dict) else None

        original_text, normalized_text = _text_and_normalized(body)

        insert_stmt = (
            pg_insert(telegram_messages)
            .values(
                telegram_chat_id=chat_pk,
                message_id=body["message_id"],
                telegram_user_id=telegram_user_id,
                sender_chat_id=sender_chat_id,
                sent_at=sent_at,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=body.get("message_thread_id"),
                is_service=_is_service(body),
                is_from_moderator=is_from_moderator,
                original_text=original_text,
                normalized_text=normalized_text,
                media_kind=_media_kind(body),
                entity_flags=_entity_flags(body),
                source_update_id=update_row_id,
            )
            .on_conflict_do_nothing(constraint="uq_telegram_messages_chat_msg")
            .returning(telegram_messages.c.id)
        )
        result = await session.execute(insert_stmt)
        inserted_id = result.scalar_one_or_none()
        await session.commit()

    # Scheduled only for a newly-inserted, non-moderator message from a real person (TG-M3,
    # T029, contract §1) — after the insert has committed, so the delayed judgement can always
    # see the row it was scheduled for (mirrors `store_batch`'s D-TG-36). A duplicate delivery
    # (`inserted_id is None`) and a moderator's or a sender_chat's message schedule nothing: the
    # burst key needs a real `telegram_user_id`, and a moderator's own words never open an item.
    if inserted_id is not None and not is_from_moderator and telegram_user_id is not None:
        settings = load_settings()
        evaluate_attention.send_with_options(
            args=(chat_pk, telegram_user_id, body.get("message_thread_id"), sent_at.timestamp()),
            delay=settings.moderation_burst_gap_s * 1000,
        )
    # A moderator message closes on the live path, with no delay (T046, contract §4) — an answer
    # should never wait for a settle window that judgement needs and matching does not.
    elif inserted_id is not None and is_from_moderator:
        match_response.send(inserted_id)

    return inserted_id


async def group_history_chat_ids(session: AsyncSession, *, telegram_chat_id: int) -> list[int]:
    """Every surrogate `telegram_chats.id` belonging to one group's continuous history: the given
    chat plus every chat reachable from it by following `migrated_from_chat_id` /
    `migrated_to_chat_id`, in either direction (`data-model.md` §4.3, D-TG-55, FR-053).

    Messages are never re-pointed across a migration — moving them would mutate immutable derived
    rows, and the platform's own message numbering can collide either side of a promotion. "One
    group's continuous history" is therefore this read-side union over the link columns `0003`
    already stores, not a stored fact.
    """
    seen: set[int] = set()
    pending = [telegram_chat_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        row = (
            await session.execute(
                sa.select(
                    telegram_chats.c.migrated_from_chat_id, telegram_chats.c.migrated_to_chat_id
                ).where(telegram_chats.c.id == current)
            )
        ).one()
        for linked_chat_id in (row.migrated_from_chat_id, row.migrated_to_chat_id):
            if linked_chat_id is None:
                continue
            linked_pk = (
                await session.execute(
                    sa.select(telegram_chats.c.id).where(
                        telegram_chats.c.chat_id == linked_chat_id
                    )
                )
            ).scalar_one_or_none()
            if linked_pk is not None:
                pending.append(linked_pk)
    return list(seen)


async def apply_edit(
    session_factory: async_sessionmaker[AsyncSession], *, update_row_id: int
) -> int:
    """Applies the captured `edited_message` event at `telegram_updates.id == update_row_id` as a
    targeted `UPDATE … SET original_text, normalized_text, edited_at` — and nothing else
    (`contracts/message-derivation.md` §2(b), D-TG-50). `sent_at`, `is_from_moderator`,
    `telegram_user_id` and `source_update_id` are untouched.

    Also clears `attention_evaluated_at` (`contracts/attention-rules.md` §3 E5, D-TG-88): this is
    the *only* mechanism that re-triggers judgement on an edit — the ordinary sweep
    (`sweep_unjudged_bursts`) picks the row up from its own authoritative work list and re-judges
    the burst through `open_item`, exactly as it would for any other unjudged message. One
    judgement path, not two.

    Returns the number of rows matched — `0` when the message was never derived (it predates
    measurement, or its `payload` was purged), which is a no-op, not an error.
    """
    async with session_factory() as session:
        update_row = await _fetch_update(session, update_row_id)
        body: dict[str, Any] = update_row["payload"].get(update_row["update_type"]) or {}

        chat_pk = await _chat_surrogate(session, update_row["chat_id"])
        original_text, normalized_text = _text_and_normalized(body)
        edited_at = datetime.fromtimestamp(body["date"], tz=UTC)

        result = await session.execute(
            telegram_messages.update()
            .where(
                telegram_messages.c.telegram_chat_id == chat_pk,
                telegram_messages.c.message_id == body["message_id"],
            )
            .values(
                original_text=original_text,
                normalized_text=normalized_text,
                edited_at=edited_at,
                attention_evaluated_at=None,
            )
        )
        await session.commit()
        rows_matched: int = result.rowcount  # type: ignore[attr-defined]
        return rows_matched
