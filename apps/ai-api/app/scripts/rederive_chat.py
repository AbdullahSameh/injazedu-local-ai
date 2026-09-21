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

from app.application.moderation.messages import apply_edit, derive_message
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import telegram_chats, telegram_updates

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
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:])))


if __name__ == "__main__":
    main()
