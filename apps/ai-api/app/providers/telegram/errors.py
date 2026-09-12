"""The Telegram provider's closed failure taxonomy (contracts/telegram-provider.md §4, D-TG-38).

Mirrors `app/application/gateway/errors.py`'s shape exactly: retry logic branches on
`retryable`, never on message text.
"""

from __future__ import annotations

from typing import ClassVar


class TelegramError(Exception):
    """Base of the closed taxonomy. Never raised directly."""

    retryable: ClassVar[bool]
    category: ClassVar[str]

    def __init__(self, message: str) -> None:
        super().__init__(message)


class TelegramUnreachableError(TelegramError):
    """Connect failure, DNS, refused."""

    retryable = True
    category = "telegram_unreachable"


class TelegramTimeoutError(TelegramError):
    """Client read timeout exceeded. Should be rare — the read timeout exceeds the long poll."""

    retryable = True
    category = "telegram_timeout"


class TelegramRateLimitedError(TelegramError):
    """HTTP 429; carries `retry_after` from `parameters.retry_after`."""

    retryable = True
    category = "telegram_rate_limited"

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TelegramConflictError(TelegramError):
    """HTTP 409 — another consumer is polling this credential."""

    retryable = False
    category = "telegram_conflict"


class TelegramAuthError(TelegramError):
    """HTTP 401/404 on the token path — a revoked or malformed credential."""

    retryable = False
    category = "telegram_auth"


class TelegramRejectedError(TelegramError):
    """HTTP 400 — a bad request shape."""

    retryable = False
    category = "telegram_rejected"
