"""`classify_message` — the live classification actor (`contracts/classification-pipeline.md`
§1 Q3, §8 F2-F3, tasks.md T036, T053).

Declared on its own queue, `moderation_classify`, consumed only by the dedicated `ai-classifier`
service (one process, one thread) — a classification waiting on the model's one-at-a-time lane
must never hold a worker thread that `default` traffic needs (FR-022, research Finding 4). The
gateway is constructed per task with `max_retries=0` (O1, research Finding 6): a cut-off answer's
retry is never the gateway's — it is `_classify_with_retry`'s own doubling backoff (F2), narrower
than the gateway's retryable set (a `ModelTruncatedError` or `StructuredOutputInvalidError` is
pipeline-final, F3, recorded by `classify_one` itself). Any non-gateway exception propagates to
Dramatiq's own `max_retries=3` (F5), untouched here.
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
    ProviderUnreachableError,
)
from app.application.gateway.accounting import AccountingWriter
from app.application.gateway.breaker import CircuitBreaker
from app.application.gateway.gateway import Gateway
from app.application.gateway.lanes import Lane
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one, record_failure
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import make_engine, make_session_factory

logger = logging.getLogger(__name__)

# F2's transient set, exactly `classification.py`'s own `_TRANSIENT_ERRORS` — re-declared rather
# than imported across the private boundary, since this module's copy is the task-retry policy's
# own closed list, not a re-export of the pipeline's.
_TRANSIENT_ERRORS: tuple[type[GatewayError], ...] = (
    ProviderUnreachableError,
    ModelTimeoutError,
    CircuitOpenError,
)


async def classify_message_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    path: str,
    attempt: int,
) -> str:
    """Wires one gateway per call (O1) and runs `classify_one` — the seam a test replaces with a
    scripted gateway/registry/redis rather than this module's own defaults."""
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
    return await classify_one(
        session_factory,
        gateway,
        registry,
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        path=path,
        attempt=attempt,
    )


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = load_settings()
    return make_session_factory(make_engine(settings))


async def _classify_with_retry(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    path: str,
    attempt: int,
) -> None:
    """F2-F3: runs `classify_message_once` and, on a transient `GatewayError` it re-raises,
    either reschedules this same actor with `attempt + 1` and a doubling delay (`30 s, 60 s, 120 s,
    240 s` at the documented defaults), or — on the last attempt — records one `failed` row naming
    the kind, never retried automatically past `MODERATION_CLASSIFY_MAX_ATTEMPTS` (D-TG-151). A
    test replaces `classify_message_once` itself to exercise this without a real gateway."""
    try:
        await classify_message_once(
            session_factory,
            redis,
            settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path=path,
            attempt=attempt,
        )
    except _TRANSIENT_ERRORS as exc:
        if attempt < settings.moderation_classify_max_attempts:
            delay_ms = settings.moderation_classify_retry_base_s * (2 ** (attempt - 1)) * 1000
            classify_message.send_with_options(
                args=(chat_pk, message_id, path, attempt + 1), delay=delay_ms
            )
            return
        registry = ProfileRegistry(session_factory)
        profile = await registry.resolve("moderation")
        async with session_factory() as session:
            await record_failure(
                session,
                chat_pk=chat_pk,
                message_id=message_id,
                path=path,
                reason=exc.category,
                model_profile_id=profile.id,
            )
            await session.commit()


async def _run(chat_pk: int, message_id: int, path: str, attempt: int) -> None:
    settings = load_settings()
    session_factory = make_session_factory(make_engine(settings))
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await _classify_with_retry(
            session_factory,
            redis,
            settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path=path,
            attempt=attempt,
        )
    finally:
        await redis.aclose()


@dramatiq.actor(queue_name="moderation_classify", max_retries=3)
def classify_message(chat_pk: int, message_id: int, path: str = "live", attempt: int = 1) -> None:
    logger.info("classification requested", extra={"message_id": message_id, "chat_id": chat_pk})
    asyncio.run(_run(chat_pk, message_id, path, attempt))
