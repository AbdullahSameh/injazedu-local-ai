"""T032 — idempotency and concurrency (`contracts/classification-pipeline.md` §9 I1-I3): the same
message classified three times produces one prediction and one provider call; a claim already
held for the message ends the second attempt without calling the provider or writing anything; an
excluded message classified twice produces one exclusion row (FR-005, SC-007).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import _CLAIM_PREFIX, classify_one
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 3, 9, 0, 0, tzinfo=UTC)

_VALID_ANSWER = {
    "category": "QUESTION_COURSE",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.93,
}


async def _count_predictions(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(message_classifications)
                .where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == message_id,
                )
            )
        ).scalar_one()


async def _count_attempts(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(message_classification_attempts)
                .where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id == message_id,
                )
            )
        ).scalar_one()


async def test_classifying_the_same_message_three_times_calls_the_provider_once(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="سؤال عن الجدول",
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    registry = ProfileRegistry(classification_session_factory)

    outcomes = []
    for _ in range(3):
        outcomes.append(
            await classify_one(
                classification_session_factory,
                gateway,
                registry,
                classification_redis,
                classification_settings,
                chat_pk=chat_pk,
                message_id=1,
                path="live",
            )
        )

    assert outcomes[0] == "classified"
    assert outcomes[1] == "already_classified"
    assert outcomes[2] == "already_classified"
    assert len(calls) == 1
    count = await _count_predictions(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert count == 1


async def test_a_claim_already_held_ends_without_calling_the_provider_or_writing_anything(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="سؤال عن الجدول",
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    registry = ProfileRegistry(classification_session_factory)

    held_key = f"{_CLAIM_PREFIX}:{chat_pk}:1"
    await classification_redis.set(held_key, "someone-else", px=60_000, nx=True)
    try:
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
    finally:
        await classification_redis.delete(held_key)

    assert outcome == "claimed_elsewhere"
    assert len(calls) == 0
    prediction_count = await _count_predictions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    attempt_count = await _count_attempts(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction_count == 0
    assert attempt_count == 0


async def test_an_excluded_message_classified_twice_records_one_exclusion_row(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, is_service=True
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    registry = ProfileRegistry(classification_session_factory)

    first = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    second = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )

    assert first == "excluded"
    assert second == "already_classified"
    assert len(calls) == 0
    assert await _count_attempts(classification_session_factory, chat_pk=chat_pk, message_id=1) == 1
