"""`TelegramClient` — speaks the Bot API over `httpx` (`contracts/telegram-provider.md` §3, §4).

The only module besides `errors.py` and `models.py` permitted to import `httpx` for Telegram
(`make check`, contracts/domain-boundary.md §4). No Telegram SDK dependency is added — TG-M0's
D-TG-19.

`retry_after` honouring lives here and nowhere else (D-TG-38): `_request` absorbs a `429` by
sleeping exactly `parameters.retry_after` and retrying, so no caller ever implements its own
backoff for a rate limit. Every other failure maps structurally, from the exception type or the
HTTP status code, never from message text (probe 5).

TG-M6 (D-TG-215, D-TG-227) adds three outbound methods — `send_message`, `edit_message_text`,
`answer_callback_query` — called only from `app/application/moderation/alert_delivery.py`. Two
things change for them alone:
- a transport failure after the request was written is `TelegramOutcomeUnknownError`, never a
  retryable error, because Telegram may already have acted on it;
- a `429` is waited out at most `_OUTBOUND_RATE_LIMIT_WAITS` times, then raised, so a delivery never
  holds a worker thread indefinitely.

Three Bot API refusals have no structured form and are read from Telegram's `description` (T5):
"message is not modified" (success), "message to edit not found" and "query is too old". No ban,
restrict, delete, react or pin method exists here (N2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from app.providers.telegram.errors import (
    TelegramAuthError,
    TelegramCallbackExpiredError,
    TelegramConflictError,
    TelegramError,
    TelegramMessageGoneError,
    TelegramOutcomeUnknownError,
    TelegramRateLimitedError,
    TelegramRejectedError,
    TelegramTimeoutError,
    TelegramUnreachableError,
)
from app.providers.telegram.models import BotIdentity, ChatMemberStatus, TelegramUpdate, WebhookInfo

# probe 5: connect=5s, read=35s — the read timeout must exceed the 30s server-side long poll
# (D-TG-39), or the client aborts every poll at the moment Telegram is legitimately holding it.
DEFAULT_TIMEOUT = httpx.Timeout(5.0, read=35.0)

# TG-M6 (D-TG-215): failures that can only happen after the request left this process. For an
# outbound call they mean "Telegram may have acted" — never retried. `ConnectError`,
# `ConnectTimeout` and `PoolTimeout` happen before anything is written, so they keep their
# retryable mapping.
_AFTER_WRITE_FAILURES: tuple[type[Exception], ...] = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

# A `429` on an outbound call is waited out at most this many times, then raised (V5's "exhausted
# 429 wait"): the next delivery attempt backs off from there.
_OUTBOUND_RATE_LIMIT_WAITS = 3

# T3: an answer is at most 200 characters.
_ANSWER_MAX_CHARS = 200

_NOT_MODIFIED = "message is not modified"
_MESSAGE_GONE = ("message to edit not found", "message can't be edited")
_CALLBACK_EXPIRED = ("query is too old", "query id is invalid")

_KNOWN_KINDS = (
    "message",
    "edited_message",
    "my_chat_member",
    "chat_member",
    "message_reaction",
    "callback_query",
)


def _kind_for(raw: dict[str, Any]) -> str:
    for kind in _KNOWN_KINDS:
        if kind in raw:
            return kind
    return "unknown"


def _chat_id_for(raw: dict[str, Any], kind: str) -> int | None:
    body = raw.get(kind)
    if not isinstance(body, dict):
        return None
    chat = body.get("chat")
    if isinstance(chat, dict) and "id" in chat:
        return int(chat["id"])
    # callback_query carries its chat, if any, under the optional attached message.
    message = body.get("message")
    if isinstance(message, dict):
        nested_chat = message.get("chat")
        if isinstance(nested_chat, dict) and "id" in nested_chat:
            return int(nested_chat["id"])
    return None


def parse_update(raw: dict[str, Any]) -> TelegramUpdate:
    kind = _kind_for(raw)
    return TelegramUpdate(
        update_id=raw["update_id"],
        kind=kind,
        chat_id=_chat_id_for(raw, kind),
        raw=raw,
    )


def _error_body(response: httpx.Response) -> tuple[str | None, dict[str, Any]]:
    """Telegram's `description` and `parameters`, or `(None, {})` for a non-JSON body."""
    try:
        body = response.json()
    except ValueError:
        return None, {}
    if not isinstance(body, dict):
        return None, {}
    description = body.get("description")
    parameters = body.get("parameters")
    return (
        description if isinstance(description, str) else None,
        parameters if isinstance(parameters, dict) else {},
    )


def _retry_after(response: httpx.Response) -> float:
    _description, parameters = _error_body(response)
    value = parameters.get("retry_after")
    return float(value) if value is not None else 1.0


def error_for_response(response: httpx.Response) -> TelegramError:
    """Maps an HTTP response to the closed taxonomy structurally — status code only, never
    message text (`contracts/telegram-provider.md` §4)."""
    if response.status_code == 429:
        return TelegramRateLimitedError(response.text, retry_after=_retry_after(response))
    if response.status_code == 409:
        return TelegramConflictError(response.text)
    if response.status_code in (401, 404):
        return TelegramAuthError(response.text)
    if response.status_code >= 500:
        return TelegramUnreachableError(response.text)
    description, parameters = _error_body(response)
    return TelegramRejectedError(response.text, description=description, parameters=parameters)


