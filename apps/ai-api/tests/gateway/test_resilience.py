"""Retry policy, the whole-call deadline, and the circuit breaker (research D-31, D-32,
contracts/gateway-interface.md §5-6, T054-T056).

Retry/deadline tests (T054, T055) drive `Gateway._call` with an instant fake lane and an
injected clock/sleep, isolating the orchestration logic from `Lane`'s own Redis timing — that
part is `test_lanes.py`'s job. The breaker test (T056) exercises the real `CircuitBreaker` against
namespaced Redis, because the property under test — caller errors never count toward the trip —
is a decision `Gateway._call` makes about *which* errors reach `record_failure`.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.application.gateway.breaker import CircuitBreaker
from app.application.gateway.errors import (
    CircuitOpenError,
    GatewayError,
    ModelTimeoutError,
    ProviderRejectedError,
    ProviderUnreachableError,
)
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.providers.llm.base import Message, TextRequest, TextResponse, Usage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class _InstantLane:
    """Satisfies `LaneLike` with no real wait — isolates retry/deadline tests from Redis."""

    @asynccontextmanager
    async def hold(self, *, timeout_s: float) -> AsyncIterator[str]:
        yield "instant"


class _LenientBreaker:
    """Satisfies `BreakerLike` and never opens — isolates retry/deadline tests from the breaker."""

    def __init__(self) -> None:
        self.failures: list[int] = []
        self.successes: list[int] = []

    async def before_call(self, profile_id: int, *, profile_name: str) -> None:
        return None

    async def record_success(self, profile_id: int) -> None:
        self.successes.append(profile_id)

    async def record_failure(self, profile_id: int) -> None:
        self.failures.append(profile_id)


class _FailNTimesProvider:
    """Fails with `error` for its first `fail_times` calls, then returns `response`."""

    def __init__(
        self, *, fail_times: int, error: type[GatewayError] = ProviderUnreachableError
    ) -> None:
        self._remaining_failures = fail_times
        self._error = error
        self.calls = 0

    async def generate_text(self, req: TextRequest) -> TextResponse:
        self.calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise self._error("injected failure", profile_name="test-llm")
        return TextResponse(
            text="ok",
            usage=Usage(prompt_tokens=1, completion_tokens=1),
            latency_ms=0,
            profile_name="test-llm",
        )


def _profile(**overrides: object) -> ModelProfile:
    defaults: dict[str, object] = dict(
        id=101,
        name="test-llm",
        provider="fake",
        model="test-model",
        role="llm",
        params={},
        is_active=True,
        base_url=None,
        dim=None,
        api_key_env=None,
    )
    defaults.update(overrides)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


class _FakeClock:
    """A controllable monotonic clock: `sleep` advances it instead of really waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeRegistry:
    """Satisfies the one method `Gateway` calls on a `ProfileRegistry` — always resolves to the
    same profile, so these tests can control failures at the provider instead."""

    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile

    async def resolve(self, role: str) -> ModelProfile:
        return self._profile


def _gateway(
    profile: ModelProfile,
    provider: _FailNTimesProvider,
    *,
    clock: _FakeClock,
    breaker: object,
    max_retries: int = 2,
    retry_base_s: float = 0.01,
    call_timeout_s: float = 5.0,
) -> Gateway:
    return Gateway(
        _FakeRegistry(profile),  # type: ignore[arg-type]
        llm_provider_factory=lambda _p: provider,  # type: ignore[arg-type,return-value]
        llm_lane=_InstantLane(),
        embed_lane=_InstantLane(),
        breaker=breaker,  # type: ignore[arg-type]
        max_retries=max_retries,
        retry_base_s=retry_base_s,
        call_timeout_s=call_timeout_s,
        clock=clock.clock,
        sleep=clock.sleep,
        jitter=lambda upper: upper,  # deterministic: full jitter's upper bound, every time
    )


def _request() -> TextRequest:
    return TextRequest(messages=[Message(role="user", content="hi")])


# --- T054: retry policy ------------------------------------------------------------------


async def test_retries_a_retryable_failure_up_to_max_retries_then_succeeds() -> None:
    profile = _profile()
    provider = _FailNTimesProvider(fail_times=2)
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=_LenientBreaker(), max_retries=2)

    response = await gateway.generate_text(_request())

    assert response.text == "ok"
    assert provider.calls == 3  # 1 initial attempt + 2 retries


async def test_exhausting_max_retries_raises_the_last_error() -> None:
    profile = _profile()
    provider = _FailNTimesProvider(fail_times=10)  # never succeeds
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=_LenientBreaker(), max_retries=2)

    with pytest.raises(ProviderUnreachableError):
        await gateway.generate_text(_request())

    assert provider.calls == 3  # 1 initial attempt + 2 retries, never a 4th


