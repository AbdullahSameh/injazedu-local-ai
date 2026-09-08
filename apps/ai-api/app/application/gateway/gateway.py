"""The gateway facade — the single entry point later milestones import from
(contracts/gateway-interface.md §6, research D-23).

Every call runs: resolve profile → check breaker → acquire lane → attempt (with retry) → release
lane → return, per `contracts/gateway-interface.md` §6 (research D-31…D-33). US6 (T066) adds a
`model_runs` row after the result is determined.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis

from app.application.gateway.accounting import AccountingLike, NullAccountingWriter
from app.application.gateway.breaker import BreakerLike, CircuitBreaker
from app.application.gateway.errors import (
    EmbeddingDimensionMismatchError,
    GatewayError,
    ModelTimeoutError,
    ProviderRejectedError,
)
from app.application.gateway.lanes import Lane, LaneLike
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.providers.embeddings.base import (
    BatchEmbeddingResult,
    EmbeddingProvider,
    EmbeddingResult,
    TextKind,
)
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.providers.llm.base import (
    LLMProvider,
    StructuredRequest,
    StructuredResponse,
    TextRequest,
    TextResponse,
    Usage,
)
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

LLMProviderFactory = Callable[[ModelProfile], LLMProvider]
EmbeddingProviderFactory = Callable[[ModelProfile], EmbeddingProvider]

# Mirror `app.infrastructure.config.Settings`' `GATEWAY_*` defaults — the numeric fallback for
# callers that construct a bare `Gateway(registry)` without wiring their own lane/breaker/Redis
# (every earlier story's tests, `smoke_llm.py`). Production wiring should still pass explicit
# values sourced from `Settings` so an operator's `.env` is the single source of truth.
_DEFAULT_LEASE_TTL_S = 30.0
_DEFAULT_LANE_RENEW_S = 10.0
_DEFAULT_BREAKER_THRESHOLD = 5
_DEFAULT_BREAKER_OPEN_S = 30
_DEFAULT_CALL_TIMEOUT_S = 180.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_BASE_S = 0.5


def _default_redis_client() -> Redis:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url, decode_responses=True)


def _default_llm_provider(profile: ModelProfile) -> LLMProvider:
    if profile.provider == "fake":
        return FakeLLMProvider(profile_name=profile.name)
    return OpenAICompatibleLLMProvider(profile)


def _default_embedding_provider(profile: ModelProfile) -> EmbeddingProvider:
    if profile.provider == "fake":
        return FakeEmbeddingProvider(dim=profile.dim or 768, profile_name=profile.name)
    return OpenAICompatibleEmbeddingProvider(profile)


def _reject_blank_inputs(texts: Sequence[str], *, profile_name: str) -> None:
    for index, text in enumerate(texts):
        if not text.strip():
            raise ProviderRejectedError(
                f"input at index {index} is empty or whitespace-only", profile_name=profile_name
            )


def _assert_dimension(vector: Sequence[float], profile: ModelProfile) -> None:
    if profile.dim is not None and len(vector) != profile.dim:
        raise EmbeddingDimensionMismatchError(
            f"vector width {len(vector)} != profile dim {profile.dim}", profile_name=profile.name
        )


def _override(override: Any | None, default: Any) -> Any:
    return override if override is not None else default


def _generation_params(
    profile: ModelProfile, req: TextRequest | StructuredRequest[Any]
) -> dict[str, Any]:
    """The effective per-call bounds — profile defaults with per-request overrides applied
    (FR-036, research D-34) — canonicalised for `request_digest` (FR-038)."""
    return {
        "num_ctx": _override(req.context_tokens, profile.params.get("num_ctx")),
        "num_predict": _override(req.max_output_tokens, profile.params.get("num_predict")),
        "temperature": _override(req.temperature, profile.params.get("temperature")),
    }


def _text_request_payload(profile: ModelProfile, req: TextRequest) -> dict[str, Any]:
    return {
        "model": profile.model,
        "operation": "generate_text",
        "messages": [m.model_dump(mode="json") for m in req.messages],
        "params": _generation_params(profile, req),
    }


def _structured_request_payload[T: BaseModel](
    profile: ModelProfile, req: StructuredRequest[T]
) -> dict[str, Any]:
    return {
        "model": profile.model,
        "operation": "generate_structured",
        "messages": [m.model_dump(mode="json") for m in req.messages],
        "params": _generation_params(profile, req),
        "schema": req.schema_model.model_json_schema(),
    }


def _embed_request_payload(profile: ModelProfile, text: str, kind: TextKind) -> dict[str, Any]:
    return {
        "model": profile.model,
        "operation": "embed",
        "input": text,
        "params": {"kind": kind},
    }


def _embed_many_request_payload(
    profile: ModelProfile, texts: Sequence[str], kind: TextKind, batch_size: int | None
) -> dict[str, Any]:
    return {
        "model": profile.model,
        "operation": "embed_many",
        "input": list(texts),
        "params": {
            "kind": kind,
            "batch_size": _override(batch_size, profile.params.get("batch_size")),
        },
    }


_GatewayResult = TextResponse | StructuredResponse[Any] | EmbeddingResult | BatchEmbeddingResult


def _usage_of(result: _GatewayResult) -> Usage:
    return result.usage


def _response_payload_of(result: _GatewayResult) -> Mapping[str, Any]:
    return result.model_dump(mode="json")


class Gateway:
    """Resolves the active profile, selects its provider, and calls it through the breaker, the
    machine-wide lane and the retry policy (`contracts/gateway-interface.md` §6)."""

    def __init__(
        self,
        registry: ProfileRegistry,
        *,
        llm_provider_factory: LLMProviderFactory = _default_llm_provider,
        embedding_provider_factory: EmbeddingProviderFactory = _default_embedding_provider,
        llm_lane: LaneLike | None = None,
        embed_lane: LaneLike | None = None,
        breaker: BreakerLike | None = None,
        accounting: AccountingLike | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_base_s: float = _DEFAULT_RETRY_BASE_S,
        call_timeout_s: float = _DEFAULT_CALL_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float], float] = lambda upper: random.uniform(0, upper),
    ) -> None:
        self._registry = registry
        self._llm_provider_factory = llm_provider_factory
        self._embedding_provider_factory = embedding_provider_factory

        default_redis: Redis = _default_redis_client()

        self._llm_lane = llm_lane or Lane(
            default_redis,
            "llm",
            lease_ttl_s=_DEFAULT_LEASE_TTL_S,
            renew_interval_s=_DEFAULT_LANE_RENEW_S,
        )
        self._embed_lane = embed_lane or Lane(
            default_redis,
            "embed",
            lease_ttl_s=_DEFAULT_LEASE_TTL_S,
            renew_interval_s=_DEFAULT_LANE_RENEW_S,
        )
        self._breaker = breaker or CircuitBreaker(
            default_redis,
            threshold=_DEFAULT_BREAKER_THRESHOLD,
            open_s=_DEFAULT_BREAKER_OPEN_S,
        )
        # Unlike the lane/breaker's live-Redis defaults, a bare `Gateway(registry)` records
        # nothing: only explicit wiring may point accounting at a database (see accounting.py).
        self._accounting = accounting or NullAccountingWriter()
        self._max_retries = max_retries
        self._retry_base_s = retry_base_s
        self._call_timeout_s = call_timeout_s
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter

    async def generate_text(self, req: TextRequest) -> TextResponse:
        profile = await self._registry.resolve("llm")
        provider = self._llm_provider_factory(profile)
        return await self._call(
            profile,
            self._llm_lane,
            lambda: provider.generate_text(req),
            operation="generate_text",
            request_payload=_text_request_payload(profile, req),
        )

    async def generate_structured[T: BaseModel](
        self, req: StructuredRequest[T]
    ) -> StructuredResponse[T]:
        profile = await self._registry.resolve("llm")
        provider = self._llm_provider_factory(profile)
        return await self._call(
            profile,
            self._llm_lane,
            lambda: provider.generate_structured(req),
            operation="generate_structured",
            request_payload=_structured_request_payload(profile, req),
        )

    async def embed(self, text: str, kind: TextKind) -> EmbeddingResult:
        profile = await self._registry.resolve("embedding")
        _reject_blank_inputs([text], profile_name=profile.name)
        provider = self._embedding_provider_factory(profile)
        result = await self._call(
            profile,
            self._embed_lane,
            lambda: provider.embed(text, kind),
            operation="embed",
            request_payload=_embed_request_payload(profile, text, kind),
        )
        _assert_dimension(result.vector, profile)
        return result

    async def embed_many(
        self, texts: Sequence[str], kind: TextKind, batch_size: int | None = None
    ) -> BatchEmbeddingResult:
        profile = await self._registry.resolve("embedding")
        _reject_blank_inputs(texts, profile_name=profile.name)
        provider = self._embedding_provider_factory(profile)
        result = await self._call(
            profile,
            self._embed_lane,
            lambda: provider.embed_many(texts, kind, batch_size),
            operation="embed_many",
            request_payload=_embed_many_request_payload(profile, texts, kind, batch_size),
        )
        for vector in result.vectors:
            _assert_dimension(vector, profile)
        return result

    async def _call[R: _GatewayResult](
        self,
        profile: ModelProfile,
        lane: LaneLike,
        call: Callable[[], Awaitable[R]],
        *,
        operation: str,
        request_payload: Mapping[str, Any],
    ) -> R:
        """Times the whole call and records a `model_runs` row after the result is determined,
        success or failure (FR-037, FR-040), around `_execute`'s breaker → lane → retry order.
        A recording failure is the accounting writer's problem, never re-raised here."""
        started = self._clock()
        attempts_made = [0]
        try:
            result = await self._execute(profile, lane, call, attempts_made)
        except GatewayError as exc:
            await self._accounting.record(
                profile=profile,
                operation=operation,
                request_payload=request_payload,
                latency_ms=int((self._clock() - started) * 1000),
                attempts=max(attempts_made[0], 1),
                ok=False,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
            raise

        usage = _usage_of(result)
        await self._accounting.record(
            profile=profile,
            operation=operation,
            request_payload=request_payload,
            latency_ms=int((self._clock() - started) * 1000),
            attempts=attempts_made[0],
            ok=True,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            response_payload=_response_payload_of(result),
        )
        return result

    async def _execute[R](
        self,
        profile: ModelProfile,
        lane: LaneLike,
        call: Callable[[], Awaitable[R]],
        attempts_made: list[int],
    ) -> R:
        """Breaker → lane → retry, in that order, for one logical caller request
        (`contracts/gateway-interface.md` §6). The lane is released on every exit path — success,
        failure, timeout, cancellation — because `Lane.hold` itself guarantees that (FR-034). The
        180 s deadline bounds the whole call, retries and lane waits included, not each attempt
        (research D-31)."""
        await self._breaker.before_call(profile.id, profile_name=profile.name)

        deadline = self._clock() + self._call_timeout_s
        total_attempts = self._max_retries + 1

        for attempt in range(1, total_attempts + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ModelTimeoutError(
                    f"deadline exceeded before attempt {attempt}", profile_name=profile.name
                )
            attempts_made[0] = attempt
            try:
                async with lane.hold(timeout_s=remaining):
                    call_budget = max(deadline - self._clock(), 0.001)
                    try:
                        result = await asyncio.wait_for(call(), timeout=call_budget)
                    except TimeoutError as exc:
                        raise ModelTimeoutError(
                            f"attempt {attempt} exceeded the call deadline",
                            profile_name=profile.name,
                        ) from exc
            except GatewayError as exc:
                if not exc.retryable:
                    raise
                await self._breaker.record_failure(profile.id)
                if attempt >= total_attempts or self._clock() >= deadline:
                    raise
                backoff = self._retry_base_s * (2 ** (attempt - 1))
                sleep_s = min(self._jitter(backoff), max(deadline - self._clock(), 0))
                await self._sleep(sleep_s)
                continue

            await self._breaker.record_success(profile.id)
            return result

        # Unreachable: the loop above always returns or raises.
        raise AssertionError("retry loop exited without returning or raising")
