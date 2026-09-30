"""M1's gateway, extended four additive ways for TG-M5 (operator item 1 — approved,
data-model.md §6): a `role=` keyword that selects the active profile independently of the
generator; `reasoning_effort` forwarded from a profile's params, never invented; the request
digest of a profile without it byte-identical to before this change; and `model_run_id` carried
on a successful response, `None` from `NullAccountingWriter` (D-TG-130…D-TG-133).

⚠ research **Finding 1**: without the forwarding, every classification answer is cut off by the
installed model's hidden reasoning. A test that only checks role selection passes against that
broken provider — `test_reasoning_effort_is_forwarded_only_when_the_profile_carries_it` and
`test_a_profile_without_reasoning_effort_sends_no_such_key` are the ones that would catch it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from app.application.gateway.accounting import AccountingWriter, compute_request_digest
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.infrastructure.models import model_runs
from app.providers.llm.base import Message, StructuredRequest, TextRequest
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# --- shared test doubles (mirrors tests/gateway/test_accounting.py) ----------------------------


class _InstantLane:
    """Satisfies `LaneLike` with no real wait — these tests are about role/digest/run-id, not
    the lane's own timing (that is `test_lanes.py`'s job)."""

    def __init__(self) -> None:
        self.held = 0

    @asynccontextmanager
    async def hold(self, *, timeout_s: float) -> AsyncIterator[str]:
        self.held += 1
        yield "instant"


class _LenientBreaker:
    """Satisfies `BreakerLike` and never opens."""

    async def before_call(self, profile_id: int, *, profile_name: str) -> None:
        return None

    async def record_success(self, profile_id: int) -> None:
        return None

    async def record_failure(self, profile_id: int) -> None:
        return None


class _Answer(BaseModel):
    text: str


def _text_request(content: str = "hi") -> TextRequest:
    return TextRequest(messages=[Message(role="user", content=content)])


def _gateway(
    registry: ProfileRegistry,
    provider: FakeLLMProvider,
    *,
    llm_lane: _InstantLane,
    embed_lane: _InstantLane,
    accounting: AccountingWriter | None = None,
) -> Gateway:
    kwargs: dict[str, object] = {
        "llm_provider_factory": lambda _p: provider,
        "llm_lane": llm_lane,
        "embed_lane": embed_lane,
        "breaker": _LenientBreaker(),
        "max_retries": 0,
    }
    if accounting is not None:
        kwargs["accounting"] = accounting
    return Gateway(registry, **kwargs)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def run_id_watermark(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Deletes only the `model_runs` rows this file's tests create, tracked by a watermark —
    the table is shared, disposable test-DB state (mirrors `test_accounting.py`'s
    `accounting_cleanup`)."""
    async with gateway_session_factory() as session:
        watermark = (
            await session.execute(text("SELECT COALESCE(MAX(id), 0) FROM model_runs"))
        ).scalar_one()
    yield
    async with gateway_session_factory() as session:
        await session.execute(
            text("DELETE FROM model_runs WHERE id > :watermark"), {"watermark": watermark}
        )
        await session.commit()


# --- role= resolves independently of the generator ----------------------------------------------


