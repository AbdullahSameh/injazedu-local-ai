"""D-TG-163 — `MODERATION_PROMPT_VERSION` chooses the instruction and nothing else: with
`classify_v2` configured the provider receives exactly `[system = classify_v2.md, user = the
redacted text]`, the prediction records `prompt_version = "classify_v2"`, routing and the incident
it opens are unchanged, and a catch-up prediction under v2 is still measurement only. The default
(`classify_v1`) is covered, unchanged, by `test_classify_one.py` and `test_model_input.py`
(`contracts/classification-pipeline.md` §2a, P3, O5, R1, A1).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.application.moderation.text import normalize, redact
from app.infrastructure.models_moderation import message_classifications, moderation_incidents
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 9, 9, 0, 0, tzinfo=UTC)

_V2_PATH = Path(__file__).resolve().parents[3] / "app" / "prompts" / "moderation" / "classify_v2.md"
_V2_INSTRUCTION = _V2_PATH.read_text(encoding="utf-8")

_TEXT = "هلا والله نورتوا 🌹 عندنا دورات بخصم، للتسجيل واتساب 0500000009"

_ADVERT_ANSWER = {
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "medium",
    "confidence": 0.95,
}


async def _fetch_prediction(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    sa.select(message_classifications).where(
                        message_classifications.c.telegram_chat_id == chat_pk,
                        message_classifications.c.telegram_message_id == message_id,
                    )
                )
            )
            .mappings()
            .one()
        )
        return dict(row)


async def _count_incidents(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(moderation_incidents)
                    .where(
                        moderation_incidents.c.telegram_chat_id == chat_pk,
                        moderation_incidents.c.telegram_message_id == message_id,
                    )
                )
            ).scalar_one()
        )


async def test_classify_v2_is_sent_and_recorded_and_routes_as_before(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    user_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text=_TEXT,
    )
    gateway, calls = scripted_gateway(responses=[dict(_ADVERT_ANSWER)])
    settings = classification_settings.model_copy(
        update={"moderation_prompt_version": "classify_v2"}
    )

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        ProfileRegistry(classification_session_factory),
        classification_redis,
        settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )

    assert outcome == "classified"
    assert len(calls) == 1
    system_message, user_message = calls[0].messages
    assert system_message.role == "system"
    assert system_message.content == _V2_INSTRUCTION
    assert user_message.role == "user"
    assert user_message.content == redact(normalize(_TEXT))
    assert "0500000009" not in user_message.content

    row = await _fetch_prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert row["prompt_version"] == "classify_v2"
    assert row["taxonomy_version"] == 1
    assert row["route"] == "incident"
    assert (
        await _count_incidents(classification_session_factory, chat_pk=chat_pk, message_id=1) == 1
    )


async def test_a_catch_up_prediction_under_v2_is_still_measurement_only(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    user_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text=_TEXT,
    )
    gateway, calls = scripted_gateway(responses=[dict(_ADVERT_ANSWER)])
    settings = classification_settings.model_copy(
        update={"moderation_prompt_version": "classify_v2"}
    )

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        ProfileRegistry(classification_session_factory),
        classification_redis,
        settings,
        chat_pk=chat_pk,
        message_id=1,
        path="catch_up",
    )

    assert outcome == "classified"
    assert calls[0].messages[0].content == _V2_INSTRUCTION
    row = await _fetch_prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert row["prompt_version"] == "classify_v2"
    assert row["route"] == "measurement_only"
    assert (
        await _count_incidents(classification_session_factory, chat_pk=chat_pk, message_id=1) == 0
    )
