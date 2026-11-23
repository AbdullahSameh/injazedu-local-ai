"""TG-M6's three outbound provider methods (D-TG-215, `contracts/alerting.md` V4-V5, U3, B7).

- Each method's request shape.
- `editMessageText`: "message is not modified" is success; "message to edit not found" is
  `TelegramMessageGoneError`.
- `answerCallbackQuery`: "query is too old" is `TelegramCallbackExpiredError`; the text is cut to
  200 characters (T3).
- A failure after the request was written is `TelegramOutcomeUnknownError`, never retryable; a
  connect-phase failure keeps its retryable class. `get_updates` is unchanged.
- A `429` waits `retry_after` and retries, at most three times for an outbound call.
- A `400` carries `description` and `parameters`, including `migrate_to_chat_id` (T8).
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.telegram.client import TelegramClient
from app.providers.telegram.errors import (
    TelegramCallbackExpiredError,
    TelegramMessageGoneError,
    TelegramOutcomeUnknownError,
    TelegramRateLimitedError,
    TelegramRejectedError,
    TelegramTimeoutError,
    TelegramUnreachableError,
)

from tests.moderation.ingest.conftest import FakeTelegramTransport, RecordingSleep

_KEYBOARD = {"inline_keyboard": [[{"text": "✅", "callback_data": "a:1:h"}]]}


def _client(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> TelegramClient:
    return TelegramClient("test-token", transport=fake_transport.transport, sleep=recording_sleep)


# --- request shapes ---


async def test_send_message_posts_html_without_link_previews_and_returns_the_id(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("sendMessage", {"message_id": 77, "chat": {"id": -1001}})
    client = _client(fake_transport, recording_sleep)

    message_id = await client.send_message(chat_id=-1001, text="<b>hi</b>", reply_markup=_KEYBOARD)

    assert message_id == 77
    assert fake_transport.calls == [
        (
            "sendMessage",
            {
                "chat_id": -1001,
                "text": "<b>hi</b>",
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
                "reply_markup": _KEYBOARD,
            },
        )
    ]


async def test_send_message_without_a_keyboard_sends_none(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("sendMessage", {"message_id": 78})

    await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")

    assert "reply_markup" not in fake_transport.calls[0][1]


async def test_edit_message_text_shape_with_and_without_a_keyboard(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("editMessageText", {"message_id": 5})
    fake_transport.enqueue_ok("editMessageText", {"message_id": 5})
    client = _client(fake_transport, recording_sleep)

    await client.edit_message_text(chat_id=-1001, message_id=5, text="a", reply_markup=_KEYBOARD)
    await client.edit_message_text(chat_id=-1001, message_id=5, text="b")

    with_keyboard, without = (params for _, params in fake_transport.calls)
    assert with_keyboard == {
        "chat_id": -1001,
        "message_id": 5,
        "text": "a",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": _KEYBOARD,
    }
    # No keyboard sent: Telegram removes the existing one.
    assert "reply_markup" not in without


async def test_answer_callback_query_shape_and_the_200_character_cut(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_ok("answerCallbackQuery", True)

    await _client(fake_transport, recording_sleep).answer_callback_query(
        callback_query_id="cq-1", text="ب" * 250
    )

    method, params = fake_transport.calls[0]
    assert method == "answerCallbackQuery"
    assert params == {"callback_query_id": "cq-1", "text": "ب" * 200}


# --- edit outcomes ---


async def test_not_modified_counts_as_success(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "editMessageText",
        400,
        description="Bad Request: message is not modified: specified new message content and "
        "reply markup are exactly the same as a current content and reply markup of the message",
    )

    await _client(fake_transport, recording_sleep).edit_message_text(
        chat_id=-1001, message_id=5, text="same"
    )


async def test_a_deleted_alert_is_message_gone(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "editMessageText", 400, description="Bad Request: message to edit not found"
    )

    with pytest.raises(TelegramMessageGoneError) as excinfo:
        await _client(fake_transport, recording_sleep).edit_message_text(
            chat_id=-1001, message_id=5, text="x"
        )
    assert excinfo.value.category == "telegram_message_gone"
    assert excinfo.value.retryable is False


async def test_another_edit_refusal_stays_rejected(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "editMessageText", 400, description="Bad Request: can't parse entities"
    )

    with pytest.raises(TelegramRejectedError) as excinfo:
        await _client(fake_transport, recording_sleep).edit_message_text(
            chat_id=-1001, message_id=5, text="<b"
        )
    assert type(excinfo.value) is TelegramRejectedError
    assert excinfo.value.description == "Bad Request: can't parse entities"


async def test_an_expired_press_is_callback_expired(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "answerCallbackQuery",
        400,
        description="Bad Request: query is too old and response timeout expired or query ID is "
        "invalid",
    )

    with pytest.raises(TelegramCallbackExpiredError) as excinfo:
        await _client(fake_transport, recording_sleep).answer_callback_query(
            callback_query_id="cq-1", text="x"
        )
    assert excinfo.value.category == "telegram_callback_expired"


# --- unknown outcome vs connect failure ---


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("timed out"),
        httpx.WriteTimeout("timed out"),
        httpx.ReadError("connection reset"),
        httpx.WriteError("broken pipe"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
)
async def test_a_failure_after_writing_is_outcome_unknown_and_never_retried(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep, exc: Exception
) -> None:
    fake_transport.enqueue_exception("sendMessage", exc)

    with pytest.raises(TelegramOutcomeUnknownError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")
    assert excinfo.value.retryable is False
    assert excinfo.value.category == "telegram_outcome_unknown"
    assert len(fake_transport.calls) == 1


async def test_an_edit_after_writing_is_outcome_unknown_too(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("editMessageText", httpx.ReadTimeout("timed out"))

    with pytest.raises(TelegramOutcomeUnknownError):
        await _client(fake_transport, recording_sleep).edit_message_text(
            chat_id=-1001, message_id=5, text="x"
        )


async def test_a_connect_failure_stays_unreachable_and_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("sendMessage", httpx.ConnectError("refused"))

    with pytest.raises(TelegramUnreachableError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")
    assert excinfo.value.retryable is True


async def test_a_connect_timeout_stays_timeout_and_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("sendMessage", httpx.ConnectTimeout("timed out"))

    with pytest.raises(TelegramTimeoutError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")
    assert excinfo.value.retryable is True


async def test_a_5xx_on_send_is_unreachable_and_retryable(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("sendMessage", 502, description="Bad Gateway")

    with pytest.raises(TelegramUnreachableError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")
    assert excinfo.value.retryable is True


async def test_get_updates_read_timeout_is_unchanged(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_exception("getUpdates", httpx.ReadTimeout("timed out"))

    with pytest.raises(TelegramTimeoutError):
        await _client(fake_transport, recording_sleep).get_updates(
            offset=None, limit=10, timeout_s=1, allowed_updates=["message"]
        )


# --- 429 ---


async def test_a_429_waits_retry_after_then_sends(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "sendMessage", 429, description="Too Many Requests", parameters={"retry_after": 7}
    )
    fake_transport.enqueue_ok("sendMessage", {"message_id": 9})

    message_id = await _client(fake_transport, recording_sleep).send_message(
        chat_id=-1001, text="x"
    )

    assert message_id == 9
    assert recording_sleep.calls == [7.0]


async def test_an_outbound_429_is_waited_out_at_most_three_times(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    for _ in range(4):
        fake_transport.enqueue_error(
            "sendMessage", 429, description="Too Many Requests", parameters={"retry_after": 2}
        )

    with pytest.raises(TelegramRateLimitedError):
        await _client(fake_transport, recording_sleep).send_message(chat_id=-1001, text="x")
    assert recording_sleep.calls == [2.0, 2.0, 2.0]
    assert len(fake_transport.calls) == 4


# --- 400 parameters ---


async def test_a_migrated_destination_carries_migrate_to_chat_id(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error(
        "sendMessage",
        400,
        description="Bad Request: group chat was upgraded to a supergroup chat",
        parameters={"migrate_to_chat_id": -1009876543210},
    )

    with pytest.raises(TelegramRejectedError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-555, text="x")
    assert excinfo.value.migrate_to_chat_id == -1009876543210
    assert excinfo.value.description == (
        "Bad Request: group chat was upgraded to a supergroup chat"
    )


async def test_a_plain_400_has_no_migration(
    fake_transport: FakeTelegramTransport, recording_sleep: RecordingSleep
) -> None:
    fake_transport.enqueue_error("sendMessage", 400, description="Bad Request: chat not found")

    with pytest.raises(TelegramRejectedError) as excinfo:
        await _client(fake_transport, recording_sleep).send_message(chat_id=-555, text="x")
    assert excinfo.value.migrate_to_chat_id is None
    assert excinfo.value.parameters == {}
