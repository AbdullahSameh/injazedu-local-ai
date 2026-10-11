"""T028 — the attention task's own retry (`specs/011-tg-m5-3-attention-judgement/contracts/
attention-judgement.md` §8 F1), mirroring `tests/moderation/classification/test_task_retry.py`.

A transient `GatewayError` re-raised by `judge_one` reschedules `judge_attention` with
`attempt + 1` and a doubling delay (`MODERATION_CLASSIFY_RETRY_BASE_S × 2^(attempt−1)`: 30 s, 60 s,
120 s, 240 s at the defaults). On the last attempt (`MODERATION_CLASSIFY_MAX_ATTEMPTS`) it records
one `failed` attention attempt naming the kind and the active attention profile, and sends nothing
further.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway import CircuitOpenError, ModelTimeoutError, ProviderUnreachableError
from app.infrastructure.models_moderation import message_attention_attempts
from app.workers.tasks.moderation import judge_attention as judge_attention_module
from app.workers.tasks.moderation.judge_attention import _judge_with_retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)


async def _fetch_failures(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(message_attention_attempts).where(
                    message_attention_attempts.c.telegram_chat_id == chat_pk,
                    message_attention_attempts.c.telegram_message_id == message_id,
                    message_attention_attempts.c.outcome == "failed",
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


def _patch_judge_attention_once(monkeypatch: Any, *, raises: type[Exception]) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> str:
        raise raises("injected", profile_name="att-test")

    monkeypatch.setattr(judge_attention_module, "judge_attention_once", _fake)


def _patch_send_with_options(monkeypatch: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def _fake(*, args: tuple[Any, ...], delay: int) -> None:
        sent.append({"args": args, "delay": delay})

    monkeypatch.setattr(judge_attention_module.judge_attention, "send_with_options", _fake)
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
    monkeypatch: Any,
    transient_error: type[Exception],
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)
    _patch_judge_attention_once(monkeypatch, raises=transient_error)
    sent = _patch_send_with_options(monkeypatch)

    expected_delays = [30_000, 60_000, 120_000, 240_000]
    for attempt, expected_delay in enumerate(expected_delays, start=1):
        await _judge_with_retry(
            classification_session_factory,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=1,
            attempt=attempt,
        )
        assert sent[-1] == {"args": (chat_pk, 1, attempt + 1), "delay": expected_delay}

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
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
    monkeypatch: Any,
    transient_error: type[Exception],
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)
    profile_id = await seeded_attention_profile(active=True)
    _patch_judge_attention_once(monkeypatch, raises=transient_error)
    sent = _patch_send_with_options(monkeypatch)

    await _judge_with_retry(
        classification_session_factory,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        attempt=classification_settings.moderation_classify_max_attempts,
    )

    assert sent == []
    failures = await _fetch_failures(classification_session_factory, chat_pk=chat_pk, message_id=1)
    assert [(f["reason"], f["model_profile_id"], f["path"]) for f in failures] == [
        (transient_error.category, profile_id, "live")  # type: ignore[attr-defined]
    ]


async def test_an_outcome_returned_without_raising_is_never_rescheduled(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    classification_redis: Any,
    classification_settings: Any,
    monkeypatch: Any,
) -> None:
    """A final error is recorded by `judge_one` itself and returned as `"failed"` (F2): the task
    adds nothing for that path."""
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_SENT_AT)

    async def _fake(*_args: Any, **_kwargs: Any) -> str:
        return "failed"

    monkeypatch.setattr(judge_attention_module, "judge_attention_once", _fake)
    sent = _patch_send_with_options(monkeypatch)

    await _judge_with_retry(
        classification_session_factory,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        attempt=1,
    )

    assert sent == []
