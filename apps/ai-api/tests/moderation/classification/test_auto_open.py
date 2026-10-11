"""T054 (US4) — a confident, consistent live prediction opens one incident on its own, in the same
transaction as the prediction, through `insert_incident` (`contracts/classification-pipeline.md`
§7 A1-A6, FR-034...FR-040, SC-002, SC-017). An operator who got there first wins (R12); a catch-up
prediction never opens anything (C2); the incident's state and figures are TG-M4's own — read here,
never recomputed.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.application.moderation.metrics import (
    detection_latency_stats,
    incident_outcome_stats,
    incident_timing_stats,
)
from app.infrastructure.models_moderation import message_classifications, moderation_incidents
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)

_CONFIDENT_VIOLATION = {
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "high",
    "confidence": 0.93,
}


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _fetch_prediction(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> dict[str, Any] | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(message_classifications).where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == message_id,
                )
            )
        ).mappings().one_or_none()
        return dict(row) if row is not None else None


async def test_confident_consistent_prediction_opens_one_incident_with_full_provenance(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fetch_incident: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    moderator = await insert_moderator(display_name="Owner")
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=moderator["moderator_id"],
        valid_from=_SENT_AT - timedelta(days=1),
    )
    user_pk = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text="اعلان عن كورس تاني بسعر مخفض جدا انضموا الآن",
    )
    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    assert outcome == "classified"
    assert len(calls) == 1

    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is not None
    assert prediction["route"] == "incident"

    incident = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert incident is not None
    assert incident["source"] == "ai"
    assert incident["opened_by_user_id"] is None
    assert incident["message_classification_id"] == prediction["id"]
    assert incident["prompted_by_classification_id"] is None
    assert incident["category"] == prediction["category"]
    assert incident["severity"] == prediction["severity"]
    assert incident["opened_at"] == _SENT_AT
    # A1: the prediction and the incident are inserted in one transaction, so `detected_at` and
    # the prediction's own `created_at` read the identical `now()` value (Postgres'
    # `transaction_timestamp()`).
    assert incident["detected_at"] == prediction["created_at"]
    assert incident["responsible_moderator_id"] == moderator["moderator_id"]


async def test_no_owner_at_detection_is_null_and_unmoved_by_a_later_handover(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fetch_incident: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="اعلان عن كورس تاني بسعر مخفض جدا انضموا الآن",
    )
    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    assert outcome == "classified"
    assert len(calls) == 1

    incident = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert incident is not None
    assert incident["responsible_moderator_id"] is None

    # A later assignment must never move an already-flagged incident's attribution.
    late_owner = await insert_moderator(display_name="Late Owner")
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=late_owner["moderator_id"],
        valid_from=incident["detected_at"],
    )

    unmoved = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert unmoved["responsible_moderator_id"] is None


async def test_an_operator_incident_already_on_the_message_blocks_a_second_one(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fetch_incident: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="اعلان عن كورس تاني بسعر مخفض جدا انضموا الآن",
    )
    operator_incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_SENT_AT,
        detected_at=_SENT_AT + timedelta(minutes=1),
        category="SPAM_OR_AD",
        severity="low",
        source="operator",
        opened_by_user_id=7,
    )
    before = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)

    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    assert outcome == "classified"
    assert len(calls) == 1

    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is not None
    assert prediction["route"] == "incident"

    after = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert after == before
    assert after["id"] == operator_incident_id
    assert after["source"] == "operator"

    async with classification_session_factory() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderation_incidents)
                .where(
                    moderation_incidents.c.telegram_chat_id == chat_pk,
                    moderation_incidents.c.telegram_message_id == 1,
                )
            )
        ).scalar_one()
    assert count == 1


async def test_a_catch_up_prediction_with_the_same_values_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fetch_incident: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="اعلان عن كورس تاني بسعر مخفض جدا انضموا الآن",
    )
    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="catch_up",
    )
    assert outcome == "classified"
    assert len(calls) == 1

    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is not None
    assert prediction["route"] == "measurement_only"
    assert prediction["path"] == "catch_up"

    assert await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1) is None


async def test_closing_a_model_opened_incident_false_positive_removes_it_from_figures(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_action: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fetch_incident: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="اعلان عن كورس تاني بسعر مخفض جدا انضموا الآن",
    )
    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    assert outcome == "classified"
    assert len(calls) == 1

    incident = await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1)
    assert incident is not None
    detected_at = incident["detected_at"]

    period_from = detected_at - timedelta(days=1)
    period_to = detected_at + timedelta(days=1)

    # Acknowledged (but not yet resolved) so it shows up in `within_window` and in the
    # acknowledgement timing figure before it is closed.
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_acknowledge",
        action_strength="acknowledgement",
        occurred_at=detected_at + timedelta(minutes=5),
        panel_user_id=1,
        moderation_incident_id=incident["id"],
    )

    async with classification_session_factory() as session:
        outcome_before = await incident_outcome_stats(
            session, period_from=period_from, period_to=period_to, max_age_s=86_400, chat_id=chat_pk
        )
        timing_before = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
        latency_before = await detection_latency_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
    assert outcome_before["flagged"] == 1
    assert outcome_before["false_positive"] == 0
    assert outcome_before["within_window"] == 1
    assert timing_before["acknowledgement"]["samples"] == 1
    # TG-M5, D-TG-159: detection latency is grouped by opener — a model-opened incident is the
    # `'ai'` block.
    assert latency_before["ai"]["flagged"] == 1

    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        occurred_at=detected_at + timedelta(minutes=10),
        panel_user_id=1,
        moderation_incident_id=incident["id"],
        note="model misread an announcement as an advert",
    )

    async with classification_session_factory() as session:
        outcome_after = await incident_outcome_stats(
            session, period_from=period_from, period_to=period_to, max_age_s=86_400, chat_id=chat_pk
        )
        timing_after = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
        latency_after = await detection_latency_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
    assert outcome_after["flagged"] == 1
    assert outcome_after["false_positive"] == 1
    assert outcome_after["within_window"] == 0
    assert outcome_after["handled"] == 0
    assert outcome_after["missed"] == 0
    assert timing_after["acknowledgement"]["samples"] == 0
    # M17: detection latency is a figure about the system — a false positive still counts.
    assert latency_after["ai"]["flagged"] == 1
