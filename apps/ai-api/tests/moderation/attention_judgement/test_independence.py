"""T031 — the two judgements are independent (`specs/011-tg-m5-3-attention-judgement/contracts/
attention-judgement.md` §1 J4, §7 W4, §8 F3, §10 N5; FR-314).

- With no active moderation profile, or with every moderation call failing, `judge_one` still
  records its judgement.
- With no active attention profile, or with every attention call failing, `classify_one` still
  records the same prediction it records when the attention side works.
- The two claim keys differ (`ai:mod:classify:msg` and `ai:mod:attention:msg`), so a claim held by
  one task never blocks the other.

Opening (V, read by `open_item`) is the only place the two meet; it is US3's
(`test_opening.py`).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.gateway import StructuredOutputInvalidError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.attention_judgement import judge_one
from app.application.moderation.classification import classify_one
from app.infrastructure.models_moderation import (
    message_attention_judgements,
    message_classifications,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 10, 4, 9, 0, 0, tzinfo=UTC)
_TEXT = "بس الرابط بايظ"  # rule-declined
_INSTRUCTIONS = {"attention_test": "TEST"}

_CLASSIFICATION_ANSWER = {
    "category": "QUESTION_ACCESS",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.9,
}
_PREDICTION_FIELDS = (
    "category",
    "needs_response",
    "needs_moderation",
    "severity",
    "confidence",
    "route",
    "route_reason",
    "prompt_version",
)


def _settings(classification_settings: Any) -> Any:
    return classification_settings.model_copy(
        update={"moderation_attention_prompt_version": "attention_test"}
    )


async def _messages(
    insert_chat: Any, insert_user: Any, insert_message: Any, *, chat_id: int, count: int
) -> int:
    chat_pk = await insert_chat(chat_id=chat_id)
    user_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    for message_id in range(1, count + 1):
        await insert_message(
            telegram_chat_id=chat_pk,
            message_id=message_id,
            sent_at=_SENT_AT,
            telegram_user_id=user_pk,
            original_text=_TEXT,
        )
    return chat_pk


async def _judge(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int,
) -> str:
    return await judge_one(
        session_factory,
        gateway,
        ProfileRegistry(session_factory),
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        instructions=_INSTRUCTIONS,
    )


async def _classify(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int,
) -> str:
    return await classify_one(
        session_factory,
        gateway,
        ProfileRegistry(session_factory),
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        path="live",
    )


async def _intent(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> str | None:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(message_attention_judgements.c.intent).where(
                    message_attention_judgements.c.telegram_chat_id == chat_pk,
                    message_attention_judgements.c.telegram_message_id == message_id,
                    message_attention_judgements.c.is_current,
                )
            )
        ).scalar_one_or_none()


async def _prediction(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> tuple[Any, ...] | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(*(message_classifications.c[f] for f in _PREDICTION_FIELDS)).where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == message_id,
                    message_classifications.c.is_current,
                )
            )
        ).one_or_none()
        return tuple(row) if row is not None else None


async def _deactivate(session_factory: async_sessionmaker[AsyncSession], role: str) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.text("UPDATE model_profiles SET is_active = false WHERE role = :role"),
            {"role": role},
        )
        await session.commit()


async def test_the_attention_judgement_records_with_the_moderation_side_failing_or_absent(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await _messages(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id, count=2
    )
    await seeded_attention_profile(active=True)
    settings = _settings(classification_settings)

    # Message 1: every moderation call fails, before and after the attention judgement.
    failing, _ = scripted_gateway(fail_with=StructuredOutputInvalidError)
    working, _ = scripted_gateway(responses=[{"intent": "asking"}, {"intent": "asking"}])
    assert (
        await _classify(
            classification_session_factory,
            failing,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=1,
        )
        == "failed"
    )
    assert (
        await _judge(
            classification_session_factory,
            working,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=1,
        )
        == "judged"
    )

    # Message 2: no active moderation profile at all.
    await _deactivate(classification_session_factory, "moderation")
    assert (
        await _classify(
            classification_session_factory,
            failing,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=2,
        )
        == "no_active_model"
    )
    assert (
        await _judge(
            classification_session_factory,
            working,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=2,
        )
        == "judged"
    )

    for message_id in (1, 2):
        assert (
            await _intent(classification_session_factory, chat_pk=chat_pk, message_id=message_id)
            == "asking"
        )


async def test_the_classification_is_the_same_with_the_attention_side_failing_or_absent(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """Message 1 is the reference (attention works), message 2 has every attention call failing,
    and message 3 has no active attention profile. The three predictions are equal."""
    chat_pk = await _messages(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id, count=3
    )
    await seeded_attention_profile(active=True)
    settings = _settings(classification_settings)
    classifier, _ = scripted_gateway(responses=[dict(_CLASSIFICATION_ANSWER) for _ in range(3)])
    attention_working, _ = scripted_gateway(responses=[{"intent": "asking"}])
    attention_failing, _ = scripted_gateway(fail_with=StructuredOutputInvalidError)

    assert (
        await _judge(
            classification_session_factory,
            attention_working,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=1,
        )
        == "judged"
    )
    assert (
        await _judge(
            classification_session_factory,
            attention_failing,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=2,
        )
        == "failed"
    )
    await _deactivate(classification_session_factory, "attention")
    assert (
        await _judge(
            classification_session_factory,
            attention_working,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=3,
        )
        == "no_active_model"
    )

    for message_id in (1, 2, 3):
        assert (
            await _classify(
                classification_session_factory,
                classifier,
                classification_redis,
                settings,
                chat_pk=chat_pk,
                message_id=message_id,
            )
            == "classified"
        )

    reference = await _prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert reference is not None
    for message_id in (2, 3):
        assert (
            await _prediction(
                classification_session_factory, chat_pk=chat_pk, message_id=message_id
            )
            == reference
        )


async def test_a_claim_held_by_one_task_never_blocks_the_other(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """W4: each task claims under its own prefix."""
    chat_pk = await _messages(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id, count=1
    )
    await seeded_attention_profile(active=True)
    settings = _settings(classification_settings)
    classify_lock_name = f"ai:mod:classify:msg:{chat_pk}:1"
    attention_lock_name = f"ai:mod:attention:msg:{chat_pk}:1"
    attention_gateway, _ = scripted_gateway(responses=[{"intent": "asking"}])
    classifier, _ = scripted_gateway(responses=[dict(_CLASSIFICATION_ANSWER)])

    await classification_redis.set(classify_lock_name, "classifier-elsewhere", px=60_000)
    try:
        judged = await _judge(
            classification_session_factory,
            attention_gateway,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=1,
        )
    finally:
        await classification_redis.delete(classify_lock_name)

    await classification_redis.set(attention_lock_name, "attention-elsewhere", px=60_000)
    try:
        classified = await _classify(
            classification_session_factory,
            classifier,
            classification_redis,
            settings,
            chat_pk=chat_pk,
            message_id=1,
        )
    finally:
        await classification_redis.delete(attention_lock_name)

    assert (judged, classified) == ("judged", "classified")
