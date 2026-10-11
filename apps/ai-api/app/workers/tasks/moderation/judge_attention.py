"""`judge_attention` — the live attention judgement actor (TG-M5.3,
`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §1 J2-J3, §8 F1;
`tasks.md` T035).

Declared on its own queue, `moderation_attention`. The current deployment (D-TG-187, deployment
policy rather than contract) has the one-thread `ai-classifier` consume it beside
`moderation_classify`; its `priority=0`, against `classify_message`'s `10`, makes Attention run
first whenever both wait on that worker (research Finding 18). The gateway is constructed per task
with `max_retries=0` (D-TG-188, research Finding 6), exactly as `classify_message_once` does: a
transient failure's retry is `_judge_with_retry`'s own doubling backoff, on the classifier's
settings, and a cut-off or malformed answer is final, recorded by `judge_one` itself (F2). Any
non-gateway exception propagates to Dramatiq's own `max_retries=3`, untouched here.

Live only (L1): `derive_message` is its one sender, so `path` is always `live`.
"""

from __future__ import annotations

import asyncio
import logging

import dramatiq
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.gateway import (
    CircuitOpenError,
    GatewayError,
    ModelTimeoutError,
    NoActiveProfileError,
    ProviderUnreachableError,
)
from app.application.gateway.accounting import AccountingWriter
from app.application.gateway.breaker import CircuitBreaker
from app.application.gateway.gateway import Gateway
from app.application.gateway.lanes import Lane
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.attention_judgement import judge_one, record_attention_failure
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import worker_session_factory

logger = logging.getLogger(__name__)

# F1's transient set, exactly `attention_judgement.py`'s own `_TRANSIENT_ERRORS` — re-declared
# rather than imported across the private boundary, as `classify_message.py` does.
_TRANSIENT_ERRORS: tuple[type[GatewayError], ...] = (
    ProviderUnreachableError,
    ModelTimeoutError,
    CircuitOpenError,
)


async def judge_attention_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    attempt: int,
) -> str:
    """Wires one gateway per call (J2) and runs `judge_one`: the seam a test replaces."""
    registry = ProfileRegistry(session_factory)
    gateway = Gateway(
        registry,
        llm_lane=Lane(
            redis,
            "llm",
            lease_ttl_s=settings.gateway_lane_lease_ttl_s,
            renew_interval_s=settings.gateway_lane_renew_s,
        ),
        breaker=CircuitBreaker(
            redis,
            threshold=settings.gateway_breaker_threshold,
            open_s=settings.gateway_breaker_open_s,
        ),
        accounting=AccountingWriter(
            session_factory, capture_payloads=settings.gateway_capture_payloads
        ),
        max_retries=0,
        call_timeout_s=settings.gateway_call_timeout_s,
    )
    return await judge_one(
        session_factory,
        gateway,
        registry,
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        attempt=attempt,
    )


async def _judge_with_retry(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    attempt: int,
) -> None:
    """F1: runs `judge_attention_once` and, on a transient `GatewayError` it re-raises, either
    reschedules this actor with `attempt + 1` and a doubling delay (`MODERATION_CLASSIFY_RETRY_
    BASE_S × 2^(attempt−1)`), or, on the last attempt (`MODERATION_CLASSIFY_MAX_ATTEMPTS`), records
    one `failed` attention attempt naming the kind and the active attention profile."""
    try:
        await judge_attention_once(
            session_factory,
            redis,
            settings,
            chat_pk=chat_pk,
            message_id=message_id,
            attempt=attempt,
        )
    except _TRANSIENT_ERRORS as exc:
        if attempt < settings.moderation_classify_max_attempts:
            delay_ms = settings.moderation_classify_retry_base_s * (2 ** (attempt - 1)) * 1000
            judge_attention.send_with_options(
                args=(chat_pk, message_id, attempt + 1), delay=delay_ms
            )
            return
        try:
            profile = await ProfileRegistry(session_factory).resolve("attention")
        except NoActiveProfileError:
            # Deactivated mid-retry: a failure must name a profile (`ck_attention_attempt_profile`),
            # and with none active nothing more is judged, so nothing is recorded.
            return
        async with session_factory() as session:
            await record_attention_failure(
                session,
                chat_pk=chat_pk,
                message_id=message_id,
                path="live",
                reason=exc.category,
                model_profile_id=profile.id,
            )
            await session.commit()


async def _run(chat_pk: int, message_id: int, attempt: int) -> None:
    settings = load_settings()
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with worker_session_factory(settings) as session_factory:
            await _judge_with_retry(
                session_factory,
                redis,
                settings,
                chat_pk=chat_pk,
                message_id=message_id,
                attempt=attempt,
            )
    finally:
        await redis.aclose()


@dramatiq.actor(queue_name="moderation_attention", max_retries=3, priority=0)
def judge_attention(chat_pk: int, message_id: int, attempt: int = 1) -> None:
    logger.info(
        "attention judgement requested", extra={"message_id": message_id, "chat_id": chat_pk}
    )
    asyncio.run(_run(chat_pk, message_id, attempt))