class TelegramProvider(Protocol):
    """The protocol every later milestone codes against (`contracts/telegram-provider.md` §3)."""

    async def get_me(self) -> BotIdentity: ...

    async def get_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_s: int,
        allowed_updates: list[str],
    ) -> list[TelegramUpdate]: ...

    async def get_webhook_info(self) -> WebhookInfo: ...

    async def get_chat_member(self, *, chat_id: int, user_id: int) -> ChatMemberStatus: ...

    async def get_chat_available_reactions(
        self, *, chat_id: int
    ) -> list[dict[str, Any]] | None: ...

    # TG-M6: the only outbound methods. Called from `alert_delivery.py` alone (D-TG-227).
    async def send_message(
        self, *, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> int: ...

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None: ...

    async def answer_callback_query(self, *, callback_query_id: str, text: str) -> None: ...


class TelegramClient:
    """Satisfies `TelegramProvider` against the real Bot API (or a scripted `httpx` transport)."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = f"{base_url}/bot{token}"
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep

    async def _request(
        self, method: str, params: dict[str, Any] | None = None, *, outbound: bool = False
    ) -> Any:
        rate_limit_waits = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url, transport=self._transport, timeout=self._timeout
                ) as client:
                    response = await client.post(f"/{method}", json=params or {})
            except _AFTER_WRITE_FAILURES as exc:
                if outbound:
                    # The exception text is httpx's, never the request body.
                    raise TelegramOutcomeUnknownError(type(exc).__name__) from exc
                if isinstance(exc, httpx.TimeoutException):
                    raise TelegramTimeoutError(str(exc)) from exc
                raise TelegramUnreachableError(str(exc)) from exc
            except httpx.TimeoutException as exc:
                raise TelegramTimeoutError(str(exc)) from exc
            except httpx.TransportError as exc:
                raise TelegramUnreachableError(str(exc)) from exc

            if response.status_code == 200:
                return response.json()["result"]

            error = error_for_response(response)
            if isinstance(error, TelegramRateLimitedError):
                if outbound and rate_limit_waits >= _OUTBOUND_RATE_LIMIT_WAITS:
                    raise error
                rate_limit_waits += 1
                await self._sleep(error.retry_after)
                continue
            raise error

    async def get_me(self) -> BotIdentity:
        result = await self._request("getMe")
        return BotIdentity(bot_id=result["id"], username=result.get("username"))

    async def get_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_s: int,
        allowed_updates: list[str],
    ) -> list[TelegramUpdate]:
        # `offset=None` omits the parameter entirely rather than sending 0 (§5, §8) — the
        # documented reset-recovery path. A negative offset forgets the whole backlog and may
        # never be issued.
        if offset is not None:
            assert offset >= 0, "get_updates offset must never be negative (data-loss operation)"
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout_s,
            "allowed_updates": allowed_updates,
        }
        if offset is not None:
            params["offset"] = offset
        result = await self._request("getUpdates", params)
        return [parse_update(item) for item in result]

    async def get_webhook_info(self) -> WebhookInfo:
        result = await self._request("getWebhookInfo")
        return WebhookInfo(url=result.get("url", ""))

    async def get_chat_member(self, *, chat_id: int, user_id: int) -> ChatMemberStatus:
        result = await self._request(
            "getChatMember", {"chat_id": chat_id, "user_id": user_id}
        )
        return ChatMemberStatus(
            status=result["status"], can_delete_messages=result.get("can_delete_messages")
        )

    async def get_chat_available_reactions(
        self, *, chat_id: int
    ) -> list[dict[str, Any]] | None:
        """Read-only `getChat`, keeping only `available_reactions` (TG-M4.1 E9): the reactions the
        chat's administrators allow, or `None` when the field is omitted — the platform's "all
        emoji reactions are allowed". Nothing else of the chat (description, pinned message) is
        kept or returned."""
        result = await self._request("getChat", {"chat_id": chat_id})
        reactions = result.get("available_reactions")
        return None if reactions is None else list(reactions)

    # --- TG-M6: outbound, to the alert group only (D-TG-215, D-TG-227) ---

    async def send_message(
        self, *, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> int:
        """Posts one HTML message with link previews off and returns its `message_id`."""
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        result = await self._request("sendMessage", params, outbound=True)
        return int(result["message_id"])

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Replaces the text of the bot's own message. With `reply_markup` None the inline keyboard
        is removed. Identical content is success (T5); a deleted message is
        `TelegramMessageGoneError` (U3)."""
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        try:
            await self._request("editMessageText", params, outbound=True)
        except TelegramRejectedError as exc:
            description = (exc.description or "").lower()
            if _NOT_MODIFIED in description:
                return
            if any(marker in description for marker in _MESSAGE_GONE):
                raise TelegramMessageGoneError(
                    str(exc), description=exc.description, parameters=exc.parameters
                ) from exc
            raise

    async def answer_callback_query(self, *, callback_query_id: str, text: str) -> None:
        """Answers a button press with a short notice (T3: at most 200 characters, cut here). A
        press too old to answer is `TelegramCallbackExpiredError`."""
        params = {"callback_query_id": callback_query_id, "text": text[:_ANSWER_MAX_CHARS]}
        try:
            await self._request("answerCallbackQuery", params, outbound=True)
        except TelegramRejectedError as exc:
            description = (exc.description or "").lower()
            if any(marker in description for marker in _CALLBACK_EXPIRED):
                raise TelegramCallbackExpiredError(
                    str(exc), description=exc.description, parameters=exc.parameters
                ) from exc
            raise
