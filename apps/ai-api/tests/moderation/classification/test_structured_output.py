"""T031 — the gateway boundary: a scripted valid answer becomes a prediction; a cut-off or
malformed answer becomes one `failed` row naming the kind, called exactly once, never retried by
the classifier's own gateway (`max_retries=0`); an out-of-range confidence is a recorded failure,
never clamped; an inconsistent combination is stored verbatim
(`contracts/classification-pipeline.md` §5 O3, §8 F3, FR-012, FR-014, FR-023, SC-004).

⚠ Finding 6: a default gateway (`max_retries=2`) calls the provider three times for a cut-off
answer — only asserting the call count catches a classifier gateway that was built without
`max_retries=0`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway import ModelTruncatedError, StructuredOutputInvalidError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 2, 9, 0, 0, tzinfo=UTC)


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


async def _fetch_failures(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(message_classification_attempts).where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id == message_id,
                    message_classification_attempts.c.outcome == "failed",
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def _make_message(
    insert_chat: Any, insert_message: Any, classification_chat_id: int, message_id: int
) -> int:
    chat_pk = await insert_chat(chat_id=classification_chat_id - message_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=message_id,
        sent_at=_SENT_AT,
        original_text="سؤال عن موعد الاختبار القادم",
    )
    return chat_pk


@pytest.mark.parametrize(
    ("fail_with", "expected_reason"),
    [
        (ModelTruncatedError, "model_truncated"),
        (StructuredOutputInvalidError, "structured_output_invalid"),
    ],
)
async def test_final_gateway_failure_is_recorded_once_never_retried(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    fail_with: type[Exception],
    expected_reason: str,
) -> None:
    chat_pk = await _make_message(insert_chat, insert_message, classification_chat_id, 1)
    gateway, calls = scripted_gateway(fail_with=fail_with)
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

    assert outcome == "failed"
    assert len(calls) == 1
    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is None
    failures = await _fetch_failures(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert len(failures) == 1
    assert failures[0]["reason"] == expected_reason
    assert failures[0]["model_profile_id"] is not None


@pytest.mark.parametrize("bad_confidence", [1.3, -0.1])
async def test_out_of_range_confidence_is_a_failure_never_clamped(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    bad_confidence: float,
) -> None:
    chat_pk = await _make_message(insert_chat, insert_message, classification_chat_id, 1)
    gateway, calls = scripted_gateway(
        responses=[
            {
                "category": "QUESTION_COURSE",
                "needs_response": True,
                "needs_moderation": False,
                "severity": "none",
                "confidence": bad_confidence,
            }
        ]
    )
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

    assert outcome == "failed"
    assert len(calls) == 1
    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is None
    failures = await _fetch_failures(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert len(failures) == 1
    assert failures[0]["reason"] == "confidence_out_of_range"


async def test_inconsistent_combination_is_stored_verbatim(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await _make_message(insert_chat, insert_message, classification_chat_id, 1)
    # An advert marked `needs_moderation=False` — R8's reverse-direction inconsistency (operator
    # item 4): the literal category/flag combination is never "fixed", only routed.
    gateway, calls = scripted_gateway(
        responses=[
            {
                "category": "SPAM_OR_AD",
                "needs_response": False,
                "needs_moderation": False,
                "severity": "none",
                "confidence": 0.95,
            }
        ]
    )
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
    row = await _fetch_prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert row is not None
    assert row["category"] == "SPAM_OR_AD"
    assert row["needs_moderation"] is False
    assert row["confidence"] == Decimal("0.950")
    assert row["route"] == "possible_violation"
    assert row["route_reason"] == "inconsistent"
