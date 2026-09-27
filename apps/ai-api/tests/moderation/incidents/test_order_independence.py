"""Order independence (T042, lifecycle contract S5, FR-045, SC-005): the same set of evidence,
inserted in different orders, produces an identical `moderation_incident_state` row every time —
the status and every moment are aggregates over a set, which has no processing order.
"""

from __future__ import annotations

import itertools
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC)
_REACTION_AT = _OPENED_AT + timedelta(minutes=7)
_BAN_AT = _OPENED_AT + timedelta(minutes=12)
_RESOLVE_AT = _OPENED_AT + timedelta(minutes=20)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _build_and_read(
    order: tuple[str, ...],
    *,
    sender_id: int,
    mod: dict[str, int],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> dict[str, Any]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=sender_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )

    for kind in order:
        if kind == "reaction":
            update_row_id = await captured_update("message_reaction", {}, chat_id=None)
            await insert_action(
                telegram_chat_id=chat_pk,
                action_type="reaction",
                action_strength="acknowledgement",
                occurred_at=_REACTION_AT,
                actor_telegram_user_id=mod["telegram_user_id"],
                actor_moderator_id=mod["moderator_id"],
                target_message_id=1,
                source_update_id=update_row_id,
            )
        elif kind == "ban":
            update_row_id = await captured_update("chat_member", {}, chat_id=None)
            await insert_action(
                telegram_chat_id=chat_pk,
                action_type="ban",
                action_strength="enforcement",
                occurred_at=_BAN_AT,
                subject_telegram_user_id=sender_id,
                source_update_id=update_row_id,
            )
        elif kind == "panel_resolve":
            await insert_action(
                telegram_chat_id=chat_pk,
                action_type="panel_resolve",
                action_strength="confirmation",
                occurred_at=_RESOLVE_AT,
                panel_user_id=1,
                moderation_incident_id=incident_id,
                note="Confirmed",
            )
        else:
            raise AssertionError(f"unknown kind: {kind!r}")

    return await read_state(incident_id)


async def test_state_is_identical_whatever_order_evidence_was_inserted_in(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    mod = await insert_moderator()

    orders = list(itertools.permutations(("reaction", "ban", "panel_resolve")))
    results = []
    for order in orders:
        state = await _build_and_read(
            order,
            sender_id=sender_id,
            mod=mod,
            insert_chat=insert_chat,
            insert_message=insert_message,
            insert_incident=insert_incident,
            insert_action=insert_action,
            captured_update=captured_update,
            read_state=read_state,
        )
        results.append({key: value for key, value in state.items() if key != "incident_id"})

    first = results[0]
    for other, order in zip(results[1:], orders[1:], strict=True):
        assert other == first, order

    assert first["status"] == "resolved"
    assert first["first_acknowledgement_at"] == _REACTION_AT
    assert first["first_enforcement_at"] == _BAN_AT
    assert first["first_confirmation_at"] == _RESOLVE_AT
    assert first["resolved_at"] == _BAN_AT
    assert first["resolution_kind"] == "ban"


async def test_a_reaction_inserted_after_the_ban_still_sets_first_acknowledgement_at(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    sender_id = await insert_user(tg_user_id=_rand_id())
    mod = await insert_moderator()
    state = await _build_and_read(
        ("ban", "reaction"),
        sender_id=sender_id,
        mod=mod,
        insert_chat=insert_chat,
        insert_message=insert_message,
        insert_incident=insert_incident,
        insert_action=insert_action,
        captured_update=captured_update,
        read_state=read_state,
    )
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "ban"
    assert state["first_acknowledgement_at"] == _REACTION_AT
