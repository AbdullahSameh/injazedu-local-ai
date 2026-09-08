"""`OpenAICompatibleLLMProvider` — speaks `{base_url}/chat/completions` (research D-24).

One class serves both `ollama` and `vllm` profiles: the request/response shape is the shared
OpenAI standard (D-24, D-25). The one dialect difference this milestone knows about (FR-014):
`options.num_ctx` is an Ollama extension to the endpoint, not part of that standard, so it is
sent only for `provider == "ollama"` — a `vllm` profile's context length is fixed at server
launch (`--max-model-len`), not per request. This is the only module besides `fake.py`
allowed to import `httpx` for the `llm` role (`make check`, SC-001).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from app.application.gateway.errors import (
    ModelNotAvailableError,
    ModelTruncatedError,
    ProviderAuthError,
    ProviderRejectedError,
    ProviderUnreachableError,
    StructuredOutputInvalidError,
)
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import (
    StructuredRequest,
    StructuredResponse,
    TextRequest,
    TextResponse,
    Usage,
)
from pydantic import BaseModel, ValidationError

_CALL_TIMEOUT_S = 180.0


def _bound_params(
    profile: ModelProfile,
    *,
    max_output_tokens: int | None,
    temperature: float | None,
    context_tokens: int | None,
) -> dict[str, Any]:
    """Per-call generation bounds: profile defaults, overridden per request (D-34, FR-036)."""
    payload: dict[str, Any] = {}

    max_tokens = max_output_tokens if max_output_tokens is not None else profile.params.get(
        "num_predict"
    )
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    resolved_temperature = (
        temperature if temperature is not None else profile.params.get("temperature")
    )
    if resolved_temperature is not None:
        payload["temperature"] = resolved_temperature

    if profile.provider == "ollama":
        num_ctx = context_tokens if context_tokens is not None else profile.params.get("num_ctx")
        if num_ctx is not None:
            payload["options"] = {"num_ctx": num_ctx}

    return payload


class OpenAICompatibleLLMProvider:
    """Satisfies `LLMProvider` against a real Ollama/vLLM runtime."""

    def __init__(
        self, profile: ModelProfile, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._profile = profile
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        if self._profile.api_key_env is None:
            return {}
        value = os.environ.get(self._profile.api_key_env)
        if not value:
            raise ProviderAuthError(
                f"environment variable {self._profile.api_key_env!r} is not set",
                profile_name=self._profile.name,
            )
        return {"Authorization": f"Bearer {value}"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        try:
            async with httpx.AsyncClient(
                base_url=self._profile.base_url or "",
                transport=self._transport,
                timeout=_CALL_TIMEOUT_S,
            ) as client:
                response = await client.post(path, json=payload, headers=headers)
        except httpx.TransportError as exc:
            raise ProviderUnreachableError(str(exc), profile_name=self._profile.name) from exc

        if response.status_code == 404:
            raise ModelNotAvailableError(
                f"model {self._profile.model!r} not available: {response.text}",
                profile_name=self._profile.name,
            )
        if response.status_code in (401, 403):
            raise ProviderAuthError(response.text, profile_name=self._profile.name)
        if 400 <= response.status_code < 500:
            raise ProviderRejectedError(response.text, profile_name=self._profile.name)
        if response.status_code >= 500:
            raise ProviderUnreachableError(response.text, profile_name=self._profile.name)

        data: dict[str, Any] = response.json()
        return data

    def _usage(self, data: dict[str, Any]) -> Usage:
        usage = data.get("usage") or {}
        return Usage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def generate_text(self, req: TextRequest) -> TextResponse:
        payload: dict[str, Any] = {
            "model": self._profile.model,
            "messages": [m.model_dump() for m in req.messages],
        }
        payload.update(
            _bound_params(
                self._profile,
                max_output_tokens=req.max_output_tokens,
                temperature=req.temperature,
                context_tokens=req.context_tokens,
            )
        )

        started = time.monotonic()
        data = await self._post("/chat/completions", payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        content = data["choices"][0]["message"]["content"]
        return TextResponse(
            text=content,
            usage=self._usage(data),
            latency_ms=latency_ms,
            profile_name=self._profile.name,
        )

    async def generate_structured[T: BaseModel](
        self, req: StructuredRequest[T]
    ) -> StructuredResponse[T]:
        payload: dict[str, Any] = {
            "model": self._profile.model,
            "messages": [m.model_dump() for m in req.messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": req.schema_model.__name__,
                    "schema": req.schema_model.model_json_schema(),
                    "strict": True,
                },
            },
        }
        payload.update(
            _bound_params(
                self._profile,
                max_output_tokens=req.max_output_tokens,
                temperature=req.temperature,
                context_tokens=req.context_tokens,
            )
        )

        started = time.monotonic()
        data = await self._post("/chat/completions", payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]

        # D-26: a truncated call is HTTP 200 with empty content — check before parsing.
        if finish_reason != "stop":
            raise ModelTruncatedError(
                f"finish_reason={finish_reason!r} (expected 'stop')",
                profile_name=self._profile.name,
            )

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise StructuredOutputInvalidError(
                f"invalid JSON in model output: {exc}", profile_name=self._profile.name
            ) from exc

        try:
            value = req.schema_model.model_validate(parsed)
        except ValidationError as exc:
            raise StructuredOutputInvalidError(
                f"schema validation failed: {exc}", profile_name=self._profile.name
            ) from exc

        return StructuredResponse(
            value=value,
            usage=self._usage(data),
            latency_ms=latency_ms,
            profile_name=self._profile.name,
        )
