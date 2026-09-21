"""Telegram event capture (`contracts/ingestion-guarantees.md`, `data-model.md`).

This milestone builds the module incrementally, story by story; Phase 2 (Foundational) adds only
bot-identity resolution, since nothing else may run before it. Phase 3 (US1) adds `store_batch` —
the append-only spine. Phase 4 (US2) adds `record_poll_outcome` and `next_offset` — the durable,
restart-safe position. Phase 5 (US3) adds the gap detectors — `record_downtime_if_any`,
`record_identifier_jump_if_any` — and the identifier-reset protocol — `resync_after_stall` and
`record_reset_outcome` (D-TG-33, `contracts/telegram-provider.md` §5). Phase 6 (US4) adds group
discovery — `upsert_chats_from_batch` and `apply_chat_migration_if_any` (D-TG-43, D-TG-44). Phase
8 (US6) adds the same-machine single-consumer lease — `hold_poll_lease` — and the cross-machine
`409` stand-down — `handle_conflict` (D-TG-37).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.assignments import repoint_for_migration
from app.infrastructure.models_moderation import (
    ingestion_gaps,
    ingestion_state,
    telegram_chats,
    telegram_updates,
)
from app.providers.telegram.client import TelegramProvider
from app.providers.telegram.errors import TelegramError
from app.providers.telegram.models import BotIdentity, TelegramUpdate
from app.workers.tasks.moderation.process_update import process_update

logger = logging.getLogger(__name__)

_IDENTITY_RETRY_BASE_S = 1.0
_IDENTITY_RETRY_MAX_S = 60.0

_CONFLICT_BACKOFF_BASE_S = 1.0
_CONFLICT_BACKOFF_MAX_S = 60.0

# The Bot API's own undeliverable-backlog retention (`contracts/telegram-provider.md` §2) — not
# configurable, since it is a platform fact rather than a policy choice.
_UNRECOVERABLE_WINDOW_S = 24 * 3600

GAP_REASON_DOWNTIME = "downtime"
GAP_REASON_UPDATE_ID_JUMP = "update_id_jump"
GAP_REASON_UPDATE_ID_RESET = "update_id_reset"
GAP_REASON_CONFLICT_409 = "conflict_409"

# The same-machine half of single-consumer enforcement (FR-003, D-TG-37); the platform's own 409
# is the cross-machine half, handled by `handle_conflict` below. A fixed, literal key — not built
# from a name/prefix pair like `gateway/lanes.py`'s `Lane`, because there is exactly one of these
# per machine, never a family of named lanes.
_POLL_LEASE_REDIS_NAME = "ai:tg:poll:lease"

# Compare-and-delete / compare-and-renew — the same fencing-token pattern proved in
# `app/application/gateway/lanes.py`: only the current holder's own release or renewal can touch
# its lease, never a stale holder's delayed call racing a reclaim by someone else.
_RELEASE_POLL_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
end
return 1
"""

_RENEW_POLL_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class PollLeaseHeldElsewhereError(Exception):
    """Another capture process already holds `ai:tg:poll:lease` on this machine (FR-003,
    D-TG-37). Raised immediately on a failed claim attempt — never retried in a loop here, since
    the correct response to losing this race is to stand down, not to queue and compete."""


async def _renew_poll_lease(
    redis: Redis, *, token: str, ttl_s: float, interval_s: float
) -> None:
    ttl_ms = int(ttl_s * 1000)
    while True:
        await asyncio.sleep(interval_s)
        await redis.eval(_RENEW_POLL_LEASE_SCRIPT, 1, _POLL_LEASE_REDIS_NAME, token, ttl_ms)


@asynccontextmanager
async def hold_poll_lease(
    redis: Redis,
    *,
    ttl_s: float = 30.0,
    renew_interval_s: float = 10.0,
    holder: str | None = None,
) -> AsyncIterator[str]:
    """Claims `ai:tg:poll:lease` with `SET … PX … NX` for the run of the poll loop, renews it with
    a watchdog while held, and releases it (compare-and-delete, so only this holder's own release
    can clear it) on every exit path.

    Unlike `gateway/lanes.py`'s `Lane`, whose callers wait their turn for a shared resource, a
    second capture process losing this race must stand down rather than compete (FR-003) — so a
    failed claim raises `PollLeaseHeldElsewhereError` immediately instead of blocking.
    """
    token = holder or uuid.uuid4().hex
    ttl_ms = int(ttl_s * 1000)
    claimed = await redis.set(_POLL_LEASE_REDIS_NAME, token, px=ttl_ms, nx=True)
    if not claimed:
        raise PollLeaseHeldElsewhereError(
            f"{_POLL_LEASE_REDIS_NAME} is already held by another process on this machine"
        )

    watchdog = asyncio.create_task(
        _renew_poll_lease(redis, token=token, ttl_s=ttl_s, interval_s=renew_interval_s)
    )
    try:
        yield token
    finally:
        watchdog.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog
        await redis.eval(_RELEASE_POLL_LEASE_SCRIPT, 1, _POLL_LEASE_REDIS_NAME, token)


