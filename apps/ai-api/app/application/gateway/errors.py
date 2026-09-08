"""The gateway's closed failure taxonomy (contracts/gateway-interface.md §5, research D-27).

Retry logic branches on `retryable`, never on message text (FR-032) — that is the entire reason
this is ten classes and not one `GatewayError` with a `code` string.
"""

from __future__ import annotations

from typing import ClassVar


class GatewayError(Exception):
    """Base of the closed taxonomy. Never raised directly."""

    retryable: ClassVar[bool]
    category: ClassVar[str]

    def __init__(self, message: str, *, profile_name: str) -> None:
        super().__init__(message)
        self.profile_name = profile_name


class ProviderUnreachableError(GatewayError):
    """Connect/read failure, DNS, connection refused."""

    retryable = True
    category = "provider_unreachable"


class ModelNotAvailableError(GatewayError):
    """HTTP 404 `not_found_error` — the model isn't pulled, or the profile is wrong."""

    retryable = False
    category = "model_not_available"


class ProviderRejectedError(GatewayError):
    """HTTP 400/422 — a bad request shape, or empty/whitespace-only embedding input."""

    retryable = False
    category = "provider_rejected"


class ProviderAuthError(GatewayError):
    """HTTP 401/403, or an `api_key_env` variable that is not set."""

    retryable = False
    category = "provider_auth"


class ModelTruncatedError(GatewayError):
    """`finish_reason != "stop"` — a structured call returned HTTP 200 with empty content."""

    retryable = True
    category = "model_truncated"


class StructuredOutputInvalidError(GatewayError):
    """JSON parse or Pydantic validation failure on structured output."""

    retryable = True
    category = "structured_output_invalid"


class EmbeddingDimensionMismatchError(GatewayError):
    """A returned vector's width does not match `model_profiles.dim`."""

    retryable = False
    category = "embedding_dimension_mismatch"


class ModelTimeoutError(GatewayError):
    """The per-call deadline (`GATEWAY_CALL_TIMEOUT_S`) was exceeded."""

    retryable = True
    category = "model_timeout"


class CircuitOpenError(GatewayError):
    """The breaker is open for this profile; fails fast without a call."""

    retryable = False
    category = "circuit_open"


class NoActiveProfileError(GatewayError):
    """No active `model_profiles` row for the requested role."""

    retryable = False
    category = "no_active_profile"
