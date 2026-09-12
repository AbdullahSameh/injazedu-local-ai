"""US5 — capture log lines carry `update_id`/`chat_id` and no message text; the correlation key
is `message_id`, never `message` (FR-037, SC-017, TG-M0 D-TG-24, `contracts/health-ingestion.md`
§3).

⚠ Calls `logger.setLevel` before logging — the reserved-name `KeyError` `extra={"message": …}`
raises fires inside `Logger.makeRecord`, which a call below the logger's effective level never
reaches (research.md §0 probe 8; mirrors `tests/moderation/test_logging_extras.py`).
"""

from __future__ import annotations

import json
import logging

from app.application.moderation import ingest as ingest_module
from app.application.moderation.ingest import store_batch
from app.infrastructure.logging import JsonFormatter
from app.providers.telegram.client import parse_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


async def test_a_stored_batch_logs_update_id_and_chat_id_with_no_message_text(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    logger = ingest_module.logger
    logger.setLevel(logging.INFO)  # REQUIRED — see module docstring.
    previous_propagate = logger.propagate
    previous_handlers = logger.handlers
    # Alembic's env.py calls `logging.config.fileConfig(...)` (its default
    # `disable_existing_loggers=True`) whenever a migration runs earlier in the same test
    # session — which marks any logger not listed in `alembic.ini`, this one included, as
    # `.disabled = True`. `Logger.disabled` short-circuits before level/handlers are even
    # consulted, so it must be saved and cleared here too, not just level/handlers/propagate.
    previous_disabled = logger.disabled
    logger.disabled = False
    handler = _CaptureHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    try:
        update = parse_update(make_message_update(51000, chat_id=-1009, text="secret content"))
        await store_batch(
            ingest_session_factory,
            bot_id=ingest_bot_id,
            updates=[update],
            schedule=lambda *_a: None,
        )
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagate
        logger.disabled = previous_disabled

    assert handler.lines, "store_batch logged nothing for a newly stored row"
    payload = json.loads(handler.lines[-1])
    assert payload["update_id"] == 51000
    assert payload["chat_id"] == -1009
    assert "secret content" not in json.dumps(payload)
    # The correlation key for a Telegram message is `message_id`, never `message` — `message` is
    # the formatter's own reserved field (the log line's text), never a Telegram identifier.
    assert payload["message"] != -1009
    assert payload["message"] != 51000
