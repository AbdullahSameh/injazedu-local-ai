"""FR-515: a rule alerts only on what crosses its threshold at or after it was last enabled, so a
backlog is never alerted (`contracts/alerting.md` §2 R8, §3 F1; US1, T522).

`enabled_at` is written by whoever enables the rule: the panel's toggle stamps it (S1, tested in
PHP with US4), and `ck_alert_rule_enabled_at` refuses an enabled rule without one. Here the rows
are written as the panel writes them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.moderation.alerts.conftest import Chat

THRESHOLD_S = 600


async def test_a_backlog_that_crossed_before_enabling_is_never_alerted(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD_S,
        enabled_at=now - timedelta(minutes=5),
    )
    # Crossed its threshold 6 minutes before the rule was switched on.
    backlog = await insert_item(source_chat, opened_at=now - timedelta(minutes=21))
    # Crossed it 1 minute after.
    fresh = await insert_item(source_chat, opened_at=now - timedelta(minutes=14))

    await evaluate()
    await evaluate()

    assert await fetch_alerts("attention_item", backlog) == []
    assert len(await fetch_alerts("attention_item", fresh)) == 1


async def test_re_enabling_starts_from_the_new_enabled_at(
    alert_session_factory, make_rule, insert_item, evaluate, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD_S,
        enabled_at=now - timedelta(days=1),
    )
    # Disabled: `enabled_at` is kept, the rule fires nothing.
    async with alert_session_factory() as session:
        await session.execute(
            sa.text("UPDATE alert_rules SET is_enabled = false WHERE id = :id"), {"id": rule_id}
        )
        await session.commit()
    while_off = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    await evaluate()
    assert await fetch_alerts("attention_item", while_off) == []

    # Re-enabled a minute ago, stamped then, as the panel's toggle does.
    async with alert_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE alert_rules SET is_enabled = true, "
                "enabled_at = now() - interval '60 seconds' WHERE id = :id"
            ),
            {"id": rule_id},
        )
        await session.commit()
    now = await db_now()
    # Crossed its threshold 30 seconds ago: after the new stamp.
    after = await insert_item(source_chat, opened_at=now - timedelta(seconds=THRESHOLD_S + 30))
    await evaluate()

    # The item that crossed while the rule was off is backlog under the new stamp.
    assert await fetch_alerts("attention_item", while_off) == []
    assert len(await fetch_alerts("attention_item", after)) == 1


async def test_an_enabled_rule_without_enabled_at_is_refused(
    alert_session_factory, source_chat: Chat
) -> None:
    async with alert_session_factory() as session:
        with pytest.raises(IntegrityError, match="ck_alert_rule_enabled_at"):
            await session.execute(
                sa.text(
                    "INSERT INTO alert_rules (trigger, telegram_chat_id, threshold_s, is_enabled) "
                    "VALUES ('question_waiting', :chat, 600, true)"
                ),
                {"chat": source_chat.id},
            )
        await session.rollback()


async def test_a_group_rule_replacing_the_global_one_does_not_re_alert(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    global_rule = await make_rule(trigger="question_waiting", threshold_s=THRESHOLD_S)
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    await evaluate()
    [alerted] = await fetch_alerts("attention_item", item_id)
    assert alerted["alert_rule_id"] == global_rule

    # The operator now gives the group its own rule, switched on now.
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=THRESHOLD_S,
        enabled_at=await db_now(),
    )
    await evaluate()

    assert [a["id"] for a in await fetch_alerts("attention_item", item_id)] == [alerted["id"]]
