"""Attribution, amended by TG-M2.1 (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md`
G1, F1). An item is opened assigned to nobody, and `responsible_moderator_id` is no longer written.
It counts in the figures of everyone on the group's team at `opened_at`. A later handover never
moves it, because team history is history (O5), not because of a snapshot.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.application.moderation.assignments import handover, open_assignment
from app.application.moderation.identities import map_moderator
from app.application.moderation.metrics import unanswered_stats
from app.application.moderation.text import normalize
from app.infrastructure.models_moderation import attention_item_assignee
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _opened_for(
    session_factory: async_sessionmaker[AsyncSession], moderator_id: int, around: datetime
) -> int:
    """How many items count in this moderator's "my groups" figures around `around` (F1)."""
    async with session_factory() as session:
        stats = await unanswered_stats(
            session,
            period_from=around - timedelta(hours=1),
            period_to=around + timedelta(hours=1),
            moderator_id=moderator_id,
        )
    opened: int = stats["opened"]
    return opened


async def test_a_new_item_is_assigned_to_nobody_and_counts_for_the_team_then(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    moderator_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Owner"
    )

    assignment_id = await open_assignment(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=moderator_id
    )
    # `open_assignment` stamps `valid_from` from the database's own `now()`, not from
    # `attention_clock` — the question must be asked strictly after it to fall inside the
    # assignment's half-open interval.
    assignment = await fetch_assignment(assignment_id=assignment_id)
    at = assignment["valid_from"] + timedelta(seconds=5)

    question = "متى الاختبار؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=at,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )

    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=at)
    assert item_id is not None
    row = await fetch_item(item_id=item_id)
    assert row["responsible_moderator_id"] is None

    async with attention_session_factory() as session:
        assignee = (
            await session.execute(
                sa.select(attention_item_assignee).where(
                    attention_item_assignee.c.attention_item_id == item_id
                )
            )
        ).mappings().one()
    assert assignee["assigned_moderator_id"] is None
    assert await _opened_for(attention_session_factory, moderator_id, at) == 1


async def test_a_handover_after_the_item_opened_leaves_it_with_the_team_then(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    incumbent_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Incumbent"
    )
    successor_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Successor"
    )

    assignment_id = await open_assignment(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=incumbent_id
    )
    assignment = await fetch_assignment(assignment_id=assignment_id)
    # Asked exactly at `valid_from` (included): the handover below closes the incumbent at the
    # database's real `now()`, so a question dated after it would fall outside the ended interval.
    at = assignment["valid_from"]

    question = "متى الاختبار؟"
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=at,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_id = await judge_burst(telegram_chat_id=chat_pk, telegram_user_id=student_id, around=at)
    assert item_id is not None

    # The runbook's own smoke-test check for this milestone (A3): reassigning afterwards must
    # never move an existing item's attribution.
    await handover(attention_session_factory, telegram_chat_id=chat_pk, moderator_id=successor_id)

    assert await _opened_for(attention_session_factory, incumbent_id, at) == 1
    assert await _opened_for(attention_session_factory, successor_id, at) == 0


async def test_a_question_asked_exactly_at_valid_from_counts_for_the_incoming_member(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_item: Any,
    fetch_assignment: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    student_id = await insert_user(tg_user_id=_rand_id())
    incumbent_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Incumbent"
    )
    successor_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Successor"
    )

    incumbent_assignment_id = await open_assignment(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=incumbent_id
    )
    successor_assignment_id = await handover(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=successor_id
    )

    incumbent_row = await fetch_assignment(assignment_id=incumbent_assignment_id)
    successor_row = await fetch_assignment(assignment_id=successor_assignment_id)
    valid_to = incumbent_row["valid_to"]
    valid_from = successor_row["valid_from"]
    assert valid_to == valid_from  # one timestamp value bound to both sides of the handover

    question = "متى الاختبار؟"

    # Asked exactly at valid_from: attributes to the incoming (successor) owner.
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=valid_from,
        telegram_user_id=student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_at_from = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_id, around=valid_from
    )
    assert item_at_from is not None

    # Asked exactly at valid_to (the incumbent's own boundary, excluded for them — a different
    # sender so it forms its own burst): the same instant is valid_from for the successor,
    # included for them, so it still resolves to the incoming owner, never the outgoing one.
    other_student_id = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=valid_to,
        telegram_user_id=other_student_id,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_at_to = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=other_student_id, around=valid_to
    )
    assert item_at_to is not None
    # valid_to == valid_from here, so "at valid_to" is indistinguishable from "at valid_from" —
    # the half-open predicate puts both on the incoming member (successor), never the outgoing one.
    assert await _opened_for(attention_session_factory, successor_id, valid_from) == 2
    assert await _opened_for(attention_session_factory, incumbent_id, valid_from) == 0


async def test_metrics_charge_each_item_to_whoever_was_responsible_when_it_opened(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    judge_burst: Any,
    fetch_assignment: Any,
) -> None:
    """T070 (M-A4, FR-044), amended by TG-M2.1 F1: a moderator's per-period figures count the
    items whose group had them on its team at `opened_at` — read from team history, never from
    today's team. A moderator whose membership changed mid-period is charged each item to whoever
    was on the team when *that* question was asked, not to whoever is on it now.
    """
    chat_pk = await insert_chat(chat_id=-_rand_id())
    incumbent_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Incumbent"
    )
    successor_id = await map_moderator(
        attention_session_factory, tg_user_id=_rand_id(), display_name="Successor"
    )

    incumbent_assignment_id = await open_assignment(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=incumbent_id
    )
    incumbent_assignment = await fetch_assignment(assignment_id=incumbent_assignment_id)
    # At `valid_from` itself, for the reason given in the second test above.
    before_handover = incumbent_assignment["valid_from"]

    question = "متى الاختبار؟"
    student_before = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=before_handover,
        telegram_user_id=student_before,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_before = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_before, around=before_handover
    )
    assert item_before is not None

    successor_assignment_id = await handover(
        attention_session_factory, telegram_chat_id=chat_pk, moderator_id=successor_id
    )
    successor_assignment = await fetch_assignment(assignment_id=successor_assignment_id)
    after_handover = successor_assignment["valid_from"] + timedelta(seconds=5)

    student_after = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=after_handover,
        telegram_user_id=student_after,
        original_text=question,
        normalized_text=normalize(question),
    )
    item_after = await judge_burst(
        telegram_chat_id=chat_pk, telegram_user_id=student_after, around=after_handover
    )
    assert item_after is not None

    period_from = before_handover - timedelta(minutes=1)
    period_to = after_handover + timedelta(minutes=1)

    async with attention_session_factory() as session:
        incumbent_stats = await unanswered_stats(
            session, period_from=period_from, period_to=period_to, moderator_id=incumbent_id
        )
        successor_stats = await unanswered_stats(
            session, period_from=period_from, period_to=period_to, moderator_id=successor_id
        )

    # Both items fall in the same period. Even though the successor now owns the group, the
    # incumbent is still charged for the item asked while they were responsible, and the
    # successor is charged only for the one asked after the handover.
    assert incumbent_stats["opened"] == 1
    assert successor_stats["opened"] == 1
