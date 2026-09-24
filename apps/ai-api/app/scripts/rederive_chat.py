"""`python -m app.scripts.rederive_chat` — catches a measured group up on what TG-M1 captured
before it was switched on (`contracts/message-derivation.md` §7, FR-020…FR-023, D-TG-53).

Composition root, exempt from the moderation import boundary by directory (`app/scripts/`, per
`tasks.md`'s Path Conventions) — the only module that may import both `app.application.moderation`
and shared infrastructure for this purpose. It calls the **same** `derive_message` / `apply_edit`
the live actor calls (§7 R3): a second derivation code path is a second set of bugs, and the
replay-convergence proof at TG-M10 depends on there being exactly one.

    python -m app.scripts.rederive_chat --chat <chat_id> [--since 2026-09-01] [--until 2026-09-08]

Refuses a chat that is not measured (§7 R1) — this is not a back door around the measurement
decision — and is never reachable from a screen (§7 R2, `control-panel-moderation.md`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.attention import assemble_burst, open_item
from app.application.moderation.messages import apply_edit, derive_message
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import (
    attention_items,
    telegram_chats,
    telegram_messages,
    telegram_updates,
)
from app.workers.tasks.moderation.expire_stale_items import expire_stale_items_once

_DERIVABLE_KINDS = ("message", "edited_message")

# Mirrors config.py's MODERATION_REDERIVE_BATCH_SIZE default. `rederive_chat` itself takes a
# plain int rather than calling `load_settings()` so it stays callable without the full app
# Settings (DATABASE_URL, REDIS_URL, …) being loadable — `main()` is where the configured
# override, if any, is resolved.
_DEFAULT_BATCH_SIZE = 500


class ChatNotMonitoredError(Exception):
    """The named chat is not measured — re-derivation refuses to run (§7 R1)."""


@dataclass(frozen=True)
class RederiveReport:
    """The three counts §7 R5 requires: examined, derived and skipped-because-purged."""

    examined: int
    derived: int
    skipped: int


@dataclass(frozen=True)
class AttentionRederiveReport:
    """`--with-attention`'s three counts (D-TG-89, FR-083): opened, answered and expired."""

    opened: int
    answered: int
    expired: int


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


