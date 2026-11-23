"""Exactly once per rule, subject and repeat (`contracts/alerting.md` §3 F2, F3, F6, F8; US1, T521).

Repeats run on the database's clock from the first alert's `fired_at`. A test cannot move `now()`,
so it moves the alerts back instead: shifting every alert of a subject back by `s` seconds is the
same, to the schedule, as `s` seconds passing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import sqlalchemy as sa
from app.application.moderation.alerting import evaluate_once
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.moderation.alerts.conftest import Chat

EVERY = 600  # R
THRESHOLD = 600


async def _shift_back(
    session_factory: async_sessionmaker[AsyncSession], item_id: int, seconds: int
) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE alerts SET fired_at = fired_at - :s * interval '1 second' "
                "WHERE subject_type = 'attention_item' AND subject_id = :id"
            ),
            {"s": seconds, "id": item_id},
        )
        await session.commit()


async def _indexes(fetch_alerts, item_id: int) -> list[int]:
    return [a["repeat_index"] for a in await fetch_alerts("attention_item", item_id)]


async def test_two_evaluators_at_once_insert_one_alert(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=THRESHOLD
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))

    first, second = await asyncio.gather(evaluate(), evaluate())

    [alert] = await fetch_alerts("attention_item", item_id)
    delivered = [i for i in first.to_deliver + second.to_deliver if i == alert["id"]]
    assert delivered == [alert["id"]]  # only one evaluator was handed it


async def test_a_second_run_and_a_restart_insert_nothing(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now,
    alert_test_database_url: str,
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=THRESHOLD
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))

    await evaluate()
    again = await evaluate()
    # A restart: a new engine, nothing carried over in memory.
    engine = create_async_engine(alert_test_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            restarted = await evaluate_once(session)
    finally:
        await engine.dispose()

    [alert] = await fetch_alerts("attention_item", item_id)
    assert alert["id"] not in again.to_deliver
    assert alert["id"] not in restarted.to_deliver


async def test_repeats_come_every_interval_up_to_the_maximum(
    alert_session_factory, make_rule, insert_item, evaluate, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD,
        repeat_every_s=EVERY,
        max_repeats=2,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=2))

    await evaluate()
    assert await _indexes(fetch_alerts, item_id) == [0]

    await _shift_back(alert_session_factory, item_id, EVERY - 5)  # not yet one interval
    await evaluate()
    assert await _indexes(fetch_alerts, item_id) == [0]

    await _shift_back(alert_session_factory, item_id, 5)  # one interval since the first
    await evaluate()
    await evaluate()  # at least R apart: the same interval adds nothing more
    assert await _indexes(fetch_alerts, item_id) == [0, 1]

    await _shift_back(alert_session_factory, item_id, EVERY)
    await evaluate()
    assert await _indexes(fetch_alerts, item_id) == [0, 1, 2]

    await _shift_back(alert_session_factory, item_id, 10 * EVERY)  # past the maximum
    await evaluate()
    assert await _indexes(fetch_alerts, item_id) == [0, 1, 2]


async def test_after_an_outage_only_the_due_repeat_is_inserted(
    alert_session_factory, make_rule, insert_item, evaluate, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD,
        repeat_every_s=EVERY,
        max_repeats=5,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=3))
    await evaluate()

    # Three intervals pass with no evaluator running.
    await _shift_back(alert_session_factory, item_id, 3 * EVERY + 5)
    result = await evaluate()

    alerts = await fetch_alerts("attention_item", item_id)
    assert [a["repeat_index"] for a in alerts] == [0, 3]  # never 1 or 2 (N8)
    # At most one insert for the subject in the run (F6).
    assert [i for i in result.to_deliver if i in {a["id"] for a in alerts}] == [alerts[1]["id"]]


async def test_nothing_repeats_once_the_item_has_ended(
    alert_session_factory, make_rule, insert_item, end_item, evaluate, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD,
        repeat_every_s=EVERY,
        max_repeats=3,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    await evaluate()
    await end_item(item_id, "answered_member")

    await _shift_back(alert_session_factory, item_id, 2 * EVERY)
    await evaluate()

    assert await _indexes(fetch_alerts, item_id) == [0]
