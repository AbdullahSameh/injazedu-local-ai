"""The Telegram provider's closed failure taxonomy (contracts/telegram-provider.md §4, D-TG-38).

Mirrors `app/application/gateway/errors.py`'s shape exactly: retry logic branches on
`retryable`, never on message text.
"""

from __future__ import annotations

from typing import Any, ClassVar


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
    """HTTP 400 — a bad request shape.

    TG-M6 (D-TG-215): carries Telegram's `description` and `parameters`, because an outbound call
    must tell a migrated destination (`parameters.migrate_to_chat_id`, T8) from any other refusal.
    """

    retryable = False
    category = "telegram_rejected"

    def __init__(
        self,
        message: str,
        *,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.description = description
        self.parameters: dict[str, Any] = parameters or {}

    @property
    def migrate_to_chat_id(self) -> int | None:
        value = self.parameters.get("migrate_to_chat_id")
        return int(value) if value is not None else None


class TelegramMessageGoneError(TelegramRejectedError):
    """TG-M6 (U3): an edit of a message that no longer exists — someone deleted the
    alert in Telegram. The alert is final and its excerpt is gone."""

    category = "telegram_message_gone"


class TelegramCallbackExpiredError(TelegramRejectedError):
    """TG-M6 (B7, T3): an answer to a press too old to answer. Logged by category and
    ignored: the act, if any, is already recorded."""

    category = "telegram_callback_expired"


class TelegramOutcomeUnknownError(TelegramError):
    """TG-M6 (D-TG-215, Finding 33): an outbound request was written, then the connection broke or
    timed out before the answer. Telegram may have acted on it. Never retried: a second send could
    post the alert twice, and a lost alert is covered by its next repeat and the history."""

    retryable = False
    category = "telegram_outcome_unknown"