@pytest.mark.usefixtures("seeded_profiles")
async def test_default_role_resolves_llm(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    provider = FakeLLMProvider(responses=["hi"])
    gateway = _gateway(registry, provider, llm_lane=_InstantLane(), embed_lane=_InstantLane())

    response = await gateway.generate_text(_text_request())

    assert response.text == "hi"


@pytest.mark.usefixtures("seeded_profiles")
async def test_role_moderation_resolves_the_active_moderation_profile(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    moderation_profile = await registry.resolve("moderation")
    assert moderation_profile.name == "gw-test-moderation-active"

    provider = FakeLLMProvider(responses=["hi"])
    gateway = _gateway(registry, provider, llm_lane=_InstantLane(), embed_lane=_InstantLane())

    response = await gateway.generate_text(
        _text_request(), role="moderation"
    )

    assert response.text == "hi"


@pytest.mark.usefixtures("seeded_profiles")
async def test_a_moderation_role_never_touches_the_embed_lane(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    provider = FakeLLMProvider(responses=["hi"])
    llm_lane = _InstantLane()
    embed_lane = _InstantLane()
    gateway = _gateway(registry, provider, llm_lane=llm_lane, embed_lane=embed_lane)

    await gateway.generate_text(
        _text_request(), role="moderation"
    )
    await gateway.generate_structured(
        StructuredRequest(messages=[Message(role="user", content="hi")], schema_model=_Answer),
        role="moderation",
    )

    assert llm_lane.held == 2
    assert embed_lane.held == 0


# --- reasoning_effort forwarded only when a profile carries it (research Finding 1) ------------


def _profile(*, params: dict[str, object]) -> ModelProfile:
    return ModelProfile(
        id=1,
        name="test-ollama",
        provider="ollama",
        model="test-model",
        role="moderation",
        params=params,
        is_active=True,
        base_url="http://ollama.local/v1",
        dim=None,
        api_key_env=None,
    )


async def _capture_payload(profile: ModelProfile) -> dict[str, object]:
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

    provider = OpenAICompatibleLLMProvider(profile, transport=httpx.MockTransport(handler))
    await provider.generate_structured(
        StructuredRequest(messages=[Message(role="user", content="answer")], schema_model=_Answer)
    )
    return captured["body"]  # type: ignore[return-value]


async def test_reasoning_effort_is_forwarded_only_when_the_profile_carries_it() -> None:
    params = {
        "num_ctx": 2048,
        "num_predict": 128,
        "temperature": 0,
        "reasoning_effort": "none",
    }
    body = await _capture_payload(_profile(params=params))
    assert body["reasoning_effort"] == "none"


async def test_a_profile_without_reasoning_effort_sends_no_such_key() -> None:
    params = {"num_ctx": 2048, "num_predict": 128, "temperature": 0}
    body = await _capture_payload(_profile(params=params))
    assert "reasoning_effort" not in body


# --- request_digest of a profile without reasoning_effort is byte-identical (pinned) -----------

_PINNED_DIGEST_WITHOUT_REASONING_EFFORT = (
    "da994c04ccb02337430f19a144d7058a9f5dc26fad207f6c0334cdd1418ad972"
)


def test_pinned_digest_for_a_profile_without_reasoning_effort_is_unchanged() -> None:
    payload = {
        "model": "fake-llm-active",
        "operation": "generate_text",
        "messages": [{"role": "user", "content": "pin me"}],
        "params": {"num_ctx": None, "num_predict": None, "temperature": None},
    }
    assert compute_request_digest(payload) == _PINNED_DIGEST_WITHOUT_REASONING_EFFORT


@pytest.mark.usefixtures("seeded_profiles", "run_id_watermark")
async def test_a_profile_without_reasoning_effort_writes_the_pinned_digest(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(responses=["ok"])
    gateway = _gateway(
        registry,
        provider,
        llm_lane=_InstantLane(),
        embed_lane=_InstantLane(),
        accounting=accounting,
    )

    await gateway.generate_text(_text_request("pin me"))

    async with gateway_session_factory() as session:
        row = (
            await session.execute(
                select(model_runs)
                .where(model_runs.c.model_profile_id == profile.id)
                .order_by(model_runs.c.id.desc())
                .limit(1)
            )
        ).one()
    assert row.request_digest == _PINNED_DIGEST_WITHOUT_REASONING_EFFORT


# --- model_run_id is carried on a successful response, absent from NullAccountingWriter --------


@pytest.mark.usefixtures("seeded_profiles", "run_id_watermark")
async def test_a_successful_calls_response_carries_the_model_runs_id_just_written(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(responses=["hi"])
    gateway = _gateway(
        registry,
        provider,
        llm_lane=_InstantLane(),
        embed_lane=_InstantLane(),
        accounting=accounting,
    )

    response = await gateway.generate_text(_text_request())

    assert response.model_run_id is not None
    async with gateway_session_factory() as session:
        row = (
            await session.execute(
                select(model_runs).where(model_runs.c.id == response.model_run_id)
            )
        ).one()
    assert row.ok is True


@pytest.mark.usefixtures("seeded_profiles")
async def test_null_accounting_writer_yields_no_model_run_id(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    provider = FakeLLMProvider(responses=["hi"])
    gateway = _gateway(registry, provider, llm_lane=_InstantLane(), embed_lane=_InstantLane())

    response = await gateway.generate_text(_text_request())

    assert response.model_run_id is None
