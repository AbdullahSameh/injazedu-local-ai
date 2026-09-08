"""`api_key_env` resolution (research D-38, contracts/environment.md, FR-015, FR-044)."""

from __future__ import annotations

import httpx
import pytest
from app.application.gateway.errors import ProviderAuthError
from app.domain.model_profile import ModelProfile
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.providers.llm.base import Message, TextRequest
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider


def _llm_profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = dict(
        id=1,
        name="test-llm",
        provider="vllm",
        model="test-model",
        role="llm",
        params={},
        is_active=True,
        base_url="http://vllm.local/v1",
        dim=None,
        api_key_env="TEST_GATEWAY_API_KEY",
    )
    defaults.update(overrides)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


def _echo_headers_transport(captured: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    return httpx.MockTransport(handler)


async def test_api_key_is_resolved_from_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_GATEWAY_API_KEY", raising=False)
    captured: dict[str, str] = {}
    provider = OpenAICompatibleLLMProvider(
        _llm_profile(), transport=_echo_headers_transport(captured)
    )

    # Not set at construction time — the profile only names the variable.
    monkeypatch.setenv("TEST_GATEWAY_API_KEY", "super-secret-value")

    await provider.generate_text(TextRequest(messages=[Message(role="user", content="hi")]))

    assert captured["authorization"] == "Bearer super-secret-value"


async def test_unset_api_key_env_raises_provider_auth_error_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_GATEWAY_API_KEY", raising=False)
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    provider = OpenAICompatibleLLMProvider(_llm_profile(), transport=transport)

    with pytest.raises(ProviderAuthError) as exc_info:
        await provider.generate_text(TextRequest(messages=[Message(role="user", content="hi")]))

    assert "TEST_GATEWAY_API_KEY" in str(exc_info.value)


async def test_embedding_provider_also_resolves_api_key_env_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_GATEWAY_EMBED_KEY", raising=False)
    profile = ModelProfile(
        id=2,
        name="test-embedding",
        provider="vllm",
        model="test-embed-model",
        role="embedding",
        params={},
        is_active=True,
        base_url="http://vllm.local/v1",
        dim=4,
        api_key_env="TEST_GATEWAY_EMBED_KEY",
    )
    provider = OpenAICompatibleEmbeddingProvider(
        profile, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    with pytest.raises(ProviderAuthError) as exc_info:
        await provider.embed("hello", "document")

    assert "TEST_GATEWAY_EMBED_KEY" in str(exc_info.value)
