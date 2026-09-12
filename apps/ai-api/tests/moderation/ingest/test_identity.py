"""Bot-identity resolution: retries indefinitely without failing startup; a rejected credential
is distinguishable from an unreachable platform (FR-007a-d, SC-023).

Nothing is stored while unresolved is not a separate runtime check here: `resolve_bot_identity`
takes no database session at all, so it is structurally incapable of writing anything — the
signature is the guarantee.
"""

from __future__ import annotations

import httpx
from app.application.moderation.ingest import resolve_bot_identity
from app.providers.telegram.client import TelegramClient
from app.providers.telegram.errors import TelegramAuthError, TelegramUnreachableError

from tests.moderation.ingest.conftest import FakeTelegramTransport, RecordingSleep


async def test_identity_unresolvable_retries_indefinitely_and_eventually_resolves(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("getMe", httpx.ConnectError("connection refused"))
    fake_transport.enqueue_exception("getMe", httpx.ConnectError("connection refused"))
    fake_transport.enqueue_ok("getMe", {"id": 42, "username": "injaz_test_bot"})
    client = TelegramClient(
        "test-token", transport=fake_transport.transport, sleep=recording_sleep
    )

    identity = await resolve_bot_identity(client, sleep=recording_sleep)

    assert identity.bot_id == 42
    assert len(recording_sleep.calls) == 2  # two failed attempts before success


async def test_a_rejected_credential_is_distinct_from_an_unreachable_platform(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("getMe", 401, description="Unauthorized")
    fake_transport.enqueue_exception("getMe", httpx.ConnectError("connection refused"))
    fake_transport.enqueue_ok("getMe", {"id": 42, "username": "injaz_test_bot"})
    client = TelegramClient(
        "test-token", transport=fake_transport.transport, sleep=recording_sleep
    )

    seen: list[type[Exception]] = []
    identity = await resolve_bot_identity(
        client, sleep=recording_sleep, on_attempt_failed=lambda exc: seen.append(type(exc))
    )

    assert identity.bot_id == 42
    assert seen == [TelegramAuthError, TelegramUnreachableError]
