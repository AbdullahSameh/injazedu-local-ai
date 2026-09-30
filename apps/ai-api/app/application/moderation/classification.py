"""`classify_one` — the classification pipeline's one write path
(`contracts/classification-pipeline.md` §3-§7, `tasks.md` T034-T035, T056).

Claims the message in Redis (I3), checks idempotency (I1-I2), resolves eligibility (E1-E8) and
either records an exclusion or builds the model's input, calls the gateway with `role="moderation"`
(O1-O2), range-checks and quantises the answer (O3-O4), routes it (R1-R6) and inserts the
prediction (O5-O6); when the inserted prediction's route is `incident`, opens one in the same
transaction (§7 A1-A6) — one transaction per outcome either way. Never retries a transient failure
itself: US3 (T053) adds the task-level retry. The redacted string is bound only to `redacted_text`,
matching `scripts/check.sh` check 4's whitelist, and is never passed to a logger (pipeline P5, N6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.gateway import (
    CircuitOpenError,
    Gateway,
    GatewayError,
    Message,
    ModelTimeoutError,
    NoActiveProfileError,
    ProviderUnreachableError,
    StructuredRequest,
)
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.incidents import insert_incident
from app.application.moderation.text import redact
from app.domain.moderation.classification import (
    TAXONOMY_VERSION,
    MessageFacts,
    Prediction,
    eligibility,
    quantise,
    route_prediction,
)
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
    telegram_chats,
    telegram_messages,
    telegram_updates,
)

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "classify_v1"
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "moderation" / "classify_v1.md"
_INSTRUCTION = _PROMPT_PATH.read_text(encoding="utf-8")

_CLAIM_PREFIX = "ai:mod:classify:msg"

# Compare-and-delete, mirroring `app/application/gateway/lanes.py`'s `_RELEASE_SCRIPT`: only the
# holder's own token can clear its claim, never a delayed release racing a reclaim by someone else.
_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
end
return 1
"""

# F2's transient set (pipeline §8) — deliberately narrower than `GatewayError.retryable`
# (`ModelTruncatedError` and `StructuredOutputInvalidError` are gateway-retryable but pipeline-
# final: the classifier's own gateway runs with `max_retries=0`, so a cut-off answer reaches here
# as a raised exception, and F3 records it as a failure rather than re-raising it for the task to
# retry).
_TRANSIENT_ERRORS: tuple[type[GatewayError], ...] = (
    ProviderUnreachableError,
    ModelTimeoutError,
    CircuitOpenError,
)


class MessageClassificationResult(BaseModel):
    """The model's structured answer (pipeline §4). No schema bounds on `confidence` — O3 range-
    checks it in the application layer so an out-of-range answer is a recorded failure, not a
    validation error indistinguishable from a malformed one."""

    category: Literal[
        "QUESTION_COURSE",
        "QUESTION_ACCESS",
        "COMPLAINT",
        "CHITCHAT",
        "SPAM_OR_AD",
        "ABUSE",
        "OTHER",
    ]
    needs_response: bool
    needs_moderation: bool
    severity: Literal["none", "low", "medium", "high"]
    confidence: float


def build_model_input(text: str) -> list[Message]:
    """`[system = classify_v1.md, user = redact(text)]` (pipeline P2-P3) — no sender, group,
    time or neighbouring message. The redacted string is named `redacted_text` only in this
    function's own scope, never logged."""
    redacted_text = redact(text)
    return [
        Message(role="system", content=_INSTRUCTION),
        Message(role="user", content=redacted_text),
    ]


@asynccontextmanager
async def claim(
    redis: Redis,
    chat_pk: int,
    message_id: int,
    ttl_ms: int,
    prefix: str = _CLAIM_PREFIX,
) -> AsyncIterator[bool]:
    """`SET … PX … NX` under a random token, released only by its own holder (I3). Yields whether
    the claim was acquired — the caller ends without touching the database when it was not:
    someone else is classifying that message."""
    key = f"{prefix}:{chat_pk}:{message_id}"
    token = uuid.uuid4().hex
    acquired = bool(await redis.set(key, token, px=ttl_ms, nx=True))
    try:
        yield acquired
    finally:
        if acquired:
            await redis.eval(_RELEASE_SCRIPT, 1, key, token)


