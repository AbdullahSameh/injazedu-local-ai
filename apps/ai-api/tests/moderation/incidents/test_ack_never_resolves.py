"""**The milestone's acceptance** (T033, FR-023, SC-002): no combination of acknowledgement rows
— a moderator's reply, a moderator's reaction, a panel acknowledgement, any number of them, in any
mix — ever reads as `resolved`. `no acknowledgement kind carries a resolving strength`
(`ck_actions_strength`) makes this true by construction; this test proves the *view* honours it
for every combination up to four rows, and for twenty in a row.
"""

from __future__ import annotations

import itertools
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 1, 12, 8, 0, 0, tzinfo=UTC)
_DETECTED_AT = datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC)

_KINDS = ("reply", "reaction", "panel_acknowledge")


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _new_incident(
    insert_chat: Any, insert_message: Any, insert_incident: Any
) -> tuple[int, int]:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_OPENED_AT)
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_OPENED_AT,
        detected_at=_DETECTED_AT,
        category="SPAM_OR_AD",
        severity="low",
    )
    return chat_pk, incident_id


async def _add_ack(
    kind: str,
    *,
    chat_pk: int,
    incident_id: int,
    moment: datetime,
    reply_message_id: int,
    mod: dict[str, int],
    insert_message: Any,
    insert_action: Any,
    captured_update: Any,
) -> None:
    if kind == "reply":
        await insert_message(
            telegram_chat_id=chat_pk,
            message_id=reply_message_id,
            sent_at=moment,
            telegram_user_id=mod["telegram_user_id"],
            is_from_moderator=True,
            reply_to_message_id=1,
        )
    elif kind == "reaction":
        update_row_id = await captured_update("message_reaction", {}, chat_id=None)
        await insert_action(
            telegram_chat_id=chat_pk,
            action_type="reaction",
            action_strength="acknowledgement",
            occurred_at=moment,
            actor_telegram_user_id=mod["telegram_user_id"],
            actor_moderator_id=mod["moderator_id"],
            target_message_id=1,
            source_update_id=update_row_id,
        )
    elif kind == "panel_acknowledge":
        await insert_action(
            telegram_chat_id=chat_pk,
            action_type="panel_acknowledge",
            action_strength="acknowledgement",
            occurred_at=moment,
            panel_user_id=1,
            moderation_incident_id=incident_id,
        )
    else:
        raise AssertionError(f"unknown kind: {kind!r}")


def _combinations() -> list[tuple[str, ...]]:
    combos: list[tuple[str, ...]] = []
    for size in range(1, 5):
        combos.extend(itertools.combinations_with_replacement(_KINDS, size))
    return combos


async def test_every_combination_of_up_to_four_acknowledgements_stays_acknowledged(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    read_state: Any,
) -> None:
    for combo in _combinations():
        chat_pk, incident_id = await _new_incident(insert_chat, insert_message, insert_incident)
        mod = await insert_moderator()
        for index, kind in enumerate(combo, start=2):
            await _add_ack(
                kind,
                chat_pk=chat_pk,
                incident_id=incident_id,
                moment=_OPENED_AT + timedelta(minutes=index),
                reply_message_id=index,
                mod=mod,
                insert_message=insert_message,
                insert_action=insert_action,
                captured_update=captured_update,
            )

        state = await read_state(incident_id)
        assert state["status"] == "acknowledged", combo
        assert state["resolved_at"] is None, combo


async def test_twenty_acknowledgements_in_a_row_stays_acknowledged(
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

    for index in range(20):
        kind = _KINDS[index % len(_KINDS)]
        await _add_ack(
            kind,
            chat_pk=chat_pk,
            incident_id=incident_id,
            moment=_OPENED_AT + timedelta(minutes=index + 2),
            reply_message_id=index + 2,
            mod=mod,
            insert_message=insert_message,
            insert_action=insert_action,
            captured_update=captured_update,
        )

    state = await read_state(incident_id)
    assert state["status"] == "acknowledged"
    assert state["resolved_at"] is None
