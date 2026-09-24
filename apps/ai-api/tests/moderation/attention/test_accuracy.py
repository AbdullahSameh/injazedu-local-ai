"""T055 (US4): the rule set's precision and recall (`contracts/attention-metrics.md` §5, M15)
computed from a seeded mix of rule-opened, dismissed and operator-opened items match hand
arithmetic, grouped by `rule_version` — pooling versions would describe no rule set that ever
ran (M15). The query is quoted from the contract rather than re-expressed, since Phase 8's
`metrics.py` does not exist yet and this milestone's whole claim is that a figure is defensible
straight from stored rows (A5).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

_ACCURACY_SQL = sa.text(
    """
    SELECT
      count(*) FILTER (WHERE source = 'rule')                                 AS rule_opened,
      count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed')        AS rule_dismissed,
      count(*) FILTER (WHERE source = 'operator')                             AS operator_added,
      rule_version
    FROM attention_items
    WHERE opened_at >= :period_from AND opened_at < :period_to
    GROUP BY rule_version;
    """
)


async def _insert_item(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
    opened_at: datetime,
    source: str,
    rule_version: int | None,
    status: str,
) -> None:
    await session.execute(
        attention_items.insert().values(
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            opened_at=opened_at,
            source=source,
            rule_version=rule_version,
            status=status,
        )
    )


async def test_accuracy_figures_match_hand_arithmetic_grouped_by_rule_version(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat,
    insert_user,
    insert_message,
    attention_chat_id: int,
):
    period_start = datetime(2026, 2, 1, tzinfo=UTC)
    chat_id = await insert_chat(chat_id=attention_chat_id)
    student_id = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))

    # rule_version=1: five rule-opened items, two of them dismissed by an operator.
    rule_statuses = ["open", "open", "answered", "dismissed", "dismissed"]
    for index, status in enumerate(rule_statuses, start=1):
        await insert_message(
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            telegram_user_id=student_id,
        )
        async with attention_session_factory() as session:
            extra = (
                {
                    "first_response_message_id": 9_000 + index,
                    "first_response_at": period_start + timedelta(minutes=index, seconds=30),
                    "first_response_kind": "group_message",
                }
                if status == "answered"
                else {}
            )
            await session.execute(
                attention_items.insert().values(
                    telegram_chat_id=chat_id,
                    telegram_message_id=index,
                    opened_at=period_start + timedelta(minutes=index),
                    source="rule",
                    rule_version=1,
                    status=status,
                    **extra,
                )
            )
            await session.commit()

    # source='operator': three items an operator hand-opened because the rules missed them.
    for index in range(6, 9):
        await insert_message(
            telegram_chat_id=chat_id,
            message_id=index,
            sent_at=period_start + timedelta(minutes=index),
            telegram_user_id=student_id,
        )
        async with attention_session_factory() as session:
            await _insert_item(
                session,
                telegram_chat_id=chat_id,
                telegram_message_id=index,
                opened_at=period_start + timedelta(minutes=index),
                source="operator",
                rule_version=None,
                status="open",
            )
            await session.commit()

    async with attention_session_factory() as session:
        rows = (
            await session.execute(
                _ACCURACY_SQL,
                {
                    "period_from": period_start,
                    "period_to": period_start + timedelta(hours=1),
                },
            )
        ).mappings().all()

    by_rule_version = {row["rule_version"]: row for row in rows}
    rule_row = by_rule_version[1]
    operator_row = by_rule_version[None]

    assert rule_row["rule_opened"] == 5
    assert rule_row["rule_dismissed"] == 2
    assert rule_row["operator_added"] == 0
    assert operator_row["rule_opened"] == 0
    assert operator_row["operator_added"] == 3

    rule_opened = rule_row["rule_opened"]
    rule_dismissed = rule_row["rule_dismissed"]
    operator_added = operator_row["operator_added"]

    precision = 1 - (rule_dismissed / rule_opened)
    recall = rule_opened / (rule_opened + operator_added)

    assert precision == pytest.approx(0.6)
    assert recall == pytest.approx(0.625)
