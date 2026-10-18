"""The fourth dismissal reason, "Answered by a member" (`member_answered`;
`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 2, operator decision
2026-10-18). It is counted in its own breakdown column beside `rule_dismissed`, never in
"other". The parts still sum to the count (K9), and `rule_dismissed` itself is unchanged (K5).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from app.application.moderation.metrics import accuracy_by_rule_version
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_each_reason_has_its_own_part_and_the_parts_sum_to_rule_dismissed(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat,
    insert_user,
    insert_message,
    attention_chat_id: int,
) -> None:
    # Its own day: `test_accuracy.py` reads 2026-02-01 across every chat.
    period_start = datetime(2026, 2, 11, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    reasons = [
        "not_a_question",
        "member_discussion",
        "member_answered",
        "member_answered",
        "message_removed",
        "before_pilot",
    ]
    for index, reason in enumerate(reasons, start=1):
        await insert_message(
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            telegram_user_id=student_id,
        )
        async with attention_session_factory() as session:
            await session.execute(
                attention_items.insert().values(
                    telegram_chat_id=chat_id,
                    telegram_message_id=index,
                    opened_at=period_start + timedelta(minutes=index),
                    source="rule",
                    rule_version=1,
                    status="dismissed",
                    close_reason=reason,
                )
            )
            await session.commit()

    async with attention_session_factory() as session:
        [row] = await accuracy_by_rule_version(
            session,
            period_from=period_start,
            period_to=period_start + timedelta(hours=1),
            chat_id=chat_id,
        )

    assert row["rule_dismissed"] == 6
    assert row["dismissed_not_a_question"] == 1
    assert row["dismissed_member_discussion"] == 1
    assert row["dismissed_member_answered"] == 2
    assert row["dismissed_message_removed"] == 1
    assert row["dismissed_other"] == 1  # `before_pilot` and any other free text
    assert (
        row["dismissed_not_a_question"]
        + row["dismissed_member_discussion"]
        + row["dismissed_member_answered"]
        + row["dismissed_message_removed"]
        + row["dismissed_other"]
    ) == row["rule_dismissed"]
