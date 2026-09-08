"""`LLMProvider` protocol and its request/response models (contracts/gateway-interface.md §1–2).

This module — like every other file directly under `app/providers/` — defines the boundary an
implementation must satisfy. It imports none of `httpx`, `ollama` or `openai` itself; only
`openai_compatible.py` and `fake.py` do (`make check`, SC-001).
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TextRequest(BaseModel):
    messages: list[Message]
    max_output_tokens: int | None = None
    temperature: float | None = None
    context_tokens: int | None = None


class StructuredRequest[T: BaseModel](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[Message]
    schema_model: type[T]
    max_output_tokens: int | None = None
    temperature: float | None = None
    context_tokens: int | None = None


class Usage(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None  # always None for embeddings (probe 6)


class TextResponse(BaseModel):
    text: str
    usage: Usage
    latency_ms: int
    profile_name: str


class StructuredResponse[T: BaseModel](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T
    usage: Usage
    latency_ms: int
    profile_name: str


class LLMProvider(Protocol):
    async def generate_text(self, req: TextRequest) -> TextResponse: ...

    async def generate_structured[T: BaseModel](
        self, req: StructuredRequest[T]
    ) -> StructuredResponse[T]: ...
