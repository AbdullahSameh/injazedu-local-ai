"""T030 — an eligible message gets exactly one immutable prediction with full provenance; each
exclusion reason gets one `excluded` row and no provider call; a bot account's and another
channel's message are still eligible (FR-003); and a later edit or an opened incident on the same
message leaves the prediction row byte-identical (`contracts/classification-pipeline.md` §5,
FR-001…FR-005, FR-011…FR-017, SC-006).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.application.moderation.incidents import open_incident
from app.application.moderation.messages import apply_edit
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
    telegram_updates,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC)

_VALID_ANSWER = {
    "category": "QUESTION_COURSE",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.93,
}


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


async def _fetch_exclusions(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(message_classification_attempts).where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id == message_id,
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def test_eligible_message_gets_one_full_prediction(
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
        original_text="متى يبدأ الفصل القادم؟",
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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
    assert row["model_profile_id"] is not None
    assert row["model_run_id"] is not None
    assert row["prompt_version"] == "classify_v1"
    assert row["taxonomy_version"] == 1
    assert row["category"] == "QUESTION_COURSE"
    assert row["needs_response"] is True
    assert row["needs_moderation"] is False
    assert row["severity"] == "none"
    assert row["confidence"] == Decimal("0.930")
    assert row["path"] == "live"
    assert row["route"] == "none"
    assert row["route_reason"] is None
    assert row["confidence_floor"] == Decimal("0.600")
    assert row["incident_threshold"] == Decimal("0.850")
    assert row["is_current"] is True


@pytest.mark.parametrize(
    ("build_kwargs", "expected_reason"),
    [
        ({"is_service": True}, "service"),
        ({"media_kind": "photo"}, "media"),
        ({"original_text": None}, "no_text"),
        ({"original_text": "شكرا"}, "acknowledgement"),
    ],
)
async def test_exclusion_reasons_record_one_row_and_call_no_provider(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    build_kwargs: dict[str, Any],
    expected_reason: str,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, **build_kwargs
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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

    assert outcome == "excluded"
    assert len(calls) == 0
    exclusions = await _fetch_exclusions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert len(exclusions) == 1
    assert exclusions[0]["outcome"] == "excluded"
    assert exclusions[0]["reason"] == expected_reason
    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is None


async def test_exclusion_moderator(
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
        is_from_moderator=True,
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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

    assert outcome == "excluded"
    assert len(calls) == 0
    exclusions = await _fetch_exclusions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert exclusions[0]["reason"] == "moderator"


async def test_exclusion_group_itself(
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
        sender_chat_id=classification_chat_id,
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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

    assert outcome == "excluded"
    assert len(calls) == 0
    exclusions = await _fetch_exclusions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert exclusions[0]["reason"] == "group_itself"


async def test_exclusion_linked_channel(
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
        sender_chat_id=classification_chat_id - 1,
        is_automatic_forward=True,
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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

    assert outcome == "excluded"
    assert len(calls) == 0
    exclusions = await _fetch_exclusions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert exclusions[0]["reason"] == "linked_channel"


async def test_exclusion_text_removed(
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
        text_purged_at=_SENT_AT,
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
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

    assert outcome == "excluded"
    assert len(calls) == 0
    exclusions = await _fetch_exclusions(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert exclusions[0]["reason"] == "text_removed"


async def test_bot_account_and_other_channel_are_eligible(
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
    bot_pk = await insert_user(
        tg_user_id=random.randint(10_000_000, 2_000_000_000), is_bot=True
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=bot_pk,
        original_text="مرحبا بالجميع في القناة",
    )
    # Another channel's message: `sender_chat_id` differs from the group's own chat id and is not
    # an automatic forward (FR-003 — only the group's own linked channel, E7, is excluded).
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=_SENT_AT,
        sender_chat_id=classification_chat_id - 1,
        original_text="اعلان من قناة اخرى",
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER), dict(_VALID_ANSWER)])
    registry = ProfileRegistry(classification_session_factory)

    bot_outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )
    channel_outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=2,
        path="live",
    )

    assert bot_outcome == "classified"
    assert channel_outcome == "classified"
    assert len(calls) == 2


async def test_prediction_is_untouched_by_a_later_edit_or_opened_incident(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
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
        original_text="اعلان عن كورس تاني بسعر مخفض",
    )
    gateway, calls = scripted_gateway(
        responses=[
            {
                # Below the incident threshold (0.85) on purpose: US4 (T056) now opens an
                # incident itself on a confident violation, which would collide with this test's
                # own manual `open_incident` call below and defeat its point — that the
                # prediction row is untouched by *anything* that happens after it, including an
                # incident opened independently.
                "category": "SPAM_OR_AD",
                "needs_response": False,
                "needs_moderation": True,
                "severity": "high",
                "confidence": 0.72,
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
    before = await _fetch_prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert before is not None

    # An edit — the prediction reads the message's first-posted words, and this milestone never
    # re-derives it from the edit (Finding 5); the row itself must stay exactly as written.
    async with classification_session_factory() as session:
        edited_update_id = (
            await session.execute(
                telegram_updates.insert()
                .values(
                    bot_id=classification_bot_id,
                    update_id=random.randint(10_000_000, 2_000_000_000),
                    update_type="edited_message",
                    chat_id=classification_chat_id,
                    payload={
                        "edited_message": {
                            "message_id": 1,
                            "date": int(_SENT_AT.timestamp()) + 60,
                            "text": "نص معدل تماما",
                        }
                    },
                )
                .returning(telegram_updates.c.id)
            )
        ).scalar_one()
        await session.commit()
    await apply_edit(classification_session_factory, update_row_id=edited_update_id)

    # An operator incident opened independently on the same message.
    incident_id = await open_incident(
        classification_session_factory,
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        category="SPAM_OR_AD",
        severity="high",
        opened_by_user_id=1,
    )
    assert incident_id is not None

    after = await _fetch_prediction(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert after == before
    assert len(calls) == 1
