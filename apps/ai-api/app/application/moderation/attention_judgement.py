"""`judge_one` — the attention judgement's one write path (TG-M5.3,
`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §2-§4, §7 W1, §8;
`tasks.md` T034).

It asks one question of one message, "does this need the team?", through its own instruction and
its own `attention` model role, and records one answer: an intent, with `needs_response` derived
once by the domain's `needs_response_for` (S2). It mirrors `classify_one` step for step and reuses
its `load_facts` (the captured event's first-posted words, Finding 5) and `claim` (under its own
prefix, so neither task blocks the other, W4). It never reads a classification, and the
classification never reads it (J4); the two meet only in `open_item`'s veto, at opening time.

With no instruction configured (`MODERATION_ATTENTION_PROMPT_VERSION` blank) or no active
`attention` profile, it claims nothing, calls nothing and records nothing (P4): shadow mode is
switched on by the setting alone. It never opens an item itself. When the opener's switch is set
(`ai_attention_from_settings`, D-TG-199), a live judgement needing a response puts its message back
on the attention work list (`request_rejudgement`) in the same transaction as its insert (W2), so a
judgement landing after its burst was judged reaches `open_item` through the one judgement path.

The redacted string is bound only to `redacted_text`, matching `scripts/check.sh` check 4's
whitelist, and is never passed to a logger (P2, N1).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

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
from app.application.moderation.attention import ai_attention_from_settings, request_rejudgement
from app.application.moderation.classification import claim, load_facts
from app.application.moderation.text import redact
from app.domain.moderation.attention_judgement import attention_exclusion, needs_response_for
from app.infrastructure.config import ATTENTION_PROMPT_VERSIONS, Settings
from app.infrastructure.models_moderation import (
    message_attention_attempts,
    message_attention_judgements,
)

logger = logging.getLogger(__name__)

# Every frozen attention instruction, read once at import (P1, P3; D-TG-189). The version is the
# file's stem. The tuple is empty until `attention_v1` is frozen, so this mapping is too; tests
# pass a test-only instruction through `judge_one(instructions=...)`.
_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "moderation"
_ATTENTION_INSTRUCTIONS: dict[str, str] = {
    version: (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
    for version in ATTENTION_PROMPT_VERSIONS
}


def attention_instruction(version: str) -> str:
    """The frozen instruction text of `version`, one of `ATTENTION_PROMPT_VERSIONS` — what the
    judge sends, and what the qualification and the smoke send for `--prompt` (contract
    qualification.md §1)."""
    return _ATTENTION_INSTRUCTIONS[version]


_CLAIM_PREFIX = "ai:mod:attention:msg"

# F1's transient set, exactly the classifier's (pipeline F2): re-raised for the task's own retry.
# A cut-off or malformed answer is final here (F2), recorded rather than retried.
_TRANSIENT_ERRORS: tuple[type[GatewayError], ...] = (
    ProviderUnreachableError,
    ModelTimeoutError,
    CircuitOpenError,
)


class AttentionJudgementResult(BaseModel):
    """The model's structured answer (S1): one field, one of the six intents (S3). Anything else
    fails validation and is recorded as `structured_output_invalid`."""

    intent: Literal["asking", "discussion", "informing", "social", "offering", "other"]


def build_attention_input(text: str, *, instruction: str) -> list[Message]:
    """`[system = the instruction, user = redact(text)]` (P1): no sender, group, time, reply target
    or neighbouring message. The redacted string is named `redacted_text` only in this function's
    own scope, never logged (P2)."""
    redacted_text = redact(text)
    return [
        Message(role="system", content=instruction),
        Message(role="user", content=redacted_text),
    ]


async def _already_judged(session: AsyncSession, *, chat_pk: int, message_id: int) -> bool:
    """W1 step 2: a current judgement or an exclusion already exists for this message."""
    judgement_exists = (
        await session.execute(
            sa.select(sa.literal(1))
            .select_from(message_attention_judgements)
            .where(
                message_attention_judgements.c.telegram_chat_id == chat_pk,
                message_attention_judgements.c.telegram_message_id == message_id,
                message_attention_judgements.c.is_current.is_(True),
            )
            .limit(1)
        )
    ).first()
    if judgement_exists is not None:
        return True

    exclusion_exists = (
        await session.execute(
            sa.select(sa.literal(1))
            .select_from(message_attention_attempts)
            .where(
                message_attention_attempts.c.telegram_chat_id == chat_pk,
                message_attention_attempts.c.telegram_message_id == message_id,
                message_attention_attempts.c.outcome == "excluded",
            )
            .limit(1)
        )
    ).first()
    return exclusion_exists is not None


async def _insert_attention_exclusion(
    session: AsyncSession, *, chat_pk: int, message_id: int, path: str, reason: str
) -> None:
    """AE3: one `excluded` row, `ON CONFLICT DO NOTHING` on `uq_attention_attempt_exclusion`."""
    await session.execute(
        pg_insert(message_attention_attempts)
        .values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            path=path,
            outcome="excluded",
            reason=reason,
        )
        .on_conflict_do_nothing(
            index_elements=[
                message_attention_attempts.c.telegram_chat_id,
                message_attention_attempts.c.telegram_message_id,
            ],
            index_where=message_attention_attempts.c.outcome == "excluded",
        )
    )


async def record_attention_failure(
    session: AsyncSession,
    *,
    chat_pk: int,
    message_id: int,
    path: str,
    reason: str,
    model_profile_id: int,
) -> None:
    """F2: one appended `failed` row naming the kind and the profile. Failures are appended, never
    deduplicated (data-model §2). Shared with the task's retry exhaustion (F1)."""
    await session.execute(
        message_attention_attempts.insert().values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            path=path,
            outcome="failed",
            reason=reason,
            model_profile_id=model_profile_id,
        )
    )
    logger.info(
        "attention judgement failed",
        extra={"message_id": message_id, "chat_id": chat_pk, "category": reason},
    )


