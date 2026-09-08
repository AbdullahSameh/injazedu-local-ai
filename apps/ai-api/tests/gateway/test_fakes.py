"""Fakes are deterministic, schema-valid by default, and fail on demand (research D-39, FR-023
..FR-025, contracts/gateway-interface.md §7)."""

from __future__ import annotations

from enum import StrEnum

import pytest
from app.application.gateway.errors import (
    CircuitOpenError,
    EmbeddingDimensionMismatchError,
    ModelNotAvailableError,
    ModelTimeoutError,
    ModelTruncatedError,
    NoActiveProfileError,
    ProviderAuthError,
    ProviderRejectedError,
    ProviderUnreachableError,
    StructuredOutputInvalidError,
)
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.llm.base import Message, StructuredRequest, TextRequest
from app.providers.llm.fake import FakeLLMProvider
from pydantic import BaseModel

_ALL_CATEGORIES = (
    ProviderUnreachableError,
    ModelNotAvailableError,
    ProviderRejectedError,
    ProviderAuthError,
    ModelTruncatedError,
    StructuredOutputInvalidError,
    EmbeddingDimensionMismatchError,
    ModelTimeoutError,
    CircuitOpenError,
    NoActiveProfileError,
)


class _Grade(StrEnum):
    A = "A"
    B = "B"


class _SubAnswer(BaseModel):
    label: str
    score: float


class _Answer(BaseModel):
    text: str
    confidence: float
    grade: _Grade
    sub: _SubAnswer
    tags: list[str]
    note: str | None = None


def _request() -> StructuredRequest[_Answer]:
    return StructuredRequest(
        messages=[Message(role="user", content="answer")], schema_model=_Answer
    )


async def test_structured_synthesis_is_deterministic_across_repeated_calls() -> None:
    provider = FakeLLMProvider()

    first = await provider.generate_structured(_request())
    second = await provider.generate_structured(_request())

    assert first.value == second.value


async def test_embedding_fake_is_deterministic_same_text_same_vector() -> None:
    provider = FakeEmbeddingProvider(dim=16)

    first = await provider.embed("hello world", "document")
    second = await provider.embed("hello world", "document")

    assert first.vector == second.vector


async def test_embedding_fake_gives_different_vectors_for_different_text() -> None:
    provider = FakeEmbeddingProvider(dim=16)

    a = await provider.embed("hello", "document")
    b = await provider.embed("goodbye", "document")

    assert a.vector != b.vector


async def test_default_structured_answer_is_schema_valid_for_a_nested_schema() -> None:
    provider = FakeLLMProvider()

    response = await provider.generate_structured(_request())

    assert isinstance(response.value, _Answer)
    assert isinstance(response.value.sub, _SubAnswer)
    assert isinstance(response.value.grade, _Grade)
    assert isinstance(response.value.tags, list)


@pytest.mark.parametrize("category", _ALL_CATEGORIES)
async def test_fail_with_raises_every_category_for_generate_text(
    category: type[Exception],
) -> None:
    provider = FakeLLMProvider(fail_with=category)  # type: ignore[arg-type]

    with pytest.raises(category):
        await provider.generate_text(TextRequest(messages=[Message(role="user", content="hi")]))


@pytest.mark.parametrize("category", _ALL_CATEGORIES)
async def test_fail_with_raises_every_category_for_generate_structured(
    category: type[Exception],
) -> None:
    provider = FakeLLMProvider(fail_with=category)  # type: ignore[arg-type]

    with pytest.raises(category):
        await provider.generate_structured(_request())


@pytest.mark.parametrize("category", _ALL_CATEGORIES)
async def test_fail_with_raises_every_category_for_embed(category: type[Exception]) -> None:
    provider = FakeEmbeddingProvider(fail_with=category)  # type: ignore[arg-type]

    with pytest.raises(category):
        await provider.embed("hello", "document")


@pytest.mark.parametrize("category", _ALL_CATEGORIES)
async def test_fail_with_raises_every_category_for_embed_many(category: type[Exception]) -> None:
    provider = FakeEmbeddingProvider(fail_with=category)  # type: ignore[arg-type]

    with pytest.raises(category):
        await provider.embed_many(["hello", "world"], "document")


async def test_scripted_text_response_queue_is_consumed_in_order() -> None:
    provider = FakeLLMProvider(responses=["first", "second"])

    first = await provider.generate_text(TextRequest(messages=[Message(role="user", content="hi")]))
    second = await provider.generate_text(
        TextRequest(messages=[Message(role="user", content="hi")])
    )
    third = await provider.generate_text(TextRequest(messages=[Message(role="user", content="hi")]))

    assert first.text == "first"
    assert second.text == "second"
    assert third.text == "fake response"  # queue exhausted — falls back to the default


async def test_scripted_structured_response_queue_returns_the_configured_instance() -> None:
    scripted = _Answer(
        text="scripted", confidence=0.9, grade=_Grade.B, sub=_SubAnswer(label="x", score=1.0),
        tags=["a"],
    )
    provider = FakeLLMProvider(responses=[scripted])

    response = await provider.generate_structured(_request())

    assert response.value == scripted
