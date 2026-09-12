"""`TelegramClient` — speaks the Bot API over `httpx` (`contracts/telegram-provider.md` §3, §4).

The only module besides `errors.py` and `models.py` permitted to import `httpx` for Telegram
(`make check`, contracts/domain-boundary.md §4). No Telegram SDK dependency is added — TG-M0's
D-TG-19.

`retry_after` honouring lives here and nowhere else (D-TG-38): `_request` absorbs a `429` by
sleeping exactly `parameters.retry_after` and retrying, so no caller ever implements its own
backoff for a rate limit. Every other failure maps structurally, from the exception type or the
HTTP status code, never from message text (probe 5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from app.providers.telegram.errors import (
    TelegramAuthError,
    TelegramConflictError,
    TelegramError,
    TelegramRateLimitedError,
    TelegramRejectedError,
    TelegramTimeoutError,
    TelegramUnreachableError,
)
from app.providers.telegram.models import BotIdentity, ChatMemberStatus, TelegramUpdate, WebhookInfo

# probe 5: connect=5s, read=35s — the read timeout must exceed the 30s server-side long poll
# (D-TG-39), or the client aborts every poll at the moment Telegram is legitimately holding it.
DEFAULT_TIMEOUT = httpx.Timeout(5.0, read=35.0)

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


def _retry_after(response: httpx.Response) -> float:
    try:
        parameters = response.json().get("parameters") or {}
    except ValueError:
        parameters = {}
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
    if response.status_code == 400:
        return TelegramRejectedError(response.text)
    if response.status_code >= 500:
        return TelegramUnreachableError(response.text)
    return TelegramRejectedError(response.text)


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

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        while True:
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url, transport=self._transport, timeout=self._timeout
                ) as client:
                    response = await client.post(f"/{method}", json=params or {})
            except httpx.TimeoutException as exc:
                raise TelegramTimeoutError(str(exc)) from exc
            except httpx.TransportError as exc:
                raise TelegramUnreachableError(str(exc)) from exc

            if response.status_code == 200:
                return response.json()["result"]

            error = error_for_response(response)
            if isinstance(error, TelegramRateLimitedError):
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
