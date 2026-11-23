"""The evaluator framework (T517, `contracts/alerting.md` §3): the rule in force, FR-515's bound,
the dedupe key, repeats (F3), quiet hours (F5), one insert per subject per run (F6) and the refresh
scan.

No trigger is registered in Phase 2, so each test registers stand-in statements of the documented
shape. The trigger cases proper are `test_evaluate_triggers.py` (US1, US2, US5). Every rule here is
scoped to this test's own chat unless a case needs a global one: the database is shared, and a
global rule also fires on other tests' leftovers (purged with the rule at teardown).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation import alerting
from app.application.moderation.alert_render import render_state
from app.application.moderation.alerting import (
    RenderSettings,
    changed_alerts,
    evaluate_once,
)
from app.domain.moderation.alerting import Trigger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.alerts.conftest import Chat

SETTINGS = RenderSettings(panel_base_url=None, retention_days=90)

_WAITING = """
SELECT f.rule_id, f.chat_pk, 'attention_item' AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at,
       i.opened_at + f.threshold_s * interval '1 second' AS qualified_at
FROM rule_in_force f
JOIN attention_items i ON i.telegram_chat_id = f.chat_pk
WHERE i.status = 'open' AND now() - i.opened_at >= f.threshold_s * interval '1 second'
"""

_FLAGGED = """
SELECT f.rule_id, f.chat_pk, 'incident' AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at, i.detected_at AS qualified_at
FROM rule_in_force f
JOIN moderation_incidents i ON i.telegram_chat_id = f.chat_pk
JOIN moderation_incident_state s ON s.incident_id = i.id
WHERE s.status IN ('open', 'acknowledged')
"""

_UNHANDLED = """
SELECT f.rule_id, f.chat_pk, 'incident' AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at,
       i.detected_at + f.threshold_s * interval '1 second' AS qualified_at
FROM rule_in_force f
JOIN moderation_incidents i ON i.telegram_chat_id = f.chat_pk
JOIN moderation_incident_state s ON s.incident_id = i.id
WHERE s.status IN ('open', 'acknowledged')
  AND now() - i.detected_at >= f.threshold_s * interval '1 second'
