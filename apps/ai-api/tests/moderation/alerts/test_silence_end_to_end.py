"""SC-501: the system speaks only in the alert group (`contracts/alerting.md` §0, §9 N1; US1, T525).

One cycle end to end, as the actors run it: evaluate (`evaluate_alert_rules_once`), deliver every
returned id, answer one question, evaluate again, refresh every changed alert. Two monitored
groups have waiting questions and an unmonitored group exists beside the destination; every
Telegram call made carries the destination's `chat_id`, and only `sendMessage` and
`editMessageText` are called.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from app.application.moderation.alert_delivery import (
    DeliveryOutcome,
    RefreshOutcome,
    deliver,
    refresh,
)
from app.application.moderation.alerting import RenderSettings
from app.workers.tasks.moderation import evaluate_alert_rules as evaluate_alert_rules_module
from app.workers.tasks.moderation.evaluate_alert_rules import evaluate_alert_rules_once

from tests.moderation.alerts.conftest import Chat, ScriptedTelegram

SETTINGS = RenderSettings(panel_base_url="https://panel.invalid", retention_days=90)


async def test_every_call_of_a_full_cycle_goes_to_the_destination(
    alert_session_factory, make_rule, insert_item, insert_chat, end_item, fetch_alerts,
    scripted_telegram: ScriptedTelegram, destination_chat: Chat, source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    second_group = await insert_chat(title="Second course group")
    await insert_chat(title="Unmonitored", is_monitored=False)
    for group in (source_chat, second_group):
        await make_rule(trigger="question_waiting", telegram_chat_id=group.id, threshold_s=600)
    first = await insert_item(source_chat, opened_at=now - timedelta(minutes=40))
    second = await insert_item(second_group, opened_at=now - timedelta(minutes=20))

    # Cycle 1: fire and deliver.
    evaluation, changed = await evaluate_alert_rules_once(alert_session_factory, SETTINGS)
    ours = {a["id"] for s in (first, second) for a in await fetch_alerts("attention_item", s)}
    assert ours <= set(evaluation.to_deliver)
    assert len(ours) == 2
    for alert_id in sorted(ours):
        assert (
            await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
            is DeliveryOutcome.SENT
        )
    assert not ours & set(changed)

    # The first question is answered; cycle 2 edits its alert and nothing else.
    await end_item(first, "answered_member")
    evaluation, changed = await evaluate_alert_rules_once(alert_session_factory, SETTINGS)
    assert not ours & set(evaluation.to_deliver)  # nothing fires twice
    [first_alert] = await fetch_alerts("attention_item", first)
    assert ours & set(changed) == {first_alert["id"]}
    assert (
        await refresh(alert_session_factory, scripted_telegram.client, first_alert["id"], SETTINGS)
        is RefreshOutcome.EDITED
    )

    # Cycle 3: nothing more to say.
    evaluation, changed = await evaluate_alert_rules_once(alert_session_factory, SETTINGS)
    assert not ours & (set(evaluation.to_deliver) | set(changed))

    assert scripted_telegram.methods() == ["sendMessage", "sendMessage", "editMessageText"]
    assert {params["chat_id"] for _, params in scripted_telegram.calls} == {
        destination_chat.chat_id
    }


async def test_fired_alerts_are_handed_to_delivery_before_the_refresh_scan(
    alert_session_factory, make_rule, insert_item, fetch_alerts, source_chat: Chat, db_now,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now: datetime = await db_now()
    await make_rule(trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600)
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))

    async def _scan_fails(*_args: object) -> list[int]:
        raise RuntimeError("refresh scan failed")

    monkeypatch.setattr(evaluate_alert_rules_module, "changed_alerts", _scan_fails)
    handed: list[int] = []

    with pytest.raises(RuntimeError):
        await evaluate_alert_rules_once(
            alert_session_factory, SETTINGS, send_delivery=handed.append
        )

    [alert] = await fetch_alerts("attention_item", item_id)
    assert alert["id"] in handed  # not stranded as `pending`
