"""`FakeLLMProvider` — schema-valid synthesis from the caller's own model, so a fake never goes
stale when a schema changes (research D-39, FR-024, contracts/gateway-interface.md §7).

Also offers a scripted response queue and `fail_with` failure injection, so every branch of
the gateway's execution order (`contracts/gateway-interface.md` §6) is reachable offline.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import date, datetime
from enum import Enum
from typing import Any, Union, get_args, get_origin

from app.application.gateway.errors import GatewayError
from app.providers.llm.base import (
    StructuredRequest,
    StructuredResponse,
    TextRequest,
    TextResponse,
    Usage,
)
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_DEFAULT_PROFILE_NAME = "fake-llm"


def _synthesize(annotation: Any) -> Any:
    origin = get_origin(annotation)

    if origin is Union:  # covers `X | None`
        args = [a for a in get_args(annotation) if a is not type(None)]
        return _synthesize(args[0]) if args else None

    if origin is list:
        return []

    if origin is dict:
        return {}

    if origin is not None:
        try:
            return origin()
        except TypeError:
            return None

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return synthesize_model(annotation)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))

    if annotation is str:
        return "fake"
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if annotation is datetime:
        return datetime(2026, 1, 1)
    if annotation is date:
        return date(2026, 1, 1)

    return None


def synthesize_model(model: type[BaseModel]) -> BaseModel:
    """Build a schema-valid instance of `model`, using declared defaults where present."""
    values: dict[str, Any] = {}
    for field_name, field in model.model_fields.items():
        has_default = field.default is not PydanticUndefined
        has_default_factory = field.default_factory is not None
        if has_default or has_default_factory:
            continue
        values[field_name] = _synthesize(field.annotation)
    return model.model_validate(values)


class FakeLLMProvider:
    """Satisfies `LLMProvider` with no model runtime (contracts/gateway-interface.md §7)."""

    def __init__(
        self,
        responses: list[Any] | None = None,
        fail_with: type[GatewayError] | None = None,
        latency_ms: int = 0,
        *,
        profile_name: str = _DEFAULT_PROFILE_NAME,
    ) -> None:
        self._responses: deque[Any] | None = deque(responses) if responses is not None else None
        self._fail_with = fail_with
        self._latency_ms = latency_ms
        self._profile_name = profile_name

    async def _before_call(self) -> None:
        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)
        if self._fail_with is not None:
            raise self._fail_with(
                f"{self._fail_with.__name__} injected by FakeLLMProvider",
                profile_name=self._profile_name,
            )

    async def generate_text(self, req: TextRequest) -> TextResponse:
        await self._before_call()
        text = self._responses.popleft() if self._responses else "fake response"
        return TextResponse(
            text=text,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            latency_ms=self._latency_ms,
            profile_name=self._profile_name,
        )

    async def generate_structured(self, req: StructuredRequest[Any]) -> StructuredResponse[Any]:
        await self._before_call()
        if self._responses:
            scripted = self._responses.popleft()
            value = (
                scripted
                if isinstance(scripted, req.schema_model)
                else req.schema_model.model_validate(scripted)
            )
        else:
            value = synthesize_model(req.schema_model)
        return StructuredResponse(
            value=value,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            latency_ms=self._latency_ms,
            profile_name=self._profile_name,
        )