async def resolve_bot_identity(
    provider: TelegramProvider,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_attempt_failed: Callable[[TelegramError], None] | None = None,
) -> BotIdentity:
    """Resolve the numeric bot id via `get_me` before anything may be stored (D-TG-42).

    Retries indefinitely with increasing delay on **any** failure — an unreachable platform and
    a rejected credential get the same "stay up and keep trying" treatment, because a swapped or
    momentarily-unreachable credential must never fall back to a previously stored identity. The
    two cases remain distinguishable to a caller via `on_attempt_failed`, which the health block
    (US5) uses to report them separately (FR-007a-d).
    """
    attempt = 0
    while True:
        try:
            return await provider.get_me()
        except TelegramError as exc:
            attempt += 1
            if on_attempt_failed is not None:
                on_attempt_failed(exc)
            logger.warning("bot identity unresolved on attempt %d: %s", attempt, exc.category)
            delay = min(_IDENTITY_RETRY_BASE_S * (2 ** (attempt - 1)), _IDENTITY_RETRY_MAX_S)
            await sleep(delay)


@dataclass(frozen=True)
class StoredUpdate:
    """One row `store_batch` actually inserted — never a row skipped by `ON CONFLICT`."""

    id: int
    update_id: int
    chat_id: int | None


def _schedule_interpretation(update_row_id: int, update_id: int) -> None:
    process_update.send(update_row_id, update_id)


async def store_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    updates: Sequence[TelegramUpdate],
    schedule: Callable[[int, int], None] = _schedule_interpretation,
) -> list[StoredUpdate]:
    """Store a batch exactly once and schedule interpretation for the rows actually stored
    (`contracts/ingestion-guarantees.md` G1, G2; FR-008, FR-010, FR-011, FR-012, D-TG-30, D-TG-36).

    One statement — `INSERT … ON CONFLICT (bot_id, update_id) DO NOTHING RETURNING id,
    update_id` — so a duplicate delivery and a fresh one are the same operation with no
    read-then-write race. Interpretation is scheduled only **after** the insert has committed,
    and only for the identifiers `RETURNING` gave back: enqueueing inside the transaction would
    let a worker find a row whose transaction has not committed, or has rolled back and never
    will (D-TG-36).
    """
    if not updates:
        return []

    values = [
        {
            "bot_id": bot_id,
            "update_id": update.update_id,
            "update_type": update.kind,
            "chat_id": update.chat_id,
            "payload": update.raw,
        }
        for update in updates
    ]
    statement = (
        pg_insert(telegram_updates)
        .values(values)
        .on_conflict_do_nothing(index_elements=["bot_id", "update_id"])
        .returning(telegram_updates.c.id, telegram_updates.c.update_id, telegram_updates.c.chat_id)
    )

    async with session_factory() as session:
        result = await session.execute(statement)
        stored = [
            StoredUpdate(id=row.id, update_id=row.update_id, chat_id=row.chat_id) for row in result
        ]
        await session.commit()

    for row in stored:
        logger.info(
            "update stored", extra={"update_id": row.update_id, "chat_id": row.chat_id}
        )
        schedule(row.id, row.update_id)
    return stored


