"""T046 — no log line the classifier emits ever carries text: not the original, not the
normalised, not the redacted words, and not a scripted model answer's own field values. Records
that do log carry `message_id` (and `chat_id` when relevant) in `extra`, never a text field
(`contracts/classification-pipeline.md` §4 P5, §11 N6, FR-010, SC-020).

Uses a dedicated handler attached directly to `classification.py`'s own logger, exactly as
`tests/moderation/test_logging_extras.py` does, rather than pytest's `caplog` fixture: something
elsewhere in this suite (`app/workers/main.py` calling `configure_logging()` at import time,
transitively triggered by another test file) replaces the root logger's handlers, and `caplog`'s
own root-propagation capture silently stops seeing this package's records once that has run —
reproducible only in a full-suite run, never in this file alone.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.application.gateway import StructuredOutputInvalidError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 7, 9, 0, 0, tzinfo=UTC)

_ELIGIBLE_TEXT = "سؤال غريب جدا عن نظام الدفع الالكتروني الخاص بالكورس"
_EXCLUDED_TEXT = "كلام لا يجب ان يظهر في اي سجل مهما حدث"

_VALID_ANSWER = {
    "category": "QUESTION_ACCESS",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.87,
}

_TEXT_MARKERS = (_ELIGIBLE_TEXT, _EXCLUDED_TEXT)

_LOGGER_NAME = "app.application.moderation.classification"


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured_records() -> Iterator[_CaptureHandler]:
    """Attaches directly to `classification.py`'s own logger (matching
    `tests/moderation/ingest/test_ingest_logging.py`'s and `test_logging_extras.py`'s established
    `caplog`-avoidance pattern) and restores its prior state afterward, so this test's own
    mutation does not leak into any test that runs after it.

    Alembic's `env.py` calls `logging.config.fileConfig(...)` (default
    `disable_existing_loggers=True`) whenever a migration runs earlier in the same test session —
    which marks any logger not listed in `alembic.ini`, this one included, as `.disabled = True`.
    `Logger.disabled` short-circuits before level/handlers are even consulted, so it must be saved
    and cleared here too, not just level/handlers/propagate."""
    log = logging.getLogger(_LOGGER_NAME)
    original_level = log.level
    original_propagate = log.propagate
    original_disabled = log.disabled
    handler = _CaptureHandler()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.disabled = False
    log.addHandler(handler)
    try:
        yield handler
    finally:
        log.removeHandler(handler)
        log.setLevel(original_level)
        log.propagate = original_propagate
        log.disabled = original_disabled


def _assert_no_text_leak(records: list[logging.LogRecord]) -> None:
    for record in records:
        message = record.getMessage()
        for marker in _TEXT_MARKERS:
            assert marker not in message
        for value in vars(record).values():
            if isinstance(value, str):
                for marker in _TEXT_MARKERS:
                    assert marker not in value


async def test_no_log_line_carries_message_text_across_every_outcome(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
    captured_records: _CaptureHandler,
) -> None:
    eligible_chat_pk = await insert_chat(chat_id=classification_chat_id)
    await insert_message(
        telegram_chat_id=eligible_chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text=_ELIGIBLE_TEXT,
    )
    excluded_chat_pk = await insert_chat(chat_id=classification_chat_id - 1)
    await insert_message(
        telegram_chat_id=excluded_chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text=_EXCLUDED_TEXT,
        is_service=True,
    )
    failing_chat_pk = await insert_chat(chat_id=classification_chat_id - 2)
    await insert_message(
        telegram_chat_id=failing_chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        original_text=_ELIGIBLE_TEXT,
    )

    registry = ProfileRegistry(classification_session_factory)

    eligible_gateway, _ = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    eligible_outcome = await classify_one(
        classification_session_factory,
        eligible_gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=eligible_chat_pk,
        message_id=1,
        path="live",
    )

    excluded_gateway, _ = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    excluded_outcome = await classify_one(
        classification_session_factory,
        excluded_gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=excluded_chat_pk,
        message_id=1,
        path="live",
    )

    failing_gateway, _ = scripted_gateway(fail_with=StructuredOutputInvalidError)
    failing_outcome = await classify_one(
        classification_session_factory,
        failing_gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=failing_chat_pk,
        message_id=1,
        path="live",
    )

    assert eligible_outcome == "classified"
    assert excluded_outcome == "excluded"
    assert failing_outcome == "failed"

    _assert_no_text_leak(captured_records.records)

    failure_records = [
        record
        for record in captured_records.records
        if record.getMessage() == "classification failed"
    ]
    assert len(failure_records) == 1
    failure_extra = vars(failure_records[0])
    assert failure_extra["message_id"] == 1
    assert failure_extra["chat_id"] == failing_chat_pk
    assert failure_extra["category"] == "structured_output_invalid"
