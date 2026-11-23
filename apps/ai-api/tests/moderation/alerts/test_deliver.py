"""Delivery (`contracts/alerting.md` §4 V1-V6, T516): at most one post per alert, only to the
destination, and nothing else changes.

Each alert here is written directly (`insert_alert`), so delivery is tested without the evaluator.
Telegram is scripted (`ScriptedTelegram`): no network, no token.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from app.application.moderation import alert_delivery
from app.application.moderation.alert_delivery import (
    DESTINATION_MIGRATED,
    OUTBOUND_REFUSED,
    DeliveryOutcome,
    OutboundRefusedError,
    RefreshOutcome,
    deliver,
    guard_edit_target,
    guard_send_target,
    refresh,
)
from app.application.moderation.alerting import RenderSettings, changed_alerts, load_alert
from app.infrastructure.models_moderation import alerts
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.alerts.conftest import Chat, ScriptedTelegram, clear_destination

SETTINGS = RenderSettings(panel_base_url=None, retention_days=90)
WORDS = "When is the final exam for this course?"


async def _row(
    session_factory: async_sessionmaker[AsyncSession], alert_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            (await session.execute(sa.select(alerts).where(alerts.c.id == alert_id)))
            .mappings()
            .one()
        )
    return dict(row)


@pytest.fixture
def question_alert(make_rule, insert_item, insert_alert, source_chat: Chat, db_now):
    """An open question waiting an hour, and one pending `question_waiting` alert for it."""

    async def _make(**fields: Any) -> tuple[int, int]:
        now: datetime = await db_now()
        rule_id = await make_rule(trigger="question_waiting", threshold_s=600)
        item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1), text=WORDS)
        alert_id = await insert_alert(
            rule_id=rule_id,
            chat=source_chat,
            subject_type="attention_item",
            subject_id=item_id,
            trigger="question_waiting",
            **fields,
        )
        return alert_id, item_id

    return _make


# --- V4: success ---


async def test_a_delivered_alert_records_its_post(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _item_id = await question_alert()

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.SENT
    [params] = scripted_telegram.calls_to("sendMessage")
    assert params["chat_id"] == destination_chat.chat_id
    assert params["parse_mode"] == "HTML"
    assert params["link_preview_options"] == {"is_disabled": True}
    assert "⏳ سؤال ينتظر الرد" in params["text"]
    assert params["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"a:{alert_id}:t"

    row = await _row(alert_session_factory, alert_id)
    assert row["delivery_status"] == "sent"
    assert row["sent_chat_id"] == destination_chat.chat_id
    assert row["sent_message_id"] == 1001
    assert row["delivered_at"] is not None
    assert row["attempts"] == 1
    assert row["excerpt_shown"] is True
    assert row["final_at"] is None
    assert row["rendered_state"]["status"] == "open"
    assert row["rendered_state"]["excerpt"] is True
    # Never the text (D-TG-216).
    assert WORDS not in str(row)


async def test_a_sent_alert_is_never_posted_again(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _ = await question_alert()

    first = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    second = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert (first, second) == (DeliveryOutcome.SENT, DeliveryOutcome.NOT_CLAIMED)
    assert len(scripted_telegram.calls_to("sendMessage")) == 1


# --- V5: failures ---


async def test_a_connect_failure_is_retried_up_to_five_attempts_then_final(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _ = await question_alert()
    scripted_telegram.script("sendMessage", *[httpx.ConnectError("refused")] * 6)

    outcomes = [
        await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
        for _ in range(6)
    ]

    assert outcomes == [DeliveryOutcome.RETRY] * 4 + [
        DeliveryOutcome.FAILED,
        DeliveryOutcome.NOT_CLAIMED,
    ]
    assert len(scripted_telegram.calls_to("sendMessage")) == 5
    row = await _row(alert_session_factory, alert_id)
    assert row["delivery_status"] == "failed"
    assert row["attempts"] == 5
    assert row["last_error_category"] == "telegram_unreachable"
    assert row["last_error_at"] is not None


async def test_a_5xx_is_retried_and_the_next_attempt_posts(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _ = await question_alert()
    scripted_telegram.script("sendMessage", (502, "Bad Gateway"))

    first = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    second = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert (first, second) == (DeliveryOutcome.RETRY, DeliveryOutcome.SENT)
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["attempts"]) == ("sent", 2)


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("late"), httpx.RemoteProtocolError("dropped")]
)
async def test_an_unknown_outcome_is_never_retried(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert, failure: Exception,
) -> None:
    alert_id, _ = await question_alert()
    scripted_telegram.script("sendMessage", failure)

    first = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    second = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert (first, second) == (DeliveryOutcome.FAILED, DeliveryOutcome.NOT_CLAIMED)
    assert len(scripted_telegram.calls_to("sendMessage")) == 1
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["attempts"]) == ("failed", 1)
    assert row["last_error_category"] == "telegram_outcome_unknown"


async def test_a_migrated_destination_is_final(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _ = await question_alert()
    scripted_telegram.script(
        "sendMessage",
        (
            400,
            "Bad Request: group chat was upgraded to a supergroup chat",
            {"migrate_to_chat_id": -1001234567890},
        ),
    )

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.FAILED
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["last_error_category"]) == (
        "failed",
        DESTINATION_MIGRATED,
    )


# --- V2: the re-check ---


async def test_no_destination_is_not_sent(
    alert_session_factory, scripted_telegram: ScriptedTelegram, question_alert
) -> None:
    await clear_destination(alert_session_factory)
    alert_id, _ = await question_alert()

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.NOT_SENT
    assert scripted_telegram.calls == []
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["not_sent_reason"]) == ("not_sent", "no_destination")


async def test_an_ended_question_is_not_sent(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, item_id = await question_alert()
    async with alert_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE attention_items SET status = 'expired', closed_at = now(), "
                "close_reason = 'expired' WHERE id = :id"
            ),
            {"id": item_id},
        )
        await session.commit()

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.NOT_SENT
    assert scripted_telegram.calls == []
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["not_sent_reason"]) == ("not_sent", "subject_ended")


async def test_an_incident_closed_as_not_a_violation_is_not_sent(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    make_rule, insert_incident, insert_alert, insert_act, source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(trigger="incident_flagged")
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(minutes=5))
    await insert_act(
        source_chat,
        action_type="panel_false_positive",
        occurred_at=now - timedelta(minutes=1),
        incident_id=incident_id,
        panel_user_id=1,
        note="Not spam",
    )
    alert_id = await insert_alert(
        rule_id=rule_id,
        chat=source_chat,
        subject_type="incident",
        subject_id=incident_id,
        trigger="incident_flagged",
    )

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.NOT_SENT
    assert scripted_telegram.calls == []
    row = await _row(alert_session_factory, alert_id)
    assert row["not_sent_reason"] == "subject_ended"


async def test_a_suppressed_alert_is_never_claimed(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert,
) -> None:
    alert_id, _ = await question_alert(delivery_status="suppressed")

    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is DeliveryOutcome.NOT_CLAIMED
    assert scripted_telegram.calls == []
    row = await _row(alert_session_factory, alert_id)
    assert (row["delivery_status"], row["attempts"]) == ("suppressed", 0)


# --- V3/U2: the guards ---


async def test_the_send_guard_admits_only_the_destination(
    alert_session_factory, destination_chat: Chat, source_chat: Chat, insert_chat
) -> None:
    unmonitored = await insert_chat(is_monitored=False)
    async with alert_session_factory() as session:
        await guard_send_target(session, destination_chat.chat_id)
        for elsewhere in (source_chat.chat_id, unmonitored.chat_id):
            with pytest.raises(OutboundRefusedError):
                await guard_send_target(session, elsewhere)


async def test_the_send_guard_refuses_everything_without_a_destination(
    alert_session_factory, source_chat: Chat
) -> None:
    await clear_destination(alert_session_factory)
    async with alert_session_factory() as session:
        with pytest.raises(OutboundRefusedError):
            await guard_send_target(session, source_chat.chat_id)


async def test_the_edit_guard_refuses_a_monitored_chat_and_any_other_chat(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    source_chat: Chat, question_alert,
) -> None:
    # Planted: an alert that claims to have been posted in the monitored source group.
    alert_id, _ = await question_alert(
        delivery_status="sent", sent_chat_id=source_chat.chat_id, sent_message_id=77
    )

    async with alert_session_factory() as session:
        alert = await load_alert(session, alert_id)
        assert alert is not None
        with pytest.raises(OutboundRefusedError):
            await guard_edit_target(session, alert, source_chat.chat_id)
        with pytest.raises(OutboundRefusedError):
            await guard_edit_target(session, alert, destination_chat.chat_id)

    # Wired into the edit path: refused once, recorded, and never followed again.
    first = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    row = await _row(alert_session_factory, alert_id)
    second = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert first is RefreshOutcome.REFUSED
    assert row["last_edit_error_category"] == OUTBOUND_REFUSED
    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)
    assert second is RefreshOutcome.REFUSED
    assert scripted_telegram.calls == []


# --- V6/V7: nothing else changes, nothing is logged ---


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession], chat: Chat
) -> dict[str, list[Any]]:
    queries = {
        "attention_items": "SELECT * FROM attention_items WHERE telegram_chat_id = :c ORDER BY id",
        "moderation_incidents": (
            "SELECT * FROM moderation_incidents WHERE telegram_chat_id = :c ORDER BY id"
        ),
        "moderation_actions": (
            "SELECT * FROM moderation_actions WHERE telegram_chat_id = :c ORDER BY id"
        ),
        "moderation_incident_state": (
            "SELECT s.* FROM moderation_incident_state s JOIN moderation_incidents i "
            "ON i.id = s.incident_id WHERE i.telegram_chat_id = :c ORDER BY s.incident_id"
        ),
        "moderation_incident_assignee": (
            "SELECT a.* FROM moderation_incident_assignee a JOIN moderation_incidents i "
            "ON i.id = a.incident_id WHERE i.telegram_chat_id = :c ORDER BY a.incident_id"
        ),
        "attention_item_assignee": (
            "SELECT a.* FROM attention_item_assignee a JOIN attention_items i "
            "ON i.id = a.attention_item_id WHERE i.telegram_chat_id = :c "
            "ORDER BY a.attention_item_id"
        ),
    }
    async with session_factory() as session:
        return {
            name: [tuple(row) for row in (await session.execute(sa.text(sql), {"c": chat.id}))]
            for name, sql in queries.items()
        }


async def test_a_failed_delivery_changes_no_state(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    make_rule, insert_incident, insert_alert, insert_act, moderator, source_chat: Chat,
    question_alert, db_now,
) -> None:
    now: datetime = await db_now()
    question_id, _ = await question_alert()
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(minutes=5))
    async with alert_session_factory() as session:
        anchor = (
            await session.execute(
                sa.text("SELECT telegram_message_id FROM moderation_incidents WHERE id = :id"),
                {"id": incident_id},
            )
        ).scalar_one()
    await insert_act(
        source_chat,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=now - timedelta(minutes=2),
        actor=moderator,
        target_message_id=anchor,
    )
    incident_alert = await insert_alert(
        rule_id=await make_rule(trigger="incident_flagged"),
        chat=source_chat,
        subject_type="incident",
        subject_id=incident_id,
        trigger="incident_flagged",
    )
    scripted_telegram.script(
        "sendMessage", httpx.ConnectError("refused"), httpx.ReadTimeout("late")
    )
    before = await _snapshot(alert_session_factory, source_chat)

    await deliver(alert_session_factory, scripted_telegram.client, question_id, SETTINGS)
    await deliver(alert_session_factory, scripted_telegram.client, incident_alert, SETTINGS)

    assert await _snapshot(alert_session_factory, source_chat) == before
    assert before["moderation_incident_state"]  # the comparison saw the incident


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_no_log_line_carries_the_words(
    alert_session_factory, scripted_telegram: ScriptedTelegram, destination_chat: Chat,
    question_alert, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Captured on the module's own logger: elsewhere in the suite a logging configuration may
    # stop propagation or disable existing loggers, which would leave `caplog` empty.
    module_logger = logging.getLogger(alert_delivery.__name__)
    capture = _Capture()
    monkeypatch.setattr(module_logger, "disabled", False)
    monkeypatch.setattr(module_logger, "level", logging.DEBUG)
    module_logger.addHandler(capture)
    alert_id, _ = await question_alert()
    scripted_telegram.script("sendMessage", httpx.ConnectError("refused"))

    try:
        await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
        await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    finally:
        module_logger.removeHandler(capture)

    assert [r.getMessage() for r in capture.records] == [
        "alert delivery failed: telegram_unreachable (attempt 1)",
        "alert sent",
    ]
    for record in capture.records:
        assert "exam" not in str(record.__dict__)
        assert set(record.__dict__) & {"alert_id", "chat_id"} == {"alert_id", "chat_id"}
