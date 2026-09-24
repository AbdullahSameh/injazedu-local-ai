"""`rederive_chat.py --with-attention` (T076-T077, D-TG-89, FR-082, FR-083).

`rederive_chat_attention` clears `attention_evaluated_at` for one chat's messages and re-judges
every affected burst inline through the same `assemble_burst`/`open_item` the live sweep uses,
then runs the ageing sweep scoped to that chat. This file drives it directly, the way
`rederive_chat.py`'s own `main()` does after the ordinary derive step.

`opened_at < now() - max_age_s` is the database's own `now()` (`contracts/attention-rules.md` §6
G2), never the package's `attention_clock` fixture — mirroring `test_ageing.py`'s own note — so
this file builds `sent_at` from real wall-clock offsets.

Each of the three scenarios (stays open, gets answered, ends up expired) gets its own chat: C10's
open-time lookback (`match_existing_responses`) resolves rule (b) against the *oldest open item in
the whole chat*, not just the burst being judged, so sharing one chat across scenarios would let
the "answered" scenario's moderator reply race the "expired" scenario's older, still-open item for
credit — a real contract rule (C3), not a bug, but one this test has no need to court.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from app.infrastructure.models_moderation import telegram_chats, telegram_messages
from app.scripts.rederive_chat import (
    AttentionRederiveReport,
    rederive_chat,
    rederive_chat_attention,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_GAP_S = 90
_MAX_AGE_S = 3600


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _build_open_only_chat(insert_chat: Any, insert_user: Any, insert_message: Any) -> int:
    platform_chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=platform_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=datetime.now(UTC),
        original_text="when is the deadline?",
    )
    return platform_chat_id


async def _build_answered_chat(
    insert_chat: Any, insert_user: Any, insert_moderator: Any, insert_message: Any
) -> int:
    platform_chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=platform_chat_id)
    now = datetime.now(UTC)
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_moderator(display_name="Owner")
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=now - timedelta(minutes=1),
        original_text="how do I submit?",
    )
    # Stored ahead of time, as if captured before this rederive ran, and a *direct* reply — rule
    # (a), C1 — so it resolves to this burst's own item regardless of what else is open elsewhere.
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        telegram_user_id=moderator["telegram_user_id"],
        sent_at=now - timedelta(seconds=30),
        is_from_moderator=True,
        original_text="submit it on the portal",
        reply_to_message_id=1,
    )
    return platform_chat_id


async def _build_expired_chat(insert_chat: Any, insert_user: Any, insert_message: Any) -> int:
    platform_chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=platform_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=datetime.now(UTC) - timedelta(hours=2),
        original_text="متى النتيجة؟",
    )
    return platform_chat_id


async def _run_all_three(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AttentionRederiveReport, AttentionRederiveReport, AttentionRederiveReport]:
    open_chat = await _build_open_only_chat(insert_chat, insert_user, insert_message)
    answered_chat = await _build_answered_chat(
        insert_chat, insert_user, insert_moderator, insert_message
    )
    expired_chat = await _build_expired_chat(insert_chat, insert_user, insert_message)

    reports = []
    for chat_id in (open_chat, answered_chat, expired_chat):
        reports.append(
            await rederive_chat_attention(
                attention_session_factory, chat_id=chat_id, gap_s=_GAP_S, max_age_s=_MAX_AGE_S
            )
        )
    return reports[0], reports[1], reports[2]


async def test_the_three_counts_are_correct(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    open_report, answered_report, expired_report = await _run_all_three(
        insert_chat, insert_user, insert_moderator, insert_message, attention_session_factory
    )

    assert (open_report.opened, open_report.answered, open_report.expired) == (1, 0, 0)
    assert (answered_report.opened, answered_report.answered, answered_report.expired) == (
        1,
        1,
        0,
    )
    assert (expired_report.opened, expired_report.answered, expired_report.expired) == (1, 0, 1)


async def test_running_it_twice_reports_zero_the_second_time_and_changes_nothing(
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_message: Any,
    count_items: Any,
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    platform_chat_id = await _build_answered_chat(
        insert_chat, insert_user, insert_moderator, insert_message
    )

    first = await rederive_chat_attention(
        attention_session_factory, chat_id=platform_chat_id, gap_s=_GAP_S, max_age_s=_MAX_AGE_S
    )
    assert (first.opened, first.answered, first.expired) == (1, 1, 0)

    async with attention_session_factory() as session:
        chat_pk = (
            await session.execute(
                sa.select(telegram_chats.c.id).where(telegram_chats.c.chat_id == platform_chat_id)
            )
        ).scalar_one()
    before_count = await count_items(telegram_chat_id=chat_pk)

    second = await rederive_chat_attention(
        attention_session_factory, chat_id=platform_chat_id, gap_s=_GAP_S, max_age_s=_MAX_AGE_S
    )

    assert (second.opened, second.answered, second.expired) == (0, 0, 0)
    assert await count_items(telegram_chat_id=chat_pk) == before_count


async def test_ordinary_derivation_never_touches_an_already_evaluated_message(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    fetch_message: Any,
    count_items: Any,
    attention_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-082: only `--with-attention` backfills. Plain `rederive_chat` walks `telegram_updates`
    for events to (re-)derive; a message that was already derived and already judged (declined,
    no item) sits outside that walk entirely — nothing about running it again clears
    `attention_evaluated_at` or opens an item for a message no new event named."""
    platform_chat_id = -_rand_id()
    chat_pk = await insert_chat(chat_id=platform_chat_id)
    student_id = await insert_user(tg_user_id=_rand_id())
    message_row_id = await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        telegram_user_id=student_id,
        sent_at=datetime.now(UTC),
        original_text="hi",
    )
    async with attention_session_factory() as session:
        await session.execute(
            telegram_messages.update()
            .where(telegram_messages.c.id == message_row_id)
            .values(attention_evaluated_at=sa.func.now())
        )
        await session.commit()

    # No telegram_updates rows exist for this chat, so this examines nothing to (re-)derive.
    report = await rederive_chat(attention_session_factory, chat_id=platform_chat_id)
    assert (report.examined, report.derived, report.skipped) == (0, 0, 0)

    after = await fetch_message(telegram_chat_id=chat_pk, message_id=1)
    assert after is not None
    assert after["attention_evaluated_at"] is not None
    assert await count_items(telegram_chat_id=chat_pk) == 0


def test_no_screen_control_ever_triggers_a_rederive() -> None:
    """FR-082's other half: `rederive_chat`/`--with-attention` is an operator's own manual step,
    never reachable from the panel (`quickstart.md` §6, contract §7 R2). The panel already
    documents the command in one field's help text (`TelegramChatForm`'s "Measured" toggle) so an
    operator knows it exists — a name is not a trigger. What actually matters is that the panel
    never *executes* anything: it must never shell out or invoke an Artisan command at all."""
    repo_root = Path(__file__).resolve().parents[5]
    pattern = re.compile(r"Process::|shell_exec\(|proc_open\(|popen\(|Artisan::call\(|\bexec\(")
    offenders = [
        path
        for directory in (
            repo_root / "apps" / "ai-control" / "app",
            repo_root / "apps" / "ai-control" / "resources" / "views",
        )
        for path in directory.rglob("*.php")
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
