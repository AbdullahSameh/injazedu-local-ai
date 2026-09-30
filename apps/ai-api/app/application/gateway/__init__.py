"""The gateway's public facade — the only place a moderation module may import model-call
vocabulary from (research Finding 3, D-TG-132).

`app/domain/moderation` and `app/application/moderation` may not import `app.providers.llm`,
`httpx`, `ollama` or `openai` directly (`make check`, M1). Re-exporting the request/response
types and the error taxonomy here lets moderation build a `StructuredRequest` and catch a
`GatewayError` without reaching past this package's boundary.
"""

from __future__ import annotations

from app.application.gateway.errors import (
    CircuitOpenError,
    GatewayError,
    ModelTimeoutError,
    ModelTruncatedError,
    NoActiveProfileError,
    ProviderUnreachableError,
    StructuredOutputInvalidError,
)
from app.application.gateway.gateway import Gateway
from app.providers.llm.base import Message, StructuredRequest, StructuredResponse

__all__ = [
    "CircuitOpenError",
    "Gateway",
    "GatewayError",
    "Message",
    "ModelTimeoutError",
    "ModelTruncatedError",
    "NoActiveProfileError",
    "ProviderUnreachableError",
    "StructuredOutputInvalidError",
    "StructuredRequest",
    "StructuredResponse",
]
