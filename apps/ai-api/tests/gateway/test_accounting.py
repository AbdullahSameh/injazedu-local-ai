"""Call accounting: one `model_runs` row per call, redacted by default (data-model.md §2,
contracts/gateway-interface.md §6, FR-037…FR-040, T061-T064).

Drives the real `Gateway` with an instant fake lane/breaker (isolating these tests from Redis
timing — that is `test_lanes.py`'s and `test_resilience.py`'s job) and a real `AccountingWriter`
against the namespaced `injaz_ai_test` database, so the rows asserted on are the ones the gateway
actually wrote.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from app.application.gateway.accounting import AccountingWriter, compute_request_digest
from app.application.gateway.errors import ProviderRejectedError, ProviderUnreachableError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.infrastructure.models import model_runs
from app.providers.llm.base import Message, TextRequest
from app.providers.llm.fake import FakeLLMProvider
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _InstantLane:
    """Satisfies `LaneLike` with no real wait — these tests are about accounting, not the lane."""

    @asynccontextmanager
    async def hold(self, *, timeout_s: float) -> AsyncIterator[str]:
        yield "instant"


class _LenientBreaker:
    """Satisfies `BreakerLike` and never opens."""

    async def before_call(self, profile_id: int, *, profile_name: str) -> None:
        return None

    async def record_success(self, profile_id: int) -> None:
        return None

    async def record_failure(self, profile_id: int) -> None:
        return None


def _request(content: str = "hi") -> TextRequest:
    return TextRequest(messages=[Message(role="user", content=content)])


def _gateway(
    registry: ProfileRegistry,
    provider: FakeLLMProvider,
    *,
    accounting: AccountingWriter,
) -> Gateway:
    return Gateway(
        registry,
        llm_provider_factory=lambda _p: provider,
        llm_lane=_InstantLane(),
        embed_lane=_InstantLane(),
        breaker=_LenientBreaker(),
        accounting=accounting,
        max_retries=0,
    )


@pytest_asyncio.fixture
async def accounting_cleanup(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Deletes only the rows this file's tests create, tracked by a watermark — `model_runs` is
    shared, disposable test-DB state, not something these tests own outright."""
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


async def _latest_run(
    session_factory: async_sessionmaker[AsyncSession], model_profile_id: int
) -> object:
    async with session_factory() as session:
        result = await session.execute(
            select(model_runs)
            .where(model_runs.c.model_profile_id == model_profile_id)
            .order_by(model_runs.c.id.desc())
            .limit(1)
        )
        row = result.first()
    assert row is not None, "expected a model_runs row to have been written"
    return row


