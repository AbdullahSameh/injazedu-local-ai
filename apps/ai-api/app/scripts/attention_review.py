"""`attention_review` — Step 3's read-only measurement of the Live Attention Queue
(`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 3).

It writes nothing. The command runs in one read-only transaction and prints counts only:
outcomes, reasons, rule literals and booleans, never a message's text. It answers three questions
over a period of Asia/Riyadh days:

1. **What happened to the items?** One row per `(opener, outcome)`. Outcomes are
   `answered:<kind>`, `dismissed:<reason>` (`other` for free text), `expired` and `open`.
2. **Which rule signal opened the noise?** Rule-opened items whose text carries exactly one
   signal are counted by that signal and outcome (`opening_signals`). A literal whose single-signal
   items are mostly dismissed is a rule set v2 candidate. Items with several signals are only
   counted.
3. **Would the shadow "answered by a member" signal have been right?** The signal is a member's
   direct reply, then the asker's acknowledgement of it (`is_acknowledgement`), and no follow-up
   question from the asker. It is counted against what really happened. **Agreement** is the signal
   with `dismissed:member_answered`. **Dangerous** is the signal on an item a moderator answered by
   direct reply.

Composition root (`app/scripts/`), exempt from the moderation import boundary by directory.

    python -m app.scripts.attention_review --from 2026-10-18 --to 2026-10-31 [--chat <chat_pk>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moderation.attention import evaluate, is_acknowledgement, opening_signals
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine, make_session_factory

_RIYADH = ZoneInfo("Asia/Riyadh")
# The reasons the panel offers; anything else an operator or a one-off write left is `other`.
_REASONS = frozenset({"not_a_question", "member_discussion", "member_answered", "message_removed"})

_ITEMS_SQL = sa.text(
    """
    SELECT ai.id, ai.source, ai.status, ai.close_reason, ai.first_response_kind,
           ai.telegram_chat_id, ai.telegram_message_id, q.telegram_user_id AS asker
    FROM attention_items ai
    JOIN telegram_messages q
      ON q.telegram_chat_id = ai.telegram_chat_id AND q.message_id = ai.telegram_message_id
    WHERE ai.opened_at >= :period_from AND ai.opened_at < :period_to
      AND (CAST(:chat_id AS bigint) IS NULL OR ai.telegram_chat_id = CAST(:chat_id AS bigint))
    ORDER BY ai.id
    """
)
# The burst's members: the C1/C6 membership join.
_MEMBERS_SQL = sa.text(
    """
    SELECT m.message_id, m.normalized_text
    FROM telegram_messages m
    WHERE m.telegram_chat_id = :chat AND (m.attention_item_id = :item OR m.message_id = :anchor)
    """
)
# Direct replies to any member, from neither a moderator nor the asker.
_MEMBER_REPLIES_SQL = sa.text(
    """
    SELECT r.message_id
    FROM telegram_messages r
    WHERE r.telegram_chat_id = :chat
      AND r.reply_to_message_id = ANY(:members)
      AND NOT r.is_from_moderator
      AND r.telegram_user_id IS DISTINCT FROM :asker
    """
)
# The asker's own replies to those member replies.
_ASKER_BACK_SQL = sa.text(
    """
    SELECT b.normalized_text
    FROM telegram_messages b
    WHERE b.telegram_chat_id = :chat
      AND b.reply_to_message_id = ANY(:replies)
      AND b.telegram_user_id = :asker
    """
)


@dataclass
class Review:
    """The three tallies, keyed by plain labels — counts only, never text."""

    outcomes: Counter[tuple[str, str]] = field(default_factory=Counter)
    single_signal_outcomes: Counter[tuple[str, str]] = field(default_factory=Counter)
    several_signals: int = 0
    no_text_signal: int = 0
    shadow: Counter[tuple[bool, str]] = field(default_factory=Counter)


def outcome_label(status: str, close_reason: str | None, first_response_kind: str | None) -> str:
    """One item's outcome, as the review counts it."""
    if status == "answered":
        return f"answered:{first_response_kind}"
    if status == "dismissed":
        return f"dismissed:{close_reason if close_reason in _REASONS else 'other'}"
    return status


