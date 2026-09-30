"""T055 (US4) — across every route and value combination, a prediction never opens, dismisses,
expires or otherwise alters a question item, never writes a `moderation_actions` row, and never
moves an already-existing incident's derived state; no attention item is ever created with
`source='ai'` (`contracts/classification-pipeline.md` §11 N1-N2, FR-032, FR-033, SC-014).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.infrastructure.models_moderation import attention_items, moderation_actions
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 3, 5, 9, 0, 0, tzinfo=UTC)

# One scripted answer per distinct route (`route_prediction`, R1-R6), so every route this
# milestone defines is exercised at least once against a message that already anchors an
# attention item or an incident.
_REVIEW = {  # R2 — below the floor.
    "category": "OTHER",
    "needs_response": False,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.30,
}
_INCONSISTENT_FORWARD = {  # R3 — needs moderation, but a category that never is one.
    "category": "CHITCHAT",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "medium",
    "confidence": 0.90,
}
_UNCERTAIN = {  # R6 — consistent, needs moderation, below the incident threshold.
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "low",
    "confidence": 0.70,
}
_NONE_ROUTE = {  # R4 — consistent, needs no moderation.
    "category": "CHITCHAT",
    "needs_response": False,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.90,
}
_CONFIDENT_VIOLATION = {  # R5 — would open an incident, if the message anchors none yet.
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "high",
    "confidence": 0.95,
}
_INCONSISTENT_REVERSE = {  # R3 — a violation category marked as needing no moderation.
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.90,
}


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _snapshot_attention(
    session_factory: async_sessionmaker[AsyncSession], *, item_ids: list[int]
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(attention_items)
                .where(attention_items.c.id.in_(item_ids))
                .order_by(attention_items.c.id)
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def _snapshot_actions(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(moderation_actions)
                .where(moderation_actions.c.telegram_chat_id == chat_pk)
                .order_by(moderation_actions.c.id)
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def test_across_every_route_nothing_moves_an_attention_item_action_or_incident(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_attention_item: Any,
    insert_incident: Any,
    insert_action: Any,
    read_incident_state: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)

    # Three messages, each already anchoring a question item in a different state.
    for message_id in (1, 2, 3):
        await insert_message(
            telegram_chat_id=chat_pk,
            message_id=message_id,
            sent_at=_SENT_AT,
            original_text="رسالة عن الكورس اليوم",
        )
    open_item_id = await insert_attention_item(
        telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=_SENT_AT, status="open"
    )
    answered_item_id = await insert_attention_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=2,
        opened_at=_SENT_AT,
        status="answered",
        first_response_message_id=999,
        first_response_at=_SENT_AT + timedelta(minutes=1),
        first_response_kind="group_message",
    )
    expired_item_id = await insert_attention_item(
        telegram_chat_id=chat_pk, telegram_message_id=3, opened_at=_SENT_AT, status="expired"
    )

    # Four messages, each already anchoring an operator incident in a different state.
    for message_id in (4, 5, 6, 7):
        await insert_message(
            telegram_chat_id=chat_pk,
            message_id=message_id,
            sent_at=_SENT_AT,
            original_text="رسالة عن الكورس اليوم",
        )
    open_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=4,
        opened_at=_SENT_AT,
        detected_at=_SENT_AT + timedelta(minutes=1),
        category="SPAM_OR_AD",
        severity="low",
    )
    acknowledged_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=5,
        opened_at=_SENT_AT,
        detected_at=_SENT_AT + timedelta(minutes=1),
        category="SPAM_OR_AD",
        severity="low",
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_acknowledge",
        action_strength="acknowledgement",
        occurred_at=_SENT_AT + timedelta(minutes=2),
        panel_user_id=1,
        moderation_incident_id=acknowledged_incident_id,
    )
    resolved_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=6,
        opened_at=_SENT_AT,
        detected_at=_SENT_AT + timedelta(minutes=1),
        category="ABUSE",
        severity="medium",
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_resolve",
        action_strength="confirmation",
        occurred_at=_SENT_AT + timedelta(minutes=2),
        panel_user_id=1,
        moderation_incident_id=resolved_incident_id,
        note="handled",
    )
    false_positive_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=7,
        opened_at=_SENT_AT,
        detected_at=_SENT_AT + timedelta(minutes=1),
        category="SPAM_OR_AD",
        severity="low",
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        occurred_at=_SENT_AT + timedelta(minutes=2),
        panel_user_id=1,
        moderation_incident_id=false_positive_incident_id,
        note="not a violation",
    )

    attention_item_ids = [open_item_id, answered_item_id, expired_item_id]
    incident_ids = [
        open_incident_id,
        acknowledged_incident_id,
        resolved_incident_id,
        false_positive_incident_id,
    ]

    attention_before = await _snapshot_attention(
        classification_session_factory, item_ids=attention_item_ids
    )
    states_before = {
        incident_id: await read_incident_state(incident_id) for incident_id in incident_ids
    }
    actions_before = await _snapshot_actions(classification_session_factory, chat_pk=chat_pk)

    registry = ProfileRegistry(classification_session_factory)
    scripts = [
        (1, _REVIEW),
        (2, _INCONSISTENT_FORWARD),
        (3, _UNCERTAIN),
        (4, {**_NONE_ROUTE}),
        # Would route `incident`, but message 5 already anchors one — R12 blocks a second.
        (5, _CONFIDENT_VIOLATION),
        (6, _INCONSISTENT_REVERSE),
        (7, _REVIEW),
    ]
    gateway, calls = scripted_gateway(responses=[dict(answer) for _, answer in scripts])

    for message_id, _ in scripts:
        outcome = await classify_one(
            classification_session_factory,
            gateway,
            registry,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path="live",
        )
        assert outcome == "classified"
    assert len(calls) == len(scripts)

    attention_after = await _snapshot_attention(
        classification_session_factory, item_ids=attention_item_ids
    )
    assert attention_after == attention_before

    for incident_id in incident_ids:
        assert await read_incident_state(incident_id) == states_before[incident_id]

    actions_after = await _snapshot_actions(classification_session_factory, chat_pk=chat_pk)
    assert actions_after == actions_before

    async with classification_session_factory() as session:
        ai_opened_attention_items = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(attention_items)
                .where(
                    attention_items.c.telegram_chat_id == chat_pk,
                    attention_items.c.source == "ai",
                )
            )
        ).scalar_one()
    assert ai_opened_attention_items == 0
