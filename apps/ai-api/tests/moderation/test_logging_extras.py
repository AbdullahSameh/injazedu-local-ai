"""Tests for `JsonFormatter`'s six-key correlation whitelist (data-model.md §3, D-TG-24).

⚠ Every test here calls `logger.setLevel` before logging. The reserved-name `KeyError` that
`extra={"message": …}` raises is thrown inside `Logger.makeRecord`, which a call below the
logger's effective level never reaches — a test that omits `setLevel` reports every key as
accepted and passes without ever building a record (research.md §0 probe 8).

FR-027-FR-029, SC-012.
"""

from __future__ import annotations

import json
import logging

import pytest
from app.infrastructure.logging import JsonFormatter

_WHITELISTED_KEYS = ("update_id", "chat_id", "message_id", "incident_id", "alert_id", "actor")


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def logger() -> logging.Logger:
    log = logging.getLogger("tests.moderation.test_logging_extras")
    log.setLevel(logging.INFO)  # REQUIRED — see module docstring.
    log.propagate = False
    handler = _CaptureHandler()
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]
    return log


def _emitted(logger: logging.Logger) -> dict[str, object]:
    handler = logger.handlers[0]
    assert isinstance(handler, _CaptureHandler)
    assert handler.lines, "no record was built — is the logger's level set below the call?"
    result: dict[str, object] = json.loads(handler.lines[-1])
    return result


def test_all_six_whitelisted_keys_are_emitted_when_supplied(logger: logging.Logger) -> None:
    logger.info(
        "ingested",
        extra={
            "update_id": 1,
            "chat_id": -100200300,
            "message_id": 42,
            "incident_id": 7,
            "alert_id": 3,
            "actor": "moderator:9",
        },
    )
    payload = _emitted(logger)
    assert payload["update_id"] == 1
    assert payload["chat_id"] == -100200300
    assert payload["message_id"] == 42
    assert payload["incident_id"] == 7
    assert payload["alert_id"] == 3
    assert payload["actor"] == "moderator:9"


@pytest.mark.parametrize("key", _WHITELISTED_KEYS)
def test_each_whitelisted_key_alone_is_emitted(logger: logging.Logger, key: str) -> None:
    logger.info("event", extra={key: "v"})
    payload = _emitted(logger)
    assert payload[key] == "v"


def test_unlisted_key_is_dropped_but_the_record_is_still_written(logger: logging.Logger) -> None:
    logger.info("event", extra={"original_text": "متى تبدأ المحاضرة، اتصل بي 0501234567"})
    payload = _emitted(logger)
    assert "original_text" not in payload
    assert payload["message"] == "event"


@pytest.mark.parametrize(
    "key", ["normalized_text", "redacted_text", "message_text", "caption", "random_key"]
)
def test_other_unlisted_keys_are_also_dropped(logger: logging.Logger, key: str) -> None:
    logger.info("event", extra={key: "should not appear"})
    payload = _emitted(logger)
    assert key not in payload


def test_existing_call_sites_produce_byte_identical_lines(logger: logging.Logger) -> None:
    # No extras supplied — the exact call shape every pre-TG-M0 log statement uses.
    logger.info("plain event")
    payload = _emitted(logger)
    assert set(payload.keys()) == {"timestamp", "level", "logger", "message"}
    assert payload["level"] == "INFO"
    assert payload["message"] == "plain event"