# --- T061: every call, successful or failed, writes exactly one row ----------------------------


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_a_successful_call_writes_one_row_with_tokens_duration_and_outcome(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(responses=["hello"])
    gateway = _gateway(registry, provider, accounting=accounting)

    response = await gateway.generate_text(_request())

    row = await _latest_run(gateway_session_factory, profile.id)
    assert response.text == "hello"
    assert row.model_profile_id == profile.id
    assert row.operation == "generate_text"
    assert row.ok is True
    assert row.attempts == 1
    assert row.latency_ms >= 0
    assert row.prompt_tokens == 0
    assert row.completion_tokens == 0
    assert row.error_type is None


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_a_failed_call_writes_one_row_naming_the_error(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(fail_with=ProviderRejectedError)
    gateway = _gateway(registry, provider, accounting=accounting)

    with pytest.raises(ProviderRejectedError):
        await gateway.generate_text(_request())

    row = await _latest_run(gateway_session_factory, profile.id)
    assert row.ok is False
    assert row.operation == "generate_text"
    assert row.attempts == 1
    assert row.error_type == "ProviderRejectedError"
    assert row.error_detail is not None
    assert row.prompt_tokens is None
    assert row.completion_tokens is None


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_a_retryable_failure_that_eventually_fails_records_every_attempt(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(fail_with=ProviderUnreachableError)
    gateway = Gateway(
        registry,
        llm_provider_factory=lambda _p: provider,
        llm_lane=_InstantLane(),
        embed_lane=_InstantLane(),
        breaker=_LenientBreaker(),
        accounting=accounting,
        max_retries=2,
        retry_base_s=0.0,
    )

    with pytest.raises(ProviderUnreachableError):
        await gateway.generate_text(_request())

    row = await _latest_run(gateway_session_factory, profile.id)
    assert row.ok is False
    assert row.attempts == 3  # 1 initial attempt + 2 retries
    assert row.error_type == "ProviderUnreachableError"


# --- T062: redaction ----------------------------------------------------------------------------


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_capture_payloads_off_by_default_stores_no_request_or_response_text(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)
    provider = FakeLLMProvider(responses=["a secret answer"])
    gateway = _gateway(registry, provider, accounting=accounting)

    await gateway.generate_text(_request(content="a copyrighted question"))

    row = await _latest_run(gateway_session_factory, profile.id)
    assert row.request_payload is None
    assert row.response_payload is None
    assert row.request_digest is not None  # the fingerprint is written regardless


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_capture_payloads_on_stores_both_request_and_response_text(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=True)
    provider = FakeLLMProvider(responses=["a secret answer"])
    gateway = _gateway(registry, provider, accounting=accounting)

    await gateway.generate_text(_request(content="a copyrighted question"))

    row = await _latest_run(gateway_session_factory, profile.id)
    assert row.request_payload is not None
    assert row.request_payload["messages"][0]["content"] == "a copyrighted question"
    assert row.response_payload is not None
    assert row.response_payload["text"] == "a secret answer"


# --- T063: request_digest is a stable fingerprint -----------------------------------------------


@pytest.mark.usefixtures("seeded_profiles", "accounting_cleanup")
async def test_identical_requests_produce_identical_digests_and_different_ones_do_not(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = ProfileRegistry(gateway_session_factory)
    profile = await registry.resolve("llm")
    accounting = AccountingWriter(gateway_session_factory, capture_payloads=False)

    gateway_a = _gateway(registry, FakeLLMProvider(responses=["r1"]), accounting=accounting)
    await gateway_a.generate_text(_request(content="same question"))
    digest_a = (await _latest_run(gateway_session_factory, profile.id)).request_digest

    gateway_b = _gateway(registry, FakeLLMProvider(responses=["r2"]), accounting=accounting)
    await gateway_b.generate_text(_request(content="same question"))
    digest_b = (await _latest_run(gateway_session_factory, profile.id)).request_digest

    gateway_c = _gateway(registry, FakeLLMProvider(responses=["r3"]), accounting=accounting)
    await gateway_c.generate_text(_request(content="a different question"))
    digest_c = (await _latest_run(gateway_session_factory, profile.id)).request_digest

    assert digest_a == digest_b
    assert digest_a != digest_c


def test_compute_request_digest_is_order_independent_and_content_sensitive() -> None:
    payload = {
        "model": "m",
        "operation": "generate_text",
        "messages": [{"role": "user", "content": "hi"}],
    }
    reordered = {
        "operation": "generate_text",
        "messages": [{"content": "hi", "role": "user"}],
        "model": "m",
    }
    different = {**payload, "model": "other"}

    assert compute_request_digest(payload) == compute_request_digest(reordered)
    assert compute_request_digest(payload) != compute_request_digest(different)


# --- T064: a recording failure is logged and swallowed, the call's own result is unaffected -----


class _FakeRegistry:
    """Resolves to a fixed profile with no database round trip — these tests exercise a *broken*
    accounting session, so profile resolution must not go through the same (real) database."""

    async def resolve(self, role: str) -> ModelProfile:
        return ModelProfile(
            id=999,
            name="acct-test-llm",
            provider="fake",
            model="fake-model",
            role="llm",
            params={},
            is_active=True,
        )


class _BrokenSession:
    async def __aenter__(self) -> _BrokenSession:
        raise RuntimeError("accounting database unavailable")

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _broken_session_factory() -> _BrokenSession:
    return _BrokenSession()


async def test_a_recording_failure_is_logged_and_swallowed_and_never_fails_the_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    accounting = AccountingWriter(_broken_session_factory, capture_payloads=False)  # type: ignore[arg-type]
    provider = FakeLLMProvider(responses=["still works"])
    gateway = _gateway(_FakeRegistry(), provider, accounting=accounting)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger="app.application.gateway.accounting"):
        response = await gateway.generate_text(_request())

    assert response.text == "still works"
    assert any(
        "failed to record model_runs row" in record.message for record in caplog.records
    ), "the recording failure must be visible in the logs (FR-040)"
