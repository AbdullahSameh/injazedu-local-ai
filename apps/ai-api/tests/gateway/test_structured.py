"""Structured-output guarantees (contracts/gateway-interface.md §3, research D-26, FR-004,
SC-003)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.application.gateway.errors import ModelTruncatedError, StructuredOutputInvalidError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import Message, StructuredRequest
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _Answer(BaseModel):
    text: str
    confidence: float


def _profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = dict(
        id=1,
        name="test-llm",
        provider="ollama",
        model="test-model",
        role="llm",
        params={},
        is_active=True,
        base_url="http://ollama.local/v1",
        dim=None,
        api_key_env=None,
    )
    defaults.update(overrides)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


def _request() -> StructuredRequest[_Answer]:
    return StructuredRequest(
        messages=[Message(role="user", content="answer")], schema_model=_Answer
    )


@pytest.mark.usefixtures("seeded_profiles")
async def test_structured_round_trip_returns_validated_instance(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    gateway = Gateway(registry)

    response = await gateway.generate_structured(_request())

    assert isinstance(response.value, _Answer)
    assert response.usage is not None
    assert response.latency_ms >= 0
    assert response.profile_name == "gw-test-llm-active"


async def test_finish_reason_length_raises_truncated_never_a_parse_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 8},
            },
        )

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelTruncatedError):
        await provider.generate_structured(_request())


async def test_unparseable_json_raises_structured_output_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "not json"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(StructuredOutputInvalidError):
        await provider.generate_structured(_request())


async def test_schema_invalid_json_raises_structured_output_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"unexpected_field": True})
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    with pytest.raises(StructuredOutputInvalidError):
        await provider.generate_structured(_request())