async def load_facts(
    session: AsyncSession, chat_pk: int, message_id: int
) -> tuple[MessageFacts, str | None]:
    """Resolves eligibility's stored facts from `telegram_messages` and re-extracts the text from
    the message's own captured event (P1, Finding 5) — never from the row, which an edit may have
    overwritten. Imports `extract_text` lazily to avoid a module-level cycle with
    `app.workers.tasks.moderation.classify_message`, which this module's callers import."""
    from app.application.moderation.messages import extract_text

    message_row = (
        await session.execute(
            sa.select(
                telegram_messages.c.is_service,
                telegram_messages.c.media_kind,
                telegram_messages.c.is_from_moderator,
                telegram_messages.c.sender_chat_id,
                telegram_messages.c.text_purged_at,
                telegram_messages.c.source_update_id,
            ).where(
                telegram_messages.c.telegram_chat_id == chat_pk,
                telegram_messages.c.message_id == message_id,
            )
        )
    ).one()

    group_chat_id = (
        await session.execute(
            sa.select(telegram_chats.c.chat_id).where(telegram_chats.c.id == chat_pk)
        )
    ).scalar_one()

    update_row = (
        await session.execute(
            sa.select(
                telegram_updates.c.payload,
                telegram_updates.c.update_type,
                telegram_updates.c.payload_purged_at,
            ).where(telegram_updates.c.id == message_row.source_update_id)
        )
    ).one()

    text_removed = (
        message_row.text_purged_at is not None or update_row.payload_purged_at is not None
    )

    text: str | None = None
    is_automatic_forward = False
    if not text_removed:
        body: dict[str, Any] = update_row.payload.get(update_row.update_type) or {}
        _original_text, text = extract_text(body)
        is_automatic_forward = bool(body.get("is_automatic_forward"))

    facts = MessageFacts(
        is_service=message_row.is_service,
        media_kind=message_row.media_kind,
        text=text,
        text_removed=text_removed,
        is_from_moderator=message_row.is_from_moderator,
        sender_chat_id=message_row.sender_chat_id,
        group_chat_id=group_chat_id,
        is_automatic_forward=is_automatic_forward,
    )
    return facts, text


async def _already_attempted(session: AsyncSession, *, chat_pk: int, message_id: int) -> bool:
    """I1-I2's backstop check: a current prediction or an exclusion already exists."""
    prediction_exists = (
        await session.execute(
            sa.select(sa.literal(1))
            .select_from(message_classifications)
            .where(
                message_classifications.c.telegram_chat_id == chat_pk,
                message_classifications.c.telegram_message_id == message_id,
                message_classifications.c.is_current.is_(True),
            )
            .limit(1)
        )
    ).first()
    if prediction_exists is not None:
        return True

    exclusion_exists = (
        await session.execute(
            sa.select(sa.literal(1))
            .select_from(message_classification_attempts)
            .where(
                message_classification_attempts.c.telegram_chat_id == chat_pk,
                message_classification_attempts.c.telegram_message_id == message_id,
                message_classification_attempts.c.outcome == "excluded",
            )
            .limit(1)
        )
    ).first()
    return exclusion_exists is not None


async def _insert_exclusion(
    session: AsyncSession, *, chat_pk: int, message_id: int, path: str, reason: str
) -> None:
    """E9: one `excluded` row, `ON CONFLICT DO NOTHING` on `uq_attempt_exclusion`."""
    await session.execute(
        pg_insert(message_classification_attempts)
        .values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            path=path,
            outcome="excluded",
            reason=reason,
        )
        .on_conflict_do_nothing(
            index_elements=[
                message_classification_attempts.c.telegram_chat_id,
                message_classification_attempts.c.telegram_message_id,
            ],
            index_where=message_classification_attempts.c.outcome == "excluded",
        )
    )


async def record_failure(
    session: AsyncSession,
    *,
    chat_pk: int,
    message_id: int,
    path: str,
    reason: str,
    model_profile_id: int,
) -> None:
    """F3: one appended `failed` row naming the kind and the profile — never `ON CONFLICT`, since
    failures are appended, not deduplicated (data-model.md §3). Shared with US3's task-level retry
    exhaustion (T053)."""
    await session.execute(
        message_classification_attempts.insert().values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            path=path,
            outcome="failed",
            reason=reason,
            model_profile_id=model_profile_id,
        )
    )
    logger.info(
        "classification failed",
        extra={"message_id": message_id, "chat_id": chat_pk, "category": reason},
    )


