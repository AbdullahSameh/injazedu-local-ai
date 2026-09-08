"""Caller code is identical against `ollama` and `vllm` profiles (FR-014).

Both dialects share the OpenAI-standard request shape. The one measured divergence: `options.
num_ctx` is an Ollama extension to the endpoint, not part of that standard, so it is sent only
for `provider == "ollama"` — a `vllm` profile's context length is fixed at server launch, not
per request.
"""

from __future__ import annotations

import json

import httpx
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import Message, StructuredRequest
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from pydantic import BaseModel


class _Answer(BaseModel):
    text: str


def _profile(provider: str) -> ModelProfile:
    return ModelProfile(
        id=1,
        name=f"test-{provider}",
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        role="llm",
        params={"num_ctx": 4096, "num_predict": 256, "temperature": 0.2},
        is_active=True,
        base_url=f"http://{provider}.local/v1",
        dim=None,
        api_key_env=None,
    )


def _request() -> StructuredRequest[_Answer]:
    return StructuredRequest(
        messages=[Message(role="user", content="answer")], schema_model=_Answer
    )


async def _capture_payload(provider: str) -> dict[str, object]:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps({"text": "ok"})}}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider_instance = OpenAICompatibleLLMProvider(
        _profile(provider), transport=httpx.MockTransport(handler)
    )
    await provider_instance.generate_structured(_request())
    return captured["body"]  # type: ignore[return-value]


async def test_ollama_and_vllm_produce_the_same_shape_for_the_shared_fields() -> None:
    ollama_body = await _capture_payload("ollama")
    vllm_body = await _capture_payload("vllm")

    shared_keys = ("model", "messages", "response_format", "max_tokens", "temperature")
    for key in shared_keys:
        assert ollama_body[key] == vllm_body[key], key


async def test_ollama_receives_the_num_ctx_extension_and_vllm_does_not() -> None:
    ollama_body = await _capture_payload("ollama")
    vllm_body = await _capture_payload("vllm")

    assert ollama_body["options"] == {"num_ctx": 4096}
    assert "options" not in vllm_body
