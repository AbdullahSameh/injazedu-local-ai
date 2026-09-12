"""Every HTTP status and transport failure maps to its taxonomy class with the right
`retryable` (contracts/telegram-provider.md §4); `429` waits exactly `retry_after` and never
escapes to the caller (T013, FR-005); a negative offset is never issued (T014).
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.telegram.client import TelegramClient
from app.providers.telegram.errors import (
    TelegramAuthError,
    TelegramConflictError,
    TelegramRejectedError,
    TelegramTimeoutError,
    TelegramUnreachableError,
)

from tests.moderation.ingest.conftest import FakeTelegramTransport, RecordingSleep


def _client(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> TelegramClient:
    return TelegramClient(
        "test-token", transport=fake_transport.transport, sleep=recording_sleep
    )


async def test_connect_failure_maps_to_unreachable_and_is_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("getMe", httpx.ConnectError("connection refused"))
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramUnreachableError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is True


async def test_read_timeout_maps_to_timeout_and_is_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("getMe", httpx.ReadTimeout("timed out"))
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramTimeoutError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is True


async def test_409_maps_to_conflict_and_is_not_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "getMe", 409, description="Conflict: terminated by other getUpdates request"
    )
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramConflictError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is False


async def test_401_maps_to_auth_error_and_is_not_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("getMe", 401, description="Unauthorized")
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramAuthError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is False


async def test_404_on_the_token_path_also_maps_to_auth_error(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("getMe", 404, description="Not Found")
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramAuthError):
        await client.get_me()


async def test_400_maps_to_rejected_and_is_not_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("getMe", 400, description="Bad Request")
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramRejectedError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is False


async def test_5xx_maps_to_unreachable_and_is_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("getMe", 500, description="Internal Server Error")
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(TelegramUnreachableError) as excinfo:
        await client.get_me()
    assert excinfo.value.retryable is True


async def test_429_waits_exactly_retry_after_and_never_reaches_the_caller(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "getUpdates", 429, description="Too Many Requests", parameters={"retry_after": 7}
    )
    fake_transport.enqueue_ok("getUpdates", [])
    client = _client(fake_transport, recording_sleep)

    result = await client.get_updates(offset=None, limit=100, timeout_s=30, allowed_updates=[])

    assert result == []
    assert recording_sleep.calls == [7.0]


async def test_offset_none_omits_the_parameter_entirely(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("getUpdates", [])
    client = _client(fake_transport, recording_sleep)

    await client.get_updates(offset=None, limit=100, timeout_s=30, allowed_updates=[])

    method, params = fake_transport.calls[-1]
    assert method == "getUpdates"
    assert "offset" not in params


async def test_offset_present_is_sent_verbatim(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("getUpdates", [])
    client = _client(fake_transport, recording_sleep)

    await client.get_updates(offset=101, limit=100, timeout_s=30, allowed_updates=[])

    method, params = fake_transport.calls[-1]
    assert method == "getUpdates"
    assert params["offset"] == 101


async def test_negative_offset_is_never_issued(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    client = _client(fake_transport, recording_sleep)

    with pytest.raises(AssertionError):
        await client.get_updates(offset=-1, limit=100, timeout_s=30, allowed_updates=[])