async def _insert_prediction(
    session: AsyncSession,
    *,
    chat_pk: int,
    message_id: int,
    model_profile_id: int,
    model_run_id: int | None,
    prediction: Prediction,
    path: str,
    route: str,
    route_reason: str | None,
    floor: Decimal | None,
    threshold: Decimal | None,
) -> int | None:
    """O5-O6: one immutable row, `ON CONFLICT (telegram_chat_id, telegram_message_id) WHERE
    is_current DO NOTHING` on `uq_classification_current` — the idempotent insert I1 backstops."""
    result = await session.execute(
        pg_insert(message_classifications)
        .values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            model_profile_id=model_profile_id,
            model_run_id=model_run_id,
            prompt_version=_PROMPT_VERSION,
            taxonomy_version=TAXONOMY_VERSION,
            category=prediction.category,
            needs_response=prediction.needs_response,
            needs_moderation=prediction.needs_moderation,
            severity=prediction.severity,
            confidence=prediction.confidence,
            path=path,
            route=route,
            route_reason=route_reason,
            confidence_floor=floor,
            incident_threshold=threshold,
        )
        .on_conflict_do_nothing(
            index_elements=[
                message_classifications.c.telegram_chat_id,
                message_classifications.c.telegram_message_id,
            ],
            index_where=message_classifications.c.is_current,
        )
        .returning(message_classifications.c.id)
    )
    return result.scalar_one_or_none()


async def classify_one(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Gateway,
    registry: ProfileRegistry,
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    path: str,
    attempt: int = 1,
) -> str:
    """The pipeline's one write path (§5-§6): resolve the profile (F1), claim the message (I3),
    check idempotency (I1-I2), resolve eligibility (E1-E8), call the gateway (O1-O2), range-check
    and quantise (O3-O4), route (R1-R6) and insert (O5). Returns a short outcome label —
    `"no_active_model"`, `"claimed_elsewhere"`, `"already_classified"`, `"excluded"`, `"failed"` or
    `"classified"` — for the caller to log or count; nothing here opens an incident (US4, T056) or
    retries a transient failure (US3, T053) — a transient `GatewayError` is re-raised.
    """
    try:
        profile = await registry.resolve("moderation")
    except NoActiveProfileError:
        return "no_active_model"

    ttl_ms = int((settings.gateway_call_timeout_s + 30) * 1000)
    async with claim(redis, chat_pk, message_id, ttl_ms) as acquired:
        if not acquired:
            return "claimed_elsewhere"

        async with session_factory() as session:
            if await _already_attempted(session, chat_pk=chat_pk, message_id=message_id):
                return "already_classified"

            facts, text = await load_facts(session, chat_pk, message_id)
            reason = eligibility(facts)
            if reason is not None:
                await _insert_exclusion(
                    session, chat_pk=chat_pk, message_id=message_id, path=path, reason=reason
                )
                await session.commit()
                return "excluded"

            assert text is not None  # eligibility's E4 (no_text) already ruled this out
            model_input = build_model_input(text)

            try:
                response = await gateway.generate_structured(
                    StructuredRequest(
                        messages=model_input, schema_model=MessageClassificationResult
                    ),
                    role="moderation",
                )
            except GatewayError as exc:
                if isinstance(exc, _TRANSIENT_ERRORS):
                    raise
                await record_failure(
                    session,
                    chat_pk=chat_pk,
                    message_id=message_id,
                    path=path,
                    reason=exc.category,
                    model_profile_id=profile.id,
                )
                await session.commit()
                return "failed"

            answer = response.value
            if not 0 <= answer.confidence <= 1:
                await record_failure(
                    session,
                    chat_pk=chat_pk,
                    message_id=message_id,
                    path=path,
                    reason="confidence_out_of_range",
                    model_profile_id=profile.id,
                )
                await session.commit()
                return "failed"

            prediction = Prediction(
                category=answer.category,
                needs_response=answer.needs_response,
                needs_moderation=answer.needs_moderation,
                severity=answer.severity,
                confidence=quantise(answer.confidence),
            )
            is_catch_up = path == "catch_up"
            floor = None if is_catch_up else quantise(settings.moderation_confidence_floor)
            threshold = None if is_catch_up else quantise(settings.moderation_incident_confidence)
            route, route_reason = route_prediction(
                prediction, floor=floor, threshold=threshold, path=path
            )

            inserted_id = await _insert_prediction(
                session,
                chat_pk=chat_pk,
                message_id=message_id,
                model_profile_id=profile.id,
                model_run_id=response.model_run_id,
                prediction=prediction,
                path=path,
                route=route,
                route_reason=route_reason,
                floor=floor,
                threshold=threshold,
            )
            if inserted_id is None:
                await session.commit()
                return "already_classified"

            if route == "incident":
                # A1-A3: the same insert `open_incident` uses, on this session, not committing —
                # an existing incident on this message (an operator got there first) wins and
                # nothing opens (`ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING`, R12).
                incident_id = await insert_incident(
                    session,
                    telegram_chat_id=chat_pk,
                    telegram_message_id=message_id,
                    category=prediction.category,
                    severity=prediction.severity,
                    source="ai",
                    opened_by_user_id=None,
                    message_classification_id=inserted_id,
                )
                if incident_id is not None:
                    logger.info(
                        "incident opened",
                        extra={"incident_id": incident_id, "message_id": message_id},
                    )

            await session.commit()
            return "classified"
