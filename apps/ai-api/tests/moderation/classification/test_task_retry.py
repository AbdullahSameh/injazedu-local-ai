"""T049 — task-level retry (`contracts/classification-pipeline.md` §8 F2-F3): a transient
`GatewayError` re-raised by `classify_one` reschedules the same actor with `attempt + 1` and a
doubling delay (30 s, 60 s, 120 s, 240 s at the documented defaults); on the last attempt it
records one `failed` row naming the kind and sends nothing further; any other gateway error is
recorded on the first attempt and never rescheduled (FR-023, FR-024, D-TG-151).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway import CircuitOpenError, ModelTimeoutError, ProviderUnreachableError
from app.infrastructure.models_moderation import message_classification_attempts
from app.workers.tasks.moderation import classify_message as classify_message_module
from app.workers.tasks.moderation.classify_message import _classify_with_retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 8, 9, 0, 0, tzinfo=UTC)


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


def _patch_classify_message_once(monkeypatch: Any, *, raises: type[Exception]) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> str:
        raise raises("injected", profile_name="cls-test-moderation-active")

    monkeypatch.setattr(classify_message_module, "classify_message_once", _fake)


def _patch_send_with_options(monkeypatch: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def _fake(*, args: tuple[Any, ...], delay: int) -> None:
        sent.append({"args": args, "delay": delay})

    monkeypatch.setattr(classify_message_module.classify_message, "send_with_options", _fake)
    return sent


@pytest.mark.parametrize(
    "transient_error", [ProviderUnreachableError, ModelTimeoutError, CircuitOpenError]
)
async def test_a_transient_failure_reschedules_with_doubling_backoff(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    classification_redis: Any,
    classification_settings: Any,
    classification_seeded_profile: None,
    monkeypatch: Any,
    transient_error: type[Exception],
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)
    _patch_classify_message_once(monkeypatch, raises=transient_error)
    sent = _patch_send_with_options(monkeypatch)

    expected_delays = [30_000, 60_000, 120_000, 240_000]
    for attempt, expected_delay in enumerate(expected_delays, start=1):
        await _classify_with_retry(
            classification_session_factory,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=1,
            path="live",
            attempt=attempt,
        )
        assert sent[-1] == {"args": (chat_pk, 1, "live", attempt + 1), "delay": expected_delay}

    assert len(sent) == 4
    failures = await _fetch_failures(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert failures == []


@pytest.mark.parametrize(
    "transient_error", [ProviderUnreachableError, ModelTimeoutError, CircuitOpenError]
)
async def test_the_last_attempt_records_one_failure_and_sends_nothing_further(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    classification_redis: Any,
    classification_settings: Any,
    classification_seeded_profile: None,
    monkeypatch: Any,
    transient_error: type[Exception],
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)
    _patch_classify_message_once(monkeypatch, raises=transient_error)
    sent = _patch_send_with_options(monkeypatch)

    last_attempt = classification_settings.moderation_classify_max_attempts
    await _classify_with_retry(
        classification_session_factory,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
        attempt=last_attempt,
    )

    assert sent == []
    failures = await _fetch_failures(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert len(failures) == 1
    assert failures[0]["reason"] == transient_error.category
    assert failures[0]["model_profile_id"] is not None


async def test_a_non_transient_gateway_error_is_recorded_on_the_first_attempt_never_rescheduled(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    classification_redis: Any,
    classification_settings: Any,
    classification_seeded_profile: None,
    monkeypatch: Any,
) -> None:
    """`ModelNotAvailableError` is not in F2's transient set — `classify_one` itself records it and
    returns `"failed"` rather than raising, so `_classify_with_retry` never even sees it as an
    exception; this proves the task layer adds nothing extra for that path (F3)."""
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)

    async def _fake(*_args: Any, **_kwargs: Any) -> str:
        return "failed"

    monkeypatch.setattr(classify_message_module, "classify_message_once", _fake)
    sent = _patch_send_with_options(monkeypatch)

    await _classify_with_retry(
        classification_session_factory,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
        attempt=1,
    )

    assert sent == []
