"""T050 — with no active `moderation` profile, classifying any message — eligible or not —
writes no prediction, exclusion or failure row and calls no provider
(`contracts/classification-pipeline.md` §8 F1, FR-025, D-TG-152).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 9, 9, 0, 0, tzinfo=UTC)


async def _count_rows(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> tuple[int, int]:
    async with session_factory() as session:
        predictions = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(message_classifications)
                .where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == message_id,
                )
            )
        ).scalar_one()
        attempts = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(message_classification_attempts)
                .where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id == message_id,
                )
            )
        ).scalar_one()
        return predictions, attempts


async def test_no_active_profile_writes_nothing_for_an_eligible_message(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    # `scripted_gateway` is not requested with the seeded-profile fixture active — deactivate the
    # one `classification_seeded_profile` would otherwise leave in place, so this test proves F1
    # against a genuinely empty roster rather than one this package's own fixtures populate.
    async with classification_session_factory() as session:
        await session.execute(
            sa.text("UPDATE model_profiles SET is_active = false WHERE role = 'moderation'")
        )
        await session.commit()

    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, original_text="سؤال عادي جدا"
    )
    gateway, calls = scripted_gateway(
        responses=[
            {
                "category": "QUESTION_COURSE",
                "needs_response": True,
                "needs_moderation": False,
                "severity": "none",
                "confidence": 0.9,
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

    assert outcome == "no_active_model"
    assert len(calls) == 0
    predictions, attempts = await _count_rows(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert predictions == 0
    assert attempts == 0


async def test_no_active_profile_writes_nothing_for_a_message_that_would_otherwise_be_excluded(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    async with classification_session_factory() as session:
        await session.execute(
            sa.text("UPDATE model_profiles SET is_active = false WHERE role = 'moderation'")
        )
        await session.commit()

    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, is_service=True
    )
    gateway, calls = scripted_gateway()
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

    assert outcome == "no_active_model"
    assert len(calls) == 0
    predictions, attempts = await _count_rows(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert predictions == 0
    assert attempts == 0