"""


@pytest.fixture
def statements(monkeypatch: pytest.MonkeyPatch) -> dict[Trigger, str]:
    registry: dict[Trigger, str] = {}
    monkeypatch.setattr(alerting, "STATEMENTS", registry)
    return registry


async def _evaluate(session_factory: async_sessionmaker[AsyncSession]) -> alerting.Evaluation:
    async with session_factory() as session:
        return await evaluate_once(session)


async def test_a_qualifying_subject_fires_once(
    alert_session_factory, statements, make_rule, insert_item, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))

    first = await _evaluate(alert_session_factory)
    second = await _evaluate(alert_session_factory)

    [alert] = await fetch_alerts("attention_item", item_id)
    assert first.to_deliver == [alert["id"]]
    assert second.to_deliver == []
    assert alert["alert_rule_id"] == rule_id
    assert alert["repeat_index"] == 0
    assert alert["delivery_status"] == "pending"
    assert alert["dedupe_key"] == f"{rule_id}:attention_item:{item_id}:0"
    assert alert["qualified_at"] == now - timedelta(minutes=20)  # opened_at + threshold
    assert alert["rule_values"]["threshold_s"] == 600
    assert alert["rule_values"]["rule_chat_id"] == source_chat.id


async def test_a_disabled_chat_rule_mutes_the_global_one(
    alert_session_factory, statements, make_rule, insert_item, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    await make_rule(trigger="question_waiting", threshold_s=600)
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        is_enabled=False,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))

    await _evaluate(alert_session_factory)

    assert await fetch_alerts("attention_item", item_id) == []


async def test_the_chat_rule_wins_over_the_global_one(
    alert_session_factory, statements, make_rule, insert_item, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    await make_rule(trigger="question_waiting", threshold_s=60)
    chat_rule = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=3600
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))

    await _evaluate(alert_session_factory)
    assert await fetch_alerts("attention_item", item_id) == []  # 30 min < the chat's hour

    async with alert_session_factory() as session:
        await session.execute(
            sa.text("UPDATE attention_items SET opened_at = opened_at - interval '1 hour' "
                    "WHERE id = :id"),
            {"id": item_id},
        )
        await session.commit()
    await _evaluate(alert_session_factory)
    [alert] = await fetch_alerts("attention_item", item_id)
    assert alert["alert_rule_id"] == chat_rule


async def test_a_backlog_older_than_the_rule_is_not_alerted(
    alert_session_factory, statements, make_rule, insert_item, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        enabled_at=now - timedelta(minutes=10),
    )
    # Crossed its threshold 40 minutes ago, before the rule was switched on (FR-515).
    old = await insert_item(source_chat, opened_at=now - timedelta(minutes=50))
    # Crosses it 5 minutes ago, after.
    new = await insert_item(source_chat, opened_at=now - timedelta(minutes=15))

    await _evaluate(alert_session_factory)

    assert await fetch_alerts("attention_item", old) == []
    assert len(await fetch_alerts("attention_item", new)) == 1


async def test_a_repeat_is_due_by_the_clock_and_missed_ones_are_not_back_filled(
    alert_session_factory, statements, make_rule, insert_item, insert_alert, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        repeat_every_s=600,
        max_repeats=3,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    await insert_alert(
        rule_id=rule_id,
        chat=source_chat,
        subject_type="attention_item",
        subject_id=item_id,
        trigger="question_waiting",
        fired_at=now - timedelta(minutes=25),
        delivery_status="sent",
        sent_chat_id=-1,
        sent_message_id=1,
    )

    first = await _evaluate(alert_session_factory)
    second = await _evaluate(alert_session_factory)

    indexes = [a["repeat_index"] for a in await fetch_alerts("attention_item", item_id)]
    assert indexes == [0, 2]  # 25 min / 10 min = 2; index 1 is never back-filled
    assert len(first.to_deliver) == 1
    assert second.to_deliver == []


async def test_inside_quiet_hours_the_alert_is_suppressed(
    alert_session_factory, statements, make_rule, insert_item, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.QUESTION_WAITING] = _WAITING
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        # Together the two windows cover the whole day, whatever the hour of the run.
        quiet_hours=[{"from": "00:00", "to": "12:00"}, {"from": "12:00", "to": "00:00"}],
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))

    result = await _evaluate(alert_session_factory)

    [alert] = await fetch_alerts("attention_item", item_id)
    assert alert["delivery_status"] == "suppressed"
    assert result.suppressed == [alert["id"]]
    assert result.to_deliver == []


async def test_one_insert_per_subject_per_run(
    alert_session_factory, statements, make_rule, insert_incident, fetch_alerts,
    source_chat: Chat, db_now,
) -> None:
    statements[Trigger.INCIDENT_FLAGGED] = _FLAGGED
    statements[Trigger.INCIDENT_UNHANDLED] = _UNHANDLED
    now: datetime = await db_now()
    await make_rule(trigger="incident_flagged", telegram_chat_id=source_chat.id)
    await make_rule(
        trigger="incident_unhandled", telegram_chat_id=source_chat.id, threshold_s=600
    )
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(hours=1))

    await _evaluate(alert_session_factory)
    after_one: list[dict[str, Any]] = await fetch_alerts("incident", incident_id)
    await _evaluate(alert_session_factory)
    after_two: list[dict[str, Any]] = await fetch_alerts("incident", incident_id)

    assert [a["trigger"] for a in after_one] == ["incident_flagged"]
    assert [a["trigger"] for a in after_two] == ["incident_flagged", "incident_unhandled"]


async def test_the_refresh_scan_lists_an_alert_whose_subject_ended(
    alert_session_factory, statements, make_rule, insert_item, insert_alert,
    source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    alert_id = await insert_alert(
        rule_id=rule_id,
        chat=source_chat,
        subject_type="attention_item",
        subject_id=item_id,
        trigger="question_waiting",
        delivery_status="sent",
        sent_chat_id=-1,
        sent_message_id=1,
    )
    # Store the render state the alert would carry now, as delivery does.
    async with alert_session_factory() as session:
        alert = await alerting.load_alert(session, alert_id)
        assert alert is not None
        data = await alerting.build_render_input(session, alert, SETTINGS)
        await session.execute(
            sa.text("UPDATE alerts SET rendered_state = :state WHERE id = :id").bindparams(
                sa.bindparam("state", type_=JSONB())
            ),
            {"state": render_state(data), "id": alert_id},
        )
        await session.commit()

    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)

    async with alert_session_factory() as session:
        await session.execute(
            sa.text("UPDATE attention_items SET status = 'expired', closed_at = now(), "
                    "close_reason = 'expired' WHERE id = :id"),
            {"id": item_id},
        )
        await session.commit()

    assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