async def record_poll_outcome(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    bot_username: str | None,
    allowed_updates: Sequence[str],
    stored: Sequence[StoredUpdate],
) -> None:
    """Update `ingestion_state` after a **successful** poll, once `store_batch`'s transaction has
    committed (`contracts/ingestion-guarantees.md` G2 steps 2-3; FR-015, FR-016, `data-model.md`
    §2).

    `last_update_id` and `last_event_at` only ever advance to reflect identifiers this bot's rows
    actually contain — an empty poll (`stored` empty) leaves both unchanged via `GREATEST`'s
    NULL-ignoring semantics, which is what makes a week of empty successes visible as a stall
    (US3, D-TG-33) instead of erased. `allowed_updates` is written on every call, so FR-006's
    re-assertion on restart is free rather than a skippable startup step (D-TG-41).
    `consecutive_failures` always resets to 0 here — call this only after a poll actually
    succeeded; a failed poll must not call it at all, which is what leaves the position unmoved
    (FR-018). `consecutive_conflicts` resets to 0 here too (FR-004b): a successful poll, empty or
    not, means this consumer currently holds the credential uncontested.
    """
    highest = max((row.update_id for row in stored), default=None)

    insert_stmt = pg_insert(ingestion_state).values(
        bot_id=bot_id,
        bot_username=bot_username,
        last_update_id=highest,
        last_poll_at=sa.func.now(),
        last_success_at=sa.func.now(),
        last_event_at=sa.func.now() if highest is not None else None,
        consecutive_failures=0,
        consecutive_conflicts=0,
        allowed_updates=list(allowed_updates),
        updated_at=sa.func.now(),
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["bot_id"],
        set_={
            "bot_username": insert_stmt.excluded.bot_username,
            "last_update_id": sa.func.greatest(
                ingestion_state.c.last_update_id, insert_stmt.excluded.last_update_id
            ),
            "last_poll_at": insert_stmt.excluded.last_poll_at,
            "last_success_at": insert_stmt.excluded.last_success_at,
            "last_event_at": sa.func.greatest(
                ingestion_state.c.last_event_at, insert_stmt.excluded.last_event_at
            ),
            "consecutive_failures": insert_stmt.excluded.consecutive_failures,
            "consecutive_conflicts": insert_stmt.excluded.consecutive_conflicts,
            "allowed_updates": insert_stmt.excluded.allowed_updates,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )

    async with session_factory() as session:
        await session.execute(upsert_stmt)
        await session.commit()


async def handle_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    standdown_count: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Responds to one `TelegramConflictError` (FR-004, FR-004a, FR-004b, D-TG-37): atomically
    increments `consecutive_conflicts`, then backs off with increasing delay so a rejected
    consumer does not hammer the platform in a tight loop.

    Once the count reaches `standdown_count`, instead of backing off it sets `stood_down_at` and
    writes an **open** `conflict_409` gap row (`gap_end_at=None` — the unobserved window has no
    known end until an explicit restart), and returns `True` so the poll loop stops entirely
    rather than retrying forever: two consumers that keep retrying alternate, and lose events on
    *both* sides while each looks healthy. Returns `False` while backing off short of the
    threshold. `record_poll_outcome`'s reset of `consecutive_conflicts` to 0 on any subsequent
    success is what FR-004b calls "a single transient conflict must not accumulate".
    """
    now = datetime.now(UTC)
    async with session_factory() as session:
        insert_stmt = pg_insert(ingestion_state).values(
            bot_id=bot_id, consecutive_conflicts=1, allowed_updates=[]
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["bot_id"],
            set_={
                "consecutive_conflicts": ingestion_state.c.consecutive_conflicts + 1,
                "updated_at": sa.func.now(),
            },
        ).returning(ingestion_state.c.consecutive_conflicts)
        new_count: int = (await session.execute(upsert_stmt)).scalar_one()

        stood_down = new_count >= standdown_count
        if stood_down:
            await session.execute(
                ingestion_state.update()
                .where(ingestion_state.c.bot_id == bot_id)
                .values(stood_down_at=now)
            )
            await _write_gap(
                session,
                bot_id=bot_id,
                reason=GAP_REASON_CONFLICT_409,
                unrecoverable=False,
                gap_start_at=now,
                gap_end_at=None,
            )
        await session.commit()

    if not stood_down:
        delay = min(_CONFLICT_BACKOFF_BASE_S * (2 ** (new_count - 1)), _CONFLICT_BACKOFF_MAX_S)
        await sleep(delay)
    return stood_down


async def next_offset(
    session_factory: async_sessionmaker[AsyncSession], *, bot_id: int
) -> int | None:
    """The offset for the next `get_updates` call: `last_update_id + 1`, or `None` (meaning
    "omit the parameter") before anything has ever been stored for this bot (FR-017, D-TG-41)."""
    async with session_factory() as session:
        last_update_id = (
            await session.execute(
                sa.select(ingestion_state.c.last_update_id).where(
                    ingestion_state.c.bot_id == bot_id
                )
            )
        ).scalar_one_or_none()
    return None if last_update_id is None else last_update_id + 1


async def _write_gap(
    session: AsyncSession,
    *,
    bot_id: int,
    reason: str,
    unrecoverable: bool,
    gap_start_at: datetime,
    gap_end_at: datetime | None,
) -> None:
    await session.execute(
        ingestion_gaps.insert().values(
            bot_id=bot_id,
            reason=reason,
            unrecoverable=unrecoverable,
            gap_start_at=gap_start_at,
            gap_end_at=gap_end_at,
        )
    )


async def record_downtime_if_any(
    session_factory: async_sessionmaker[AsyncSession], *, bot_id: int, min_silence_s: int
) -> None:
    """Writes a `downtime` gap when the silence since the last successful poll exceeds
    `min_silence_s`, `unrecoverable` once it exceeds the platform's 24 h retention
    (`contracts/ingestion-guarantees.md` G4; FR-021, FR-022, FR-023, FR-025).

    Call once on startup, before polling resumes — this is what turns "the container was
    stopped" into a fact the honesty of every later report depends on. A silence under the
    minimum writes nothing: a marker that appears on every ordinary restart means nothing on any
    report.
    """
    now = datetime.now(UTC)
    async with session_factory() as session:
        last_success_at = (
            await session.execute(
                sa.select(ingestion_state.c.last_success_at).where(
                    ingestion_state.c.bot_id == bot_id
                )
            )
        ).scalar_one_or_none()
        if last_success_at is None:
            return  # never successfully polled — nothing to have been silent since
        silence_s = (now - last_success_at).total_seconds()
        if silence_s < min_silence_s:
            return
        await _write_gap(
            session,
            bot_id=bot_id,
            reason=GAP_REASON_DOWNTIME,
            unrecoverable=silence_s > _UNRECOVERABLE_WINDOW_S,
            gap_start_at=last_success_at,
            gap_end_at=now,
        )
        await session.commit()


async def record_identifier_jump_if_any(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    incoming_update_ids: Sequence[int],
    stall_window_s: int,
) -> str | None:
    """Detects a batch whose lowest identifier is above `last_update_id + 1` and branches on
    `last_event_at` (FR-024, D-TG-33, `contracts/ingestion-guarantees.md` G4): under the stall
    window this is a real, permanent loss and is written as `update_id_jump`
    (`unrecoverable=True`). At or beyond it, the same observable is Telegram's own renumbering,
    already recovered — writing `update_id_jump` here would invent a loss that did not happen, so
    this function writes nothing and leaves the reset protocol (`resync_after_stall`) as the only
    place `update_id_reset` is ever written.

    Must be called with the state as of the *previous* poll, i.e. before `record_poll_outcome`
    advances `last_update_id` / `last_event_at` for the batch being checked. Returns the gap
    reason written, or `None` when no jump was detected (or the discontinuity was attributed to
    the reset protocol instead).
    """
    if not incoming_update_ids:
        return None
    now = datetime.now(UTC)
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(ingestion_state.c.last_update_id, ingestion_state.c.last_event_at).where(
                    ingestion_state.c.bot_id == bot_id
                )
            )
        ).one_or_none()
        if row is None or row.last_update_id is None:
            return None  # nothing stored yet for this bot — no prior position to jump from

        expected = row.last_update_id + 1
        lowest_incoming = min(incoming_update_ids)
        if lowest_incoming <= expected:
            return None

        if row.last_event_at is not None:
            silence_s = (now - row.last_event_at).total_seconds()
            if silence_s >= stall_window_s:
                return None  # a renumbering already recovered, not this function's reason

        await _write_gap(
            session,
            bot_id=bot_id,
            reason=GAP_REASON_UPDATE_ID_JUMP,
            unrecoverable=True,
            gap_start_at=row.last_event_at or now,
            gap_end_at=now,
        )
        await session.commit()
        return GAP_REASON_UPDATE_ID_JUMP


async def resync_after_stall(
    session_factory: async_sessionmaker[AsyncSession],
    provider: TelegramProvider,
    *,
    bot_id: int,
    allowed_updates: Sequence[str],
    limit: int,
    timeout_s: int,
    stall_window_s: int,
) -> list[TelegramUpdate] | None:
    """The identifier-reset protocol (`contracts/telegram-provider.md` §5, D-TG-33): when
    `last_event_at` is older than `stall_window_s`, a strictly-forward offset can no longer ever
    receive Telegram's randomly-renumbered next identifier (Finding 1) — the poll would succeed,
    return empty, and do so forever while every health signal stayed green. Re-syncs by calling
    `get_updates(offset=None, …)`, the parameter omitted rather than sent negative, which the
    documentation defines as returning "the earliest unconfirmed update" regardless of numbering.

    Writes the `update_id_reset` gap (`unrecoverable=False` — nothing was lost, Telegram simply
    renumbered) and returns the re-synced batch for the caller to store and schedule exactly like
    any other batch, via `store_batch` then `record_reset_outcome`. Returns `None` when no stall
    was detected — the ordinary poll loop should proceed as normal.
    """
    now = datetime.now(UTC)
    async with session_factory() as session:
        last_event_at = (
            await session.execute(
                sa.select(ingestion_state.c.last_event_at).where(ingestion_state.c.bot_id == bot_id)
            )
        ).scalar_one_or_none()

    if last_event_at is None:
        return None
    if (now - last_event_at).total_seconds() < stall_window_s:
        return None

    resynced = await provider.get_updates(
        offset=None, limit=limit, timeout_s=timeout_s, allowed_updates=list(allowed_updates)
    )

    async with session_factory() as session:
        await _write_gap(
            session,
            bot_id=bot_id,
            reason=GAP_REASON_UPDATE_ID_RESET,
            unrecoverable=False,
            gap_start_at=last_event_at,
            gap_end_at=now,
        )
        await session.commit()

    return resynced


async def record_reset_outcome(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    bot_username: str | None,
    allowed_updates: Sequence[str],
    stored: Sequence[StoredUpdate],
) -> None:
    """Like `record_poll_outcome`, but assigns `last_update_id` / `last_event_at` unconditionally
    instead of `GREATEST`-ing against the stored batch — the one case where the confirmed
    position is allowed to move backwards (FR-019's documented exception, D-TG-33). Call this
    only for the batch `resync_after_stall` returned; every ordinary poll still uses
    `record_poll_outcome`, whose forward-only `GREATEST` is what makes G2 hold everywhere else.
    """
    highest = max((row.update_id for row in stored), default=None)

    insert_stmt = pg_insert(ingestion_state).values(
        bot_id=bot_id,
        bot_username=bot_username,
        last_update_id=highest,
        last_poll_at=sa.func.now(),
        last_success_at=sa.func.now(),
        last_event_at=sa.func.now() if highest is not None else None,
        consecutive_failures=0,
        consecutive_conflicts=0,
        allowed_updates=list(allowed_updates),
        updated_at=sa.func.now(),
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["bot_id"],
        set_={
            "bot_username": insert_stmt.excluded.bot_username,
            "last_update_id": insert_stmt.excluded.last_update_id,
            "last_poll_at": insert_stmt.excluded.last_poll_at,
            "last_success_at": insert_stmt.excluded.last_success_at,
            "last_event_at": insert_stmt.excluded.last_event_at,
            "consecutive_failures": insert_stmt.excluded.consecutive_failures,
            "consecutive_conflicts": insert_stmt.excluded.consecutive_conflicts,
            "allowed_updates": insert_stmt.excluded.allowed_updates,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )

    async with session_factory() as session:
        await session.execute(upsert_stmt)
        await session.commit()


def _chat_payload_for(raw: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The chat object a given update kind carries, if any — mirrors `client.py`'s
    `_chat_id_for` but returns the whole object, since chat discovery needs `type`/`title`/
    `username`, not just the id."""
    body = raw.get(kind)
    if not isinstance(body, dict):
        return None
    chat = body.get("chat")
    if isinstance(chat, dict) and "id" in chat:
        return chat
    if kind == "callback_query":
        message = body.get("message")
        if isinstance(message, dict):
            nested_chat = message.get("chat")
            if isinstance(nested_chat, dict) and "id" in nested_chat:
                return nested_chat
    return None


async def upsert_chats_from_batch(
    session_factory: async_sessionmaker[AsyncSession], *, updates: Sequence[TelegramUpdate]
) -> None:
    """Discovers and updates `telegram_chats` from a fetched batch (FR-026, FR-027, FR-028,
    D-TG-43).

    Identity fields (`chat_type`, `title`, `username`) and `last_event_at` are upserted from
    **any** chat-bearing update, because a bot already present in a group before capture started
    never emits a standing-change update — and those are precisely the groups a pilot begins
    with. `bot_status`, `bot_status_at` and `bot_can_delete` are written **only** from
    `my_chat_member`, each call recording the current observation rather than preserving the
    previous one: a group seen only through ordinary messages is left at the table's default
    `'unknown'`, never guessed as `'administrator'` — guessing would hide exactly the coverage
    failure this milestone exists to make visible. `is_monitored` is never touched here; it
    defaults false and is the operator's opt-in switch (FR-030).
    """
    async with session_factory() as session:
        for update in updates:
            chat = _chat_payload_for(update.raw, update.kind)
            if chat is None:
                continue

            identity_stmt = pg_insert(telegram_chats).values(
                chat_id=chat["id"],
                chat_type=chat.get("type", "unknown"),
                title=chat.get("title"),
                username=chat.get("username"),
                last_event_at=sa.func.now(),
            )
            await session.execute(
                identity_stmt.on_conflict_do_update(
                    index_elements=["chat_id"],
                    set_={
                        "chat_type": identity_stmt.excluded.chat_type,
                        "title": identity_stmt.excluded.title,
                        "username": identity_stmt.excluded.username,
                        "last_event_at": identity_stmt.excluded.last_event_at,
                        "updated_at": sa.func.now(),
                    },
                )
            )

            if update.kind == "my_chat_member":
                new_member = update.raw.get("my_chat_member", {}).get("new_chat_member") or {}
                await session.execute(
                    telegram_chats.update()
                    .where(telegram_chats.c.chat_id == chat["id"])
                    .values(
                        bot_status=new_member.get("status", "unknown"),
                        bot_status_at=sa.func.now(),
                        bot_can_delete=new_member.get("can_delete_messages"),
                        updated_at=sa.func.now(),
                    )
                )
        await session.commit()


async def apply_chat_migration_if_any(
    session_factory: async_sessionmaker[AsyncSession], *, update: TelegramUpdate
) -> None:
    """Links a supergroup promotion's old and new chat rows in both directions (FR-029, D-TG-44,
    `contracts/telegram-provider.md` §1 "service messages").

    Telegram delivers this as a service message carrying `migrate_to_chat_id` (on the **old**
    chat's stream) or its mirror `migrate_from_chat_id` (on the **new** chat's stream) — "the
    classic Telegram footgun" is that the mirror does not always land, so either one alone must
    be enough: each carries both identifiers, letting this function write both linking columns
    from a single observed event. No derived state was re-pointed here in TG-M1 — that arrives in
    TG-M2 as `repoint_for_migration`, called below once both rows exist: it moves the promoted
    group's ownership assignments to the surviving row and carries `is_monitored` /
    `injaz_course_id` forward (D-TG-54), which this function's own upserts leave at the table's
    defaults on the new row.
    """
    body = update.raw.get(update.kind)
    if not isinstance(body, dict):
        return
    migrate_to = body.get("migrate_to_chat_id")
    migrate_from = body.get("migrate_from_chat_id")
    if migrate_to is None and migrate_from is None:
        return

    if migrate_to is not None:
        old_chat_id, new_chat_id = update.chat_id, migrate_to
    else:
        old_chat_id, new_chat_id = migrate_from, update.chat_id
    # The chat stream carrying this service message always names its own chat; the other side
    # comes from the payload's own migrate_to/migrate_from field, checked non-None above.
    assert old_chat_id is not None and new_chat_id is not None

    async with session_factory() as session:
        old_stmt = pg_insert(telegram_chats).values(
            chat_id=old_chat_id, chat_type="unknown", migrated_to_chat_id=new_chat_id
        )
        await session.execute(
            old_stmt.on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"migrated_to_chat_id": new_chat_id, "updated_at": sa.func.now()},
            )
        )
        new_stmt = pg_insert(telegram_chats).values(
            chat_id=new_chat_id, chat_type="unknown", migrated_from_chat_id=old_chat_id
        )
        await session.execute(
            new_stmt.on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"migrated_from_chat_id": old_chat_id, "updated_at": sa.func.now()},
            )
        )
        await session.commit()

    await repoint_for_migration(session_factory, old_chat_id=old_chat_id, new_chat_id=new_chat_id)
