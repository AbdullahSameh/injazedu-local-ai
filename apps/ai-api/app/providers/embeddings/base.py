"""`EmbeddingProvider` protocol and its result models (contracts/gateway-interface.md §1–2, §4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from app.providers.llm.base import Usage
from pydantic import BaseModel

TextKind = Literal["document", "query"]


class EmbeddingResult(BaseModel):
    vector: list[float]  # len == profile.dim, guaranteed
    usage: Usage
    profile_name: str


class BatchEmbeddingResult(BaseModel):
    vectors: list[list[float]]  # len == len(texts), input order (FR-020)
    usage: Usage
    profile_name: str


class EmbeddingProvider(Protocol):
    async def embed(self, text: str, kind: TextKind) -> EmbeddingResult: ...

    async def embed_many(
        self, texts: Sequence[str], kind: TextKind, batch_size: int | None = None
    ) -> BatchEmbeddingResult: ...
