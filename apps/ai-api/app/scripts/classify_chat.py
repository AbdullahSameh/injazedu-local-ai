"""`python -m app.scripts.classify_chat` — the catch-up command that classifies a measured
chat's already-captured history for **measurement only** (`contracts/classification-pipeline.md`
§1 Q4, §9 C1-C3, `data-model.md` §2's `path = 'catch_up'`, D-TG-160, FR-061, FR-062, tasks.md T071).

Composition root, exempt from the moderation import boundary by directory (`app/scripts/`, per
`tasks.md`'s Path Conventions) — the only module besides the live actor that calls `classify_one`.
Refuses a chat that is not measured, exactly as `rederive_chat` (§7 R1). Walks the chat's messages
in `sent_at` order that have **neither** a current prediction **nor** an exclusion — the same
idempotency backstop `classify_one` itself checks (I1-I2) — through the **same** `classify_one`
the live actor calls, always with `path="catch_up"`: `route_prediction`'s R1 then forces
`route = 'measurement_only'` on every prediction this command ever writes (`ck_classification_
route_path`), so it can never open an incident and never appears on the possible-violations list
(C4). A transient `GatewayError` `classify_one` re-raises is recorded here as one `failed` row —
never re-scheduled, since there is no queue underneath a synchronous command (D-TG-151 is the live
actor's own policy, not this one's). History is classified only through this command; the live
path only ever sees a message once, at derivation (D-TG-149).

    python -m app.scripts.classify_chat --chat <chat_id> [--since 2026-09-01] [--until 2026-09-08]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
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
from app.infrastructure.models_moderation import (
    message_classification_attempts,
    message_classifications,
    telegram_chats,
    telegram_messages,
)

_BATCH_SIZE = 200

# Mirrors `classify_message.py`'s own closed list (F2): the only errors `classify_one` re-raises
# rather than recording itself.
_TRANSIENT_ERRORS: tuple[type[GatewayError], ...] = (
    ProviderUnreachableError,
    ModelTimeoutError,
    CircuitOpenError,
)


class ChatNotMonitoredError(Exception):
    """The named chat is not measured — the catch-up refuses to run (§7 R1)."""


@dataclass(frozen=True)
class ClassifyChatReport:
    """The three counts the command prints: how many messages got a prediction, and the
    exclusion / failure breakdown by reason (D-TG-160's own report line)."""

    classified: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        def _fmt(counts: dict[str, int]) -> str:
            return ",".join(f"{reason}:{n}" for reason, n in sorted(counts.items()))

        return (
            f"classified={self.classified} "
            f"excluded={_fmt(self.excluded)} "
            f"failed={_fmt(self.failed)}"
        )


async def _chat_surrogate(session: AsyncSession, chat_id: int) -> int:
    result = await session.execute(
        sa.select(telegram_chats.c.id).where(telegram_chats.c.chat_id == chat_id)
    )
    surrogate: int = result.scalar_one()
    return surrogate


async def _is_monitored(session: AsyncSession, chat_id: int) -> bool:
    result = await session.execute(
        sa.select(telegram_chats.c.is_monitored).where(telegram_chats.c.chat_id == chat_id)
    )
    monitored: bool = result.scalar_one()
    return monitored


async def _fetch_attempt_reason(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_pk: int,
    message_id: int,
    outcome: str,
) -> str:
    """Reads back the reason `classify_one` just recorded (excluded: the one row; failed: the
    latest, `data-model.md` §3's own precedence) — `classify_one` returns only the outcome kind,
    never the reason, so the report reads it from the row it wrote."""
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(message_classification_attempts.c.reason)
                .where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id == message_id,
                    message_classification_attempts.c.outcome == outcome,
                )
                .order_by(
                    message_classification_attempts.c.created_at.desc(),
                    message_classification_attempts.c.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one()
    return str(row)


async def classify_chat(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Gateway,
    registry: ProfileRegistry,
    redis: Redis,
    settings: Settings,
    *,
    chat_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    batch_size: int = _BATCH_SIZE,
) -> ClassifyChatReport:
    """Walks `chat_id`'s messages in `sent_at` order — keyset-paginated on `(sent_at,
    telegram_message_id)`, so a message is visited **at most once per run** whatever the outcome,
    including a message that fails again (no infinite retry loop within one run) — calling
    `classify_one(..., path="catch_up")` on each that has no current prediction and no exclusion
    yet (I1-I2's own backstop). Raises `ChatNotMonitoredError` for an unmeasured chat. A second
    run over the same range finds nothing left to do (D-TG-160): every message from the first run
    now carries a prediction or an exclusion.
    """
    async with session_factory() as session:
        if not await _is_monitored(session, chat_id):
            raise ChatNotMonitoredError(f"chat {chat_id} is not measured — refusing to classify")
        chat_pk = await _chat_surrogate(session, chat_id)

    classified = 0
    excluded: Counter[str] = Counter()
    failed: Counter[str] = Counter()

    last_sent_at: datetime | None = None
    last_message_id: int | None = None

    while True:
        conditions = [
            telegram_messages.c.telegram_chat_id == chat_pk,
            ~sa.exists(
                sa.select(sa.literal(1))
                .select_from(message_classifications)
                .where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id
                    == telegram_messages.c.message_id,
                    message_classifications.c.is_current,
                )
            ),
            ~sa.exists(
                sa.select(sa.literal(1))
                .select_from(message_classification_attempts)
                .where(
                    message_classification_attempts.c.telegram_chat_id == chat_pk,
                    message_classification_attempts.c.telegram_message_id
                    == telegram_messages.c.message_id,
                    message_classification_attempts.c.outcome == "excluded",
                )
            ),
        ]
        if since is not None:
            conditions.append(telegram_messages.c.sent_at >= since)
        if until is not None:
            conditions.append(telegram_messages.c.sent_at < until)
        if last_sent_at is not None:
            conditions.append(
                sa.or_(
                    telegram_messages.c.sent_at > last_sent_at,
                    sa.and_(
                        telegram_messages.c.sent_at == last_sent_at,
                        telegram_messages.c.message_id > last_message_id,
                    ),
                )
            )

        async with session_factory() as session:
            batch = (
                await session.execute(
                    sa.select(telegram_messages.c.sent_at, telegram_messages.c.message_id)
                    .where(*conditions)
                    .order_by(telegram_messages.c.sent_at, telegram_messages.c.message_id)
                    .limit(batch_size)
                )
            ).all()

        if not batch:
            break

        for row in batch:
            last_sent_at, last_message_id = row.sent_at, row.message_id

            try:
                outcome = await classify_one(
                    session_factory,
                    gateway,
                    registry,
                    redis,
                    settings,
                    chat_pk=chat_pk,
                    message_id=row.message_id,
                    path="catch_up",
                )
            except _TRANSIENT_ERRORS as exc:
                profile = await registry.resolve("moderation")
                async with session_factory() as session:
                    await record_failure(
                        session,
                        chat_pk=chat_pk,
                        message_id=row.message_id,
                        path="catch_up",
                        reason=exc.category,
                        model_profile_id=profile.id,
                    )
                    await session.commit()
                failed[exc.category] += 1
                continue

            if outcome == "classified":
                classified += 1
            elif outcome == "excluded":
                reason = await _fetch_attempt_reason(
                    session_factory, chat_pk=chat_pk, message_id=row.message_id, outcome="excluded"
                )
                excluded[reason] += 1
            elif outcome == "failed":
                reason = await _fetch_attempt_reason(
                    session_factory, chat_pk=chat_pk, message_id=row.message_id, outcome="failed"
                )
                failed[reason] += 1
            elif outcome == "no_active_model":
                # F1: no active `moderation` profile at all — every remaining message will
                # resolve identically, so the run ends here rather than repeating the same
                # no-op lookup for the rest of the chat's history.
                return ClassifyChatReport(
                    classified=classified, excluded=dict(excluded), failed=dict(failed)
                )
            # "claimed_elsewhere" / "already_classified": I1/I3's backstop — nothing to count,
            # the next run (or the live path) already owns or has already recorded this message.

        if len(batch) < batch_size:
            break

    return ClassifyChatReport(classified=classified, excluded=dict(excluded), failed=dict(failed))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", type=int, required=True, help="The platform's own chat id.")
    parser.add_argument(
        "--since", type=_parse_datetime, default=None, help="ISO date/datetime, inclusive."
    )
    parser.add_argument(
        "--until", type=_parse_datetime, default=None, help="ISO date/datetime, exclusive."
    )
    return parser.parse_args(argv)


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    session_factory = make_session_factory(make_engine(settings))
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)

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

    try:
        report = await classify_chat(
            session_factory,
            gateway,
            registry,
            redis,
            settings,
            chat_id=args.chat,
            since=args.since,
            until=args.until,
        )
    except ChatNotMonitoredError as exc:
        print(f"classify_chat: {exc}", file=sys.stderr)
        await redis.aclose()
        return 1

    await redis.aclose()
    print(report.render())
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:])))


if __name__ == "__main__":
    main()
