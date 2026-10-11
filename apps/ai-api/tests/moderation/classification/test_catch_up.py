"""T064 (US6) — `python -m app.scripts.classify_chat`, the catch-up command
(`contracts/classification-pipeline.md` §9 C1-C3, `data-model.md` §2's `path='catch_up'`,
D-TG-160, FR-061, FR-062, SC-011).

Every prediction it writes carries `path='catch_up'`; `route_prediction`'s R1 then forces
`route='measurement_only'` regardless of confidence or consistency (`ck_classification_route_
path` backstops it in the database), so a catch-up run never opens an incident and never appears
on the possible-violations list (C4) — measurement only, exactly as `classify_one` and
`route_prediction` are already proven to behave (US1, US4); this file proves the **walking**
command around them, not the routing itself.

`scripted_gateway`'s provider factory is called fresh on every `Gateway.generate_structured` call
(`gateway.py`'s own `provider = self._llm_provider_factory(profile)`), so each message that must
receive a distinct scripted answer gets its own gateway build — a shared gateway across several
different messages would hand every one of them `responses[0]`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway import ProviderUnreachableError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.metrics import possible_violations
from app.infrastructure.models_moderation import message_classifications
from app.scripts.classify_chat import ChatNotMonitoredError, classify_chat
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)

_CONFIDENT_VIOLATION = {
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "high",
    "confidence": 0.93,
}


async def _fetch_prediction(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> dict[str, object] | None:
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


async def test_refuses_an_unmeasured_chat(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    await insert_chat(chat_id=classification_chat_id, is_monitored=False)
    gateway, calls = scripted_gateway()
    registry = ProfileRegistry(classification_session_factory)

    with pytest.raises(ChatNotMonitoredError):
        await classify_chat(
            classification_session_factory,
            gateway,
            registry,
            classification_redis,
            classification_settings,
            chat_id=classification_chat_id,
        )
    assert len(calls) == 0


async def test_catch_up_predictions_are_measurement_only_and_open_and_list_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    fetch_incident: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text="اعلان عن كورس بسعر مخفض جدا انضموا الان",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=_SENT_AT, media_kind="photo",
        original_text=None,
    )

    gateway, calls = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    registry = ProfileRegistry(classification_session_factory)

    report = await classify_chat(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_id=classification_chat_id,
    )

    assert report.classified == 1
    assert report.excluded == {"media": 1}
    assert report.failed == {}
    assert len(calls) == 1

    prediction = await _fetch_prediction(
        classification_session_factory, chat_pk=chat_pk, message_id=1
    )
    assert prediction is not None
    assert prediction["path"] == "catch_up"
    assert prediction["route"] == "measurement_only"
    assert prediction["route_reason"] is None
    assert prediction["confidence_floor"] is None
    assert prediction["incident_threshold"] is None

    assert await fetch_incident(telegram_chat_id=chat_pk, telegram_message_id=1) is None

    async with classification_session_factory() as session:
        listed = await possible_violations(
            session,
            period_from=_SENT_AT.replace(year=2000),
            period_to=_SENT_AT.replace(year=2100),
            chat_id=chat_pk,
        )
    assert listed == []


async def test_a_second_run_classifies_nothing_and_makes_no_provider_call(
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
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, original_text="نص للتصنيف"
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=_SENT_AT, media_kind="photo",
        original_text=None,
    )
    registry = ProfileRegistry(classification_session_factory)

    first_gateway, _ = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    first_report = await classify_chat(
        classification_session_factory,
        first_gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_id=classification_chat_id,
    )
    assert first_report.classified == 1
    assert first_report.excluded == {"media": 1}

    second_gateway, second_calls = scripted_gateway(fail_with=ProviderUnreachableError)
    second_report = await classify_chat(
        classification_session_factory,
        second_gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_id=classification_chat_id,
    )
    assert second_report.classified == 0
    assert second_report.excluded == {}
    assert second_report.failed == {}
    assert len(second_calls) == 0


async def test_transient_failures_are_recorded_not_rescheduled(
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
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, original_text="نص سيفشل تصنيفه"
    )
    gateway, calls = scripted_gateway(fail_with=ProviderUnreachableError)
    registry = ProfileRegistry(classification_session_factory)

    report = await classify_chat(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_id=classification_chat_id,
    )

    assert report.classified == 0
    assert report.excluded == {}
    assert report.failed == {"provider_unreachable": 1}
    assert len(calls) == 1  # never retried within this run — one call, one recorded failure

    async with classification_session_factory() as session:
        row = (
            await session.execute(
                sa.select(message_classifications).where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == 1,
                )
            )
        ).first()
    assert row is None  # a failure never yields a prediction


async def test_the_printed_report_counts_equal_the_rows_written(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_user: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    moderator_user_pk = await insert_user(tg_user_id=1_234_567)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT, original_text="نص للتصنيف الاول"
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=_SENT_AT, is_from_moderator=True,
        telegram_user_id=moderator_user_pk, original_text="رد المشرف",
    )
    registry = ProfileRegistry(classification_session_factory)

    gateway, _ = scripted_gateway(responses=[dict(_CONFIDENT_VIOLATION)])
    report = await classify_chat(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_id=classification_chat_id,
    )

    assert report.render() == "classified=1 excluded=moderator:1 failed="
