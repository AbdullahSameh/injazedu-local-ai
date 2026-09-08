"""`FakeEmbeddingProvider` — deterministic hash-derived vectors (research D-39, FR-024,
contracts/gateway-interface.md §7).

Same text, same vector; different text, different vector — real structure for M4's retrieval
tests with no model. Also offers `fail_with` failure injection, so every branch of the
gateway's execution order (`contracts/gateway-interface.md` §6) is reachable offline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.application.gateway.errors import GatewayError
from app.providers.embeddings.base import BatchEmbeddingResult, EmbeddingResult, TextKind
from app.providers.llm.base import Usage

_DEFAULT_PROFILE_NAME = "fake-embedding"


def _hash_vector(text: str, dim: int) -> list[float]:
    normalized = " ".join(text.split()).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return [(digest[i % len(digest)] / 255.0) * 2.0 - 1.0 for i in range(dim)]


class FakeEmbeddingProvider:
    """Satisfies `EmbeddingProvider` with no model runtime (contracts/gateway-interface.md §7)."""

    def __init__(
        self,
        *,
        dim: int = 768,
        fail_with: type[GatewayError] | None = None,
        profile_name: str = _DEFAULT_PROFILE_NAME,
    ) -> None:
        self._dim = dim
        self._fail_with = fail_with
        self._profile_name = profile_name

    def _maybe_fail(self) -> None:
        if self._fail_with is not None:
            raise self._fail_with(
                f"{self._fail_with.__name__} injected by FakeEmbeddingProvider",
                profile_name=self._profile_name,
            )

    async def embed(self, text: str, kind: TextKind) -> EmbeddingResult:
        self._maybe_fail()
        return EmbeddingResult(
            vector=_hash_vector(text, self._dim),
            usage=Usage(prompt_tokens=None, completion_tokens=None),
            profile_name=self._profile_name,
        )

    async def embed_many(
        self, texts: Sequence[str], kind: TextKind, batch_size: int | None = None
    ) -> BatchEmbeddingResult:
        self._maybe_fail()
        return BatchEmbeddingResult(
            vectors=[_hash_vector(text, self._dim) for text in texts],
            usage=Usage(prompt_tokens=None, completion_tokens=None),
            profile_name=self._profile_name,
        )