async def rederive_chat(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> RederiveReport:
    """Walks `telegram_updates` for `chat_id` (the platform's own id) in `update_id` order, in
    batches bounded by `batch_size` (default: `MODERATION_REDERIVE_BATCH_SIZE`), and re-derives
    each `message` / `edited_message` event through the actor's own functions.

    Raises `ChatNotMonitoredError` when the chat is not measured. Returns a `RederiveReport` of
    examined / derived / skipped counts. Running it twice over the same range derives nothing
    further the second time — `messages.derive_message`'s `ON CONFLICT … DO NOTHING` guarantees
    it (§2(a), R7).
    """
    async with session_factory() as session:
        if not await _is_monitored(session, chat_id):
            raise ChatNotMonitoredError(f"chat {chat_id} is not measured — refusing to re-derive")

    examined = derived = skipped = 0
    last_update_id: int | None = None

    while True:
        conditions = [
            telegram_updates.c.chat_id == chat_id,
            telegram_updates.c.update_type.in_(_DERIVABLE_KINDS),
        ]
        if last_update_id is not None:
            conditions.append(telegram_updates.c.update_id > last_update_id)
        if since is not None:
            conditions.append(telegram_updates.c.received_at >= since)
        if until is not None:
            conditions.append(telegram_updates.c.received_at < until)

        async with session_factory() as session:
            batch = (
                await session.execute(
                    sa.select(
                        telegram_updates.c.id,
                        telegram_updates.c.update_id,
                        telegram_updates.c.update_type,
                        telegram_updates.c.payload_purged_at,
                    )
                    .where(*conditions)
                    .order_by(telegram_updates.c.update_id)
                    .limit(batch_size)
                )
            ).all()

        if not batch:
            break

        for row in batch:
            examined += 1
            last_update_id = row.update_id

            if row.payload_purged_at is not None:
                skipped += 1
                continue

            if row.update_type == "message":
                inserted_id = await derive_message(session_factory, update_row_id=row.id)
                if inserted_id is not None:
                    derived += 1
            else:
                rows_matched = await apply_edit(session_factory, update_row_id=row.id)
                if rows_matched:
                    derived += 1

        if len(batch) < batch_size:
            break

    return RederiveReport(examined=examined, derived=derived, skipped=skipped)


async def rederive_chat_attention(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    gap_s: int,
    max_age_s: int,
) -> AttentionRederiveReport:
    """`--with-attention`, default off (D-TG-89, FR-083, FR-082): clears `attention_evaluated_at`
    for every message of `chat_id` inside `[since, until)` — by `sent_at`, never `received_at` —
    and re-judges each affected burst inline through the **same** `assemble_burst`/`open_item` the
    live sweep uses (D-TG-88's "one judgement path, not two"), then runs the ageing sweep
    (`contracts/attention-rules.md` §6 G2) scoped to this chat so a catch-up run does not leave a
    newly-opened item artificially fresh past its own ceiling.

    Never called from a screen (§7 R2) and never scheduled — this is an operator's explicit,
    manual step. Running it twice over the same range reports zero the second time and changes no
    status: the guarded writes underneath (`ON CONFLICT DO NOTHING`, `UPDATE … WHERE status =
    'open'`) are idempotent by construction, and ordinary derivation (without this flag) opens
    items only for messages derived from now on — this is the only path that backfills.
    """
    async with session_factory() as session:
        chat_pk = await _chat_surrogate(session, chat_id)
        before_rows = (
            await session.execute(
                sa.select(attention_items.c.id, attention_items.c.status).where(
                    attention_items.c.telegram_chat_id == chat_pk
                )
            )
        ).all()
        before_status: dict[int, str] = {row.id: row.status for row in before_rows}

        conditions = [telegram_messages.c.telegram_chat_id == chat_pk]
        if since is not None:
            conditions.append(telegram_messages.c.sent_at >= since)
        if until is not None:
            conditions.append(telegram_messages.c.sent_at < until)
        await session.execute(
            telegram_messages.update().where(*conditions).values(attention_evaluated_at=None)
        )
        await session.commit()

    while True:
        async with session_factory() as session:
            claimed = (
                await session.execute(
                    sa.select(
                        telegram_messages.c.id,
                        telegram_messages.c.telegram_user_id,
                        telegram_messages.c.message_thread_id,
                        telegram_messages.c.sent_at,
                    )
                    .where(
                        telegram_messages.c.telegram_chat_id == chat_pk,
                        telegram_messages.c.attention_evaluated_at.is_(None),
                    )
                    .order_by(telegram_messages.c.sent_at)
                    .limit(200)
                )
            ).all()
            if not claimed:
                break

            covered: set[int] = set()
            for row in claimed:
                if row.id in covered:
                    continue
                if row.telegram_user_id is None:
                    await session.execute(
                        telegram_messages.update()
                        .where(telegram_messages.c.id == row.id)
                        .values(attention_evaluated_at=sa.func.now())
                    )
                    continue
                burst = await assemble_burst(
                    session,
                    telegram_chat_id=chat_pk,
                    telegram_user_id=row.telegram_user_id,
                    message_thread_id=row.message_thread_id,
                    around=row.sent_at,
                    gap_s=gap_s,
                )
                covered.update(member["id"] for member in burst)
                await open_item(session, burst)
            await session.commit()

    expired = await expire_stale_items_once(
        session_factory, max_age_s=max_age_s, telegram_chat_id=chat_pk
    )

    async with session_factory() as session:
        after_status = (
            await session.execute(
                sa.select(attention_items.c.id, attention_items.c.status).where(
                    attention_items.c.telegram_chat_id == chat_pk
                )
            )
        ).all()

    opened = sum(1 for item_id, _status in after_status if item_id not in before_status)
    answered = sum(
        1
        for item_id, status in after_status
        if status == "answered" and before_status.get(item_id) != "answered"
    )

    return AttentionRederiveReport(opened=opened, answered=answered, expired=expired)


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
    parser.add_argument(
        "--batch-size", type=int, default=None, help="Overrides MODERATION_REDERIVE_BATCH_SIZE."
    )
    parser.add_argument(
        "--with-attention",
        action="store_true",
        default=False,
        help=(
            "Also clears attention_evaluated_at for this chat and window and re-judges every "
            "affected burst inline (D-TG-89). Default off — this is the only path that backfills "
            "attention items; ordinary derivation never does."
        ),
    )
    return parser.parse_args(argv)


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    session_factory = make_session_factory(make_engine(settings))

    batch_size = args.batch_size or settings.moderation_rederive_batch_size

    try:
        report = await rederive_chat(
            session_factory,
            chat_id=args.chat,
            since=args.since,
            until=args.until,
            batch_size=batch_size,
        )
    except ChatNotMonitoredError as exc:
        print(f"rederive_chat: {exc}", file=sys.stderr)
        return 1

    print(f"examined={report.examined} derived={report.derived} skipped={report.skipped}")

    if args.with_attention:
        attention_report = await rederive_chat_attention(
            session_factory,
            chat_id=args.chat,
            since=args.since,
            until=args.until,
            gap_s=settings.moderation_burst_gap_s,
            max_age_s=settings.moderation_item_max_age_s,
        )
        print(
            f"attention: opened={attention_report.opened} "
            f"answered={attention_report.answered} expired={attention_report.expired}"
        )

    return 0


def main() -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:])))


if __name__ == "__main__":
    main()
