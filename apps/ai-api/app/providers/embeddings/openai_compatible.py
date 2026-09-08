"""`OpenAICompatibleEmbeddingProvider` — speaks `{base_url}/embeddings` (research D-24, D-28,
D-29, D-30).

Applies the profile's kind-specific prefix templates, batches internally at
`params.batch_size` (default 32), reorders by the response's `index`, and asserts the
returned width against `model_profiles.dim`. The only module besides `fake.py` allowed to
import `httpx` for the `embedding` role (`make check`, SC-001).

`ollama` and `vllm` share this class unchanged (FR-014): unlike generation, an embedding
request carries no Ollama-specific extension field — `model` and `input` are the whole of
the OpenAI standard's `/embeddings` body — so there is no measured dialect to select on yet.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import httpx
from app.application.gateway.errors import (
    EmbeddingDimensionMismatchError,
    ModelNotAvailableError,
    ProviderAuthError,
    ProviderRejectedError,
    ProviderUnreachableError,
)
from app.domain.model_profile import ModelProfile
from app.providers.embeddings.base import BatchEmbeddingResult, EmbeddingResult, TextKind
from app.providers.llm.base import Usage

_CALL_TIMEOUT_S = 180.0
_DEFAULT_BATCH_SIZE = 32


def _apply_prefix(profile: ModelProfile, text: str, kind: TextKind) -> str:
    key = "prefix_document" if kind == "document" else "prefix_query"
    template = profile.params.get(key)
    if not template:
        return text
    return str(template).format(text=text)


class OpenAICompatibleEmbeddingProvider:
    """Satisfies `EmbeddingProvider` against a real Ollama/vLLM runtime."""

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

    def _assert_width(self, vector: list[float]) -> None:
        if self._profile.dim is not None and len(vector) != self._profile.dim:
            raise EmbeddingDimensionMismatchError(
                f"vector width {len(vector)} != profile dim {self._profile.dim}",
                profile_name=self._profile.name,
            )

    async def _embed_batch(self, texts: Sequence[str], kind: TextKind) -> list[list[float]]:
        prefixed = [_apply_prefix(self._profile, text, kind) for text in texts]
        payload = {"model": self._profile.model, "input": prefixed}
        data = await self._post("/embeddings", payload)

        ordered: list[list[float] | None] = [None] * len(texts)
        for item in data["data"]:
            ordered[item["index"]] = item["embedding"]

        vectors = [v for v in ordered if v is not None]
        for vector in vectors:
            self._assert_width(vector)
        return vectors

    async def embed(self, text: str, kind: TextKind) -> EmbeddingResult:
        vectors = await self._embed_batch([text], kind)
        return EmbeddingResult(
            vector=vectors[0],
            usage=Usage(prompt_tokens=None, completion_tokens=None),
            profile_name=self._profile.name,
        )

    async def embed_many(
        self, texts: Sequence[str], kind: TextKind, batch_size: int | None = None
    ) -> BatchEmbeddingResult:
        resolved_batch_size = (
            batch_size
            if batch_size is not None
            else self._profile.params.get("batch_size", _DEFAULT_BATCH_SIZE)
        )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), resolved_batch_size):
            chunk = texts[start : start + resolved_batch_size]
            vectors.extend(await self._embed_batch(chunk, kind))

        return BatchEmbeddingResult(
            vectors=vectors,
            usage=Usage(prompt_tokens=None, completion_tokens=None),
            profile_name=self._profile.name,
        )
