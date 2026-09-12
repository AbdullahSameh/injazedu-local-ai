"""A regression test for a real incident, not a hypothetical: once `telegram_main.py` was
actually wired to run against a live credential (T084), `httpx`'s own INFO-level request logging
put the bot token in plaintext into stdout — Telegram's Bot API embeds the credential in the URL
path (`/bot<TOKEN>/<method>`), unlike a bearer header, and the JsonFormatter's `_EXTRA_KEYS`
whitelist (D-TG-24) only guards structured `extra=` fields, not a third-party logger's own
message string. `make check` never would have caught this — it runs with no credential
configured (SC-016), so `get_me` is never actually called against a real token in the suite.

Guards `configure_logging`'s fix directly: the credential must never reach the configured log
stream (FR-039, `contracts/ingestion-guarantees.md` G5 — "The credential never reaches the
database or a log").
"""

from __future__ import annotations

import io
import logging

from app.infrastructure.logging import configure_logging
from app.providers.telegram.client import TelegramClient
from app.providers.telegram.models import BotIdentity

from tests.moderation.ingest.conftest import FakeTelegramTransport

_FAKE_TOKEN = "123456789:AAFake-Token-Shaped-Value-For-This-Regression-Test-Only"


async def test_a_real_get_me_call_never_writes_the_token_to_the_configured_log_stream(
    fake_transport: FakeTelegramTransport,
) -> None:
    configure_logging("INFO")
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    handler.stream = stream  # capture into a buffer this test controls, not pytest's own capsys

    fake_transport.enqueue_ok("getMe", {"id": 1, "username": "test_bot"})
    client = TelegramClient(_FAKE_TOKEN, transport=fake_transport.transport)
    identity = await client.get_me()

    assert identity == BotIdentity(bot_id=1, username="test_bot")
    assert _FAKE_TOKEN not in stream.getvalue()


def test_configure_logging_raises_the_httpx_logger_above_info() -> None:
    configure_logging("INFO")
    assert logging.getLogger("httpx").isEnabledFor(logging.INFO) is False