def member_answer_candidate(*, member_replies: int, asker_back: Sequence[str]) -> bool:
    """The shadow signal: another member replied, the asker acknowledged one of those replies,
    and none of the asker's replies back asks again (rule set v1 would open on it). Measured
    only — nothing reads it to act."""
    if member_replies == 0:
        return False
    if any(evaluate([text]) for text in asker_back):
        return False
    return any(is_acknowledgement(text) for text in asker_back)


async def review(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None
) -> Review:
    """Reads every item opened in `[period_from, period_to)` and tallies the three questions."""
    await session.execute(sa.text("SET TRANSACTION READ ONLY"))
    result = Review()
    items = (
        await session.execute(
            _ITEMS_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    for item in items:
        outcome = outcome_label(item["status"], item["close_reason"], item["first_response_kind"])
        result.outcomes[(item["source"], outcome)] += 1
        if item["source"] != "rule":
            continue

        chat = item["telegram_chat_id"]
        members = (
            await session.execute(
                _MEMBERS_SQL,
                {"chat": chat, "item": item["id"], "anchor": item["telegram_message_id"]},
            )
        ).all()
        signals = opening_signals([row.normalized_text for row in members])
        if len(signals) == 1:
            result.single_signal_outcomes[(signals[0], outcome)] += 1
        elif signals:
            result.several_signals += 1
        else:
            result.no_text_signal += 1

        replies = (
            await session.execute(
                _MEMBER_REPLIES_SQL,
                {
                    "chat": chat,
                    "members": [row.message_id for row in members],
                    "asker": item["asker"],
                },
            )
        ).scalars().all()
        asker_back: list[str] = []
        if replies:
            asker_back = [
                text
                for text in (
                    await session.execute(
                        _ASKER_BACK_SQL,
                        {"chat": chat, "replies": list(replies), "asker": item["asker"]},
                    )
                ).scalars()
                if text
            ]
        candidate = member_answer_candidate(member_replies=len(replies), asker_back=asker_back)
        result.shadow[(candidate, outcome)] += 1
    return result


def format_report(report: Review) -> str:
    """The printed report: plain lines of labels and counts."""
    lines = ["== 1. Outcomes by opener =="]
    lines += [
        f"{source:9} {outcome:32} {n}" for (source, outcome), n in sorted(report.outcomes.items())
    ]
    lines.append("")
    lines.append("== 2. Rule-opened items with exactly one text signal: signal x outcome ==")
    lines += [
        f"{signal:12} {outcome:32} {n}"
        for (signal, outcome), n in sorted(report.single_signal_outcomes.items())
    ]
    lines.append(f"several signals: {report.several_signals}")
    lines.append(f"no text signal (mention or reply to a moderator): {report.no_text_signal}")
    lines.append("")
    lines.append('== 3. Shadow "answered by a member" signal x outcome (rule-opened items) ==')
    lines += [
        f"{'signal' if candidate else 'no signal':10} {outcome:32} {n}"
        for (candidate, outcome), n in sorted(report.shadow.items())
    ]
    agreement = report.shadow[(True, "dismissed:member_answered")]
    dangerous = report.shadow[(True, "answered:direct_reply")]
    signalled = sum(n for (candidate, _), n in report.shadow.items() if candidate)
    lines.append(f"signal on {signalled} item(s): agreement {agreement}, dangerous {dangerous}")
    return "\n".join(lines)


def _riyadh_day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=_RIYADH)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--to", dest="date_to", type=date.fromisoformat, required=True, help="Inclusive day."
    )
    parser.add_argument(
        "--chat", type=int, default=None, help="A telegram_chats.id; every group if omitted."
    )
    return parser.parse_args(argv)


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)
    session_factory = make_session_factory(make_engine(load_settings()))
    period_from = _riyadh_day_start(args.date_from)
    period_to = _riyadh_day_start(args.date_to) + timedelta(days=1)
    async with session_factory() as session:
        report = await review(
            session, period_from=period_from, period_to=period_to, chat_id=args.chat
        )
        await session.rollback()
    scope = f"group {args.chat}" if args.chat is not None else "all groups"
    print(f"Attention review {args.date_from} .. {args.date_to} (Asia/Riyadh days), {scope}\n")
    print(format_report(report))
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:])))


if __name__ == "__main__":
    main()
