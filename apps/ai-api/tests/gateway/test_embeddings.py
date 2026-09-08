"""Embedding guarantees (contracts/gateway-interface.md §4, research D-29, D-30, FR-018..FR-022)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.application.gateway.errors import EmbeddingDimensionMismatchError, ProviderRejectedError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = dict(
        id=2,
        name="test-embedding",
        provider="ollama",
        model="test-embed-model",
        role="embedding",
        params={
            "prefix_document": "title: none | text: {text}",
            "prefix_query": "task: search result | query: {text}",
        },
        is_active=True,
        base_url="http://ollama.local/v1",
        dim=4,
        api_key_env=None,
    )
    defaults.update(overrides)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


async def test_document_and_query_kinds_apply_different_prefixes() -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["input"] = body["input"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}],
                "usage": {"prompt_tokens": 3},
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(_profile(), transport=httpx.MockTransport(handler))

    await provider.embed("hello", "document")
    assert captured["input"] == ["title: none | text: hello"]

    await provider.embed("hello", "query")
    assert captured["input"] == ["task: search result | query: hello"]


async def test_no_prefix_keys_embeds_raw_text() -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["input"] = body["input"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}],
                "usage": {"prompt_tokens": 1},
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        _profile(params={}), transport=httpx.MockTransport(handler)
    )

    await provider.embed("hello", "document")
    assert captured["input"] == ["hello"]


async def test_batch_order_preserved_by_response_index_not_arrival() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        n = len(body["input"])
        data = [{"index": n - 1 - i, "embedding": [float(n - 1 - i)] * 4} for i in range(n)]
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": n}})

    provider = OpenAICompatibleEmbeddingProvider(
        _profile(params={}), transport=httpx.MockTransport(handler)
    )

    result = await provider.embed_many(["a", "b", "c"], "document")

    assert result.vectors[0][0] == 0.0
    assert result.vectors[1][0] == 1.0
    assert result.vectors[2][0] == 2.0


async def test_oversized_batch_is_split_and_reassembled_in_order() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        inputs: list[str] = body["input"]
        calls.append(len(inputs))
        data = [
            {"index": i, "embedding": [float(ord(text[0]))] * 4} for i, text in enumerate(inputs)
        ]
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": len(inputs)}})

    provider = OpenAICompatibleEmbeddingProvider(
        _profile(params={"batch_size": 2}), transport=httpx.MockTransport(handler)
    )

    texts = ["a", "b", "c", "d", "e"]
    result = await provider.embed_many(texts, "document")

    assert calls == [2, 2, 1]
    assert [v[0] for v in result.vectors] == [float(ord(t)) for t in texts]


@pytest.mark.usefixtures("seeded_profiles")
async def test_embedding_width_mismatch_raises_and_nothing_reaches_the_caller(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    gateway = Gateway(
        registry,
        embedding_provider_factory=lambda profile: FakeEmbeddingProvider(
            dim=3, profile_name=profile.name
        ),
    )

    with pytest.raises(EmbeddingDimensionMismatchError):
        await gateway.embed("hello", "document")


@pytest.mark.usefixtures("seeded_profiles")
async def test_empty_text_raises_provider_rejected_naming_the_index(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    gateway = Gateway(registry)

    with pytest.raises(ProviderRejectedError) as exc_info:
        await gateway.embed("   ", "document")
    assert "0" in str(exc_info.value)


@pytest.mark.usefixtures("seeded_profiles")
async def test_embed_many_rejects_whitespace_only_entry_naming_its_index(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    gateway = Gateway(registry)

    with pytest.raises(ProviderRejectedError) as exc_info:
        await gateway.embed_many(["valid text", "   ", "also valid"], "document")
    assert "1" in str(exc_info.value)
