"""The transport failure map (contracts/gateway-interface.md §5, research D-27, probe 4)."""

from __future__ import annotations

import httpx
import pytest
from app.application.gateway.errors import (
    ModelNotAvailableError,
    ProviderAuthError,
    ProviderRejectedError,
    ProviderUnreachableError,
)
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import Message, TextRequest
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider


def _profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = dict(
        id=1,
        name="test-llm",
        provider="ollama",
        model="missing-model",
        role="llm",
        params={},
        is_active=True,
        base_url="http://ollama.local/v1",
        dim=None,
        api_key_env=None,
    )
    defaults.update(overrides)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


def _request() -> TextRequest:
    return TextRequest(messages=[Message(role="user", content="hi")])


async def test_connection_refused_raises_provider_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderUnreachableError):
        await provider.generate_text(_request())


async def test_404_not_found_raises_model_not_available_naming_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {"message": "model 'missing-model' not found", "type": "not_found_error"}
            },
        )

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelNotAvailableError) as exc_info:
        await provider.generate_text(_request())
    assert "missing-model" in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 422])
async def test_bad_request_raises_provider_rejected(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "bad request"}})

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderRejectedError):
        await provider.generate_text(_request())


@pytest.mark.parametrize("status", [401, 403])
async def test_unauthorized_raises_provider_auth_error(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="unauthorized")

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderAuthError):
        await provider.generate_text(_request())