async def _insert_judgement(
    session: AsyncSession,
    *,
    chat_pk: int,
    message_id: int,
    model_profile_id: int,
    model_run_id: int | None,
    prompt_version: str,
    intent: str,
    path: str,
) -> int | None:
    """W1 step 3: one immutable row, `ON CONFLICT (telegram_chat_id, telegram_message_id) WHERE
    is_current DO NOTHING` on `uq_attention_judgement_current`. `needs_response` is computed here,
    once, by the domain's single derivation (S2), and never again."""
    result = await session.execute(
        pg_insert(message_attention_judgements)
        .values(
            telegram_chat_id=chat_pk,
            telegram_message_id=message_id,
            model_profile_id=model_profile_id,
            model_run_id=model_run_id,
            prompt_version=prompt_version,
            intent=intent,
            needs_response=needs_response_for(intent),
            path=path,
        )
        .on_conflict_do_nothing(
            index_elements=[
                message_attention_judgements.c.telegram_chat_id,
                message_attention_judgements.c.telegram_message_id,
            ],
            index_where=message_attention_judgements.c.is_current,
        )
        .returning(message_attention_judgements.c.id)
    )
    return result.scalar_one_or_none()


async def judge_one(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Gateway,
    registry: ProfileRegistry,
    redis: Redis,
    settings: Settings,
    *,
    chat_pk: int,
    message_id: int,
    path: str = "live",
    attempt: int = 1,
    instructions: Mapping[str, str] | None = None,
) -> str:
    """W1: check the instruction (P4), resolve the `attention` profile, claim the message, check
    for an existing judgement or exclusion, apply AE1-AE2, call the model and insert. W2: a live
    insert with `needs_response` true, while the opener's switch is set, requests re-judgement of
    its message before the same commit.

    Returns a short outcome label for the caller to log or count: `"no_prompt"`,
    `"no_active_model"`, `"claimed_elsewhere"`, `"already_judged"`, `"excluded"`, `"failed"` or
    `"judged"`. A transient `GatewayError` is re-raised for the task's retry (F1). `instructions`
    defaults to the frozen files; tests pass a test-only one (D-TG-189). `attempt` is the task's
    retry counter, carried for symmetry with `classify_one`.
    """
    prompt_version = settings.moderation_attention_prompt_version
    if prompt_version is None:
        return "no_prompt"
    instruction = (instructions if instructions is not None else _ATTENTION_INSTRUCTIONS)[
        prompt_version
    ]

    try:
        profile = await registry.resolve("attention")
    except NoActiveProfileError:
        return "no_active_model"

    ttl_ms = int((settings.gateway_call_timeout_s + 30) * 1000)
    async with claim(redis, chat_pk, message_id, ttl_ms, prefix=_CLAIM_PREFIX) as acquired:
        if not acquired:
            return "claimed_elsewhere"

        async with session_factory() as session:
            if await _already_judged(session, chat_pk=chat_pk, message_id=message_id):
                return "already_judged"

            facts, text = await load_facts(session, chat_pk, message_id)
            reason = attention_exclusion(facts)
            if reason is not None:
                await _insert_attention_exclusion(
                    session, chat_pk=chat_pk, message_id=message_id, path=path, reason=reason
                )
                await session.commit()
                return "excluded"

            assert text is not None  # AE1's E4 (no_text) already ruled this out
            model_input = build_attention_input(text, instruction=instruction)

            try:
                response = await gateway.generate_structured(
                    StructuredRequest(messages=model_input, schema_model=AttentionJudgementResult),
                    role="attention",
                )
            except GatewayError as exc:
                if isinstance(exc, _TRANSIENT_ERRORS):
                    raise
                await record_attention_failure(
                    session,
                    chat_pk=chat_pk,
                    message_id=message_id,
                    path=path,
                    reason=exc.category,
                    model_profile_id=profile.id,
                )
                await session.commit()
                return "failed"

            inserted_id = await _insert_judgement(
                session,
                chat_pk=chat_pk,
                message_id=message_id,
                model_profile_id=profile.id,
                model_run_id=response.model_run_id,
                prompt_version=prompt_version,
                intent=response.value.intent,
                path=path,
            )
            if inserted_id is None:
                await session.commit()
                return "already_judged"

            if (
                path == "live"
                and needs_response_for(response.value.intent)
                and ai_attention_from_settings(settings) is not None
            ):
                # W2 (TG-M5.1 I1, re-pointed): this judgement proposes a question item. If the
                # burst was already judged without it, put the message back on the sweep's work
                # list — in this same transaction, so the judgement and the request commit
                # together. Whether an item opens is `open_item`'s decision alone.
                await request_rejudgement(
                    session, telegram_chat_id=chat_pk, message_id=message_id
                )

            await session.commit()
            return "judged"