async def test_a_non_retryable_error_is_never_retried() -> None:
    profile = _profile()
    provider = _FailNTimesProvider(fail_times=10, error=ProviderRejectedError)
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=_LenientBreaker(), max_retries=2)

    with pytest.raises(ProviderRejectedError):
        await gateway.generate_text(_request())

    assert provider.calls == 1


async def test_retry_backoff_is_jittered_and_grows_exponentially() -> None:
    profile = _profile()
    provider = _FailNTimesProvider(fail_times=2)
    clock = _FakeClock()
    gateway = _gateway(
        profile, provider, clock=clock, breaker=_LenientBreaker(), max_retries=2, retry_base_s=0.5
    )

    await gateway.generate_text(_request())

    # jitter() is stubbed to return its upper bound deterministically: 0.5*2^0, then 0.5*2^1.
    assert clock.sleeps == pytest.approx([0.5, 1.0])


# --- T055: the deadline bounds the whole call, retries and lane wait included ------------


async def test_deadline_is_not_reset_per_attempt() -> None:
    profile = _profile()
    provider = _FailNTimesProvider(fail_times=10, error=ProviderUnreachableError)
    clock = _FakeClock()
    # A tight deadline that the backoff schedule (0.5s, 1.0s, ...) will blow through well before
    # `max_retries` is exhausted, proving the bound is on the call, not on each attempt.
    gateway = _gateway(
        profile,
        provider,
        clock=clock,
        breaker=_LenientBreaker(),
        max_retries=5,
        retry_base_s=0.5,
        call_timeout_s=1.2,
    )

    with pytest.raises(ModelTimeoutError):
        await gateway.generate_text(_request())

    assert provider.calls < 6  # never got anywhere close to all 6 attempts
    assert clock.now >= 1.2  # the fake clock only advances via `sleep` — proves it was consulted


# --- T056: the breaker -------------------------------------------------------------------


def _breaker(namespace: str, *, threshold: int = 3, open_s: int = 30) -> CircuitBreaker:
    redis = Redis.from_url(_REDIS_URL, decode_responses=True)
    return CircuitBreaker(
        redis, threshold=threshold, open_s=open_s, key_prefix=f"ai:gw:{namespace}:breaker"
    )


async def test_breaker_opens_after_threshold_consecutive_retryable_failures_and_fails_fast(
    gateway_redis_namespace: str,
) -> None:
    profile = _profile(id=202)
    breaker = _breaker(gateway_redis_namespace, threshold=3)
    provider = _FailNTimesProvider(fail_times=100, error=ProviderUnreachableError)
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=breaker, max_retries=0)

    for _ in range(3):
        with pytest.raises(ProviderUnreachableError):
            await gateway.generate_text(_request())

    started = time.monotonic()
    with pytest.raises(CircuitOpenError):
        await gateway.generate_text(_request())
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert provider.calls == 3  # the 4th call never reached the provider


async def test_caller_errors_never_count_toward_the_trip(gateway_redis_namespace: str) -> None:
    profile = _profile(id=203)
    breaker = _breaker(gateway_redis_namespace, threshold=2)
    provider = _FailNTimesProvider(fail_times=100, error=ProviderRejectedError)
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=breaker, max_retries=0)

    for _ in range(5):
        with pytest.raises(ProviderRejectedError):
            await gateway.generate_text(_request())

    # A caller error never opens the breaker — a 6th call still reaches the provider.
    with pytest.raises(ProviderRejectedError):
        await gateway.generate_text(_request())
    assert provider.calls == 6


async def test_half_open_trial_closes_the_breaker_on_success(
    gateway_redis_namespace: str,
) -> None:
    profile = _profile(id=204)
    breaker = _breaker(gateway_redis_namespace, threshold=2, open_s=1)
    provider = _FailNTimesProvider(fail_times=2, error=ProviderUnreachableError)
    clock = _FakeClock()
    gateway = _gateway(profile, provider, clock=clock, breaker=breaker, max_retries=0)

    for _ in range(2):
        with pytest.raises(ProviderUnreachableError):
            await gateway.generate_text(_request())

    with pytest.raises(CircuitOpenError):
        await gateway.generate_text(_request())

    await asyncio.sleep(1.1)  # real sleep — waiting out the breaker's own `open_s`, not the fake

    response = await gateway.generate_text(_request())  # the half-open trial
    assert response.text == "ok"

    # The trial's success reset the failure count — the breaker is fully closed, not still
    # counting toward a fresh trip.
    response_again = await gateway.generate_text(_request())
    assert response_again.text == "ok"


@pytest.mark.usefixtures("seeded_profiles")
async def test_resilience_is_wired_through_the_real_gateway_construction(
    gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A smoke check that `Gateway(registry)`'s *default* wiring — no injected lane/breaker —
    still runs a call end to end through the real (namespaced-by-default) breaker and lane."""
    registry = ProfileRegistry(gateway_session_factory)
    gateway = Gateway(registry)

    response = await gateway.generate_text(_request())

    assert response.profile_name == "gw-test-llm-active"
