"""`generate_text` returns text with token counts (contracts/gateway-interface.md §2)."""

from __future__ import annotations

import httpx
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import Message, TextRequest
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider


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


async def test_generate_text_returns_text_with_token_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "hello there"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    provider = OpenAICompatibleLLMProvider(_profile(), transport=httpx.MockTransport(handler))

    response = await provider.generate_text(
        TextRequest(messages=[Message(role="user", content="hi")])
    )

    assert response.text == "hello there"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 4
    assert response.profile_name == "test-llm"
    assert response.latency_ms >= 0
