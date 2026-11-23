"""Edits (`contracts/alerting.md` §6 U1-U6): a posted alert follows its subject's derived state.

US1 (T524): the question cases — each way an item ends, "not modified", a deleted alert, the
retention crossing, an unchanged state and repeated edit failures. US2 (T531): each route an
incident ends by, with its `{actor}` and `{how}`. US5 adds the group cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.alert_delivery import (
    DeliveryOutcome,
    RefreshOutcome,
    deliver,
    refresh,
)
from app.application.moderation.alert_render import TEXT_NOT_HELD, format_time
from app.application.moderation.alerting import RenderSettings, changed_alerts
from app.domain.moderation.alerting import MAX_EDIT_ATTEMPTS
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.alerts.conftest import Chat, Moderator, ScriptedTelegram

SETTINGS = RenderSettings(panel_base_url=None, retention_days=90)
WORDS = "When is the final exam for this course?"


async def _row(session_factory: async_sessionmaker[AsyncSession], alert_id: int) -> dict[str, Any]:
    async with session_factory() as session:
        return dict(
            (
                await session.execute(
                    sa.text("SELECT * FROM alerts WHERE id = :id"), {"id": alert_id}
                )
            )
            .mappings()
            .one()
        )


async def _item(session_factory: async_sessionmaker[AsyncSession], item_id: int) -> tuple[Any, ...]:
    async with session_factory() as session:
        return tuple(
            (
                await session.execute(
                    sa.text("SELECT * FROM attention_items WHERE id = :id"), {"id": item_id}
                )
            ).one()
        )


@pytest.fixture
def sent_question(
    alert_session_factory, make_rule, insert_item, insert_alert, scripted_telegram,
    destination_chat: Chat, source_chat: Chat, db_now,
):
    """An open question and its `question_waiting` alert, delivered to the scripted destination."""

    async def _make(*, opened_ago: timedelta = timedelta(hours=1)) -> tuple[int, int]:
        now: datetime = await db_now()
        rule_id = await make_rule(
            trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600
        )
        item_id = await insert_item(source_chat, opened_at=now - opened_ago, text=WORDS)
        alert_id = await insert_alert(
            rule_id=rule_id,
            chat=source_chat,
            subject_type="attention_item",
            subject_id=item_id,
            trigger="question_waiting",
        )
        outcome = await deliver(
            alert_session_factory, scripted_telegram.client, alert_id, SETTINGS
        )
        assert outcome is DeliveryOutcome.SENT
        return alert_id, item_id

    return _make


@pytest.mark.parametrize(
    ("route", "by_moderator", "line"),
    [
        ("answered_moderator", True, "✅ أُجيب عنه — Sara الساعة {at}"),
        ("answered_member", False, "✅ أجاب عنه عضو الساعة {at}"),
        ("dismissed", True, "استُبعد — Sara الساعة {at}"),
        ("dismissed", False, "استُبعد — مشغّل اللوحة الساعة {at}"),
        ("expired", False, "انتهت مهلته الساعة {at} دون رد"),
    ],
)
async def test_each_way_a_question_ends_edits_the_alert_once(
    alert_session_factory, sent_question, end_item, scripted_telegram: ScriptedTelegram,
    destination_chat: Chat, moderator: Moderator, route: str, by_moderator: bool, line: str,
) -> None:
    alert_id, item_id = await sent_question()
    posted = await _row(alert_session_factory, alert_id)
    ended_at = await end_item(item_id, route, moderator=moderator if by_moderator else None)
    item_before = await _item(alert_session_factory, item_id)

    assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    again = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    # Ended, but its words are still held: still followed for the retention edit, unchanged now.
    assert (outcome, again) == (RefreshOutcome.EDITED, RefreshOutcome.UNCHANGED)
    [edit] = scripted_telegram.calls_to("editMessageText")
    assert edit["chat_id"] == destination_chat.chat_id
    assert edit["message_id"] == posted["sent_message_id"]
    assert line.format(at=format_time(ended_at, posted["fired_at"])) in edit["text"]
    assert "reply_markup" not in edit  # the keyboard is removed

    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is not None
    assert row["rendered_state"]["end"]["kind"] == route
    assert (row["edit_attempts"], row["last_edit_error_category"]) == (0, None)
    assert row["last_edit_at"] is not None
    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)
    assert await _item(alert_session_factory, item_id) == item_before  # U6


async def test_not_modified_counts_as_success(
    alert_session_factory, sent_question, end_item, scripted_telegram: ScriptedTelegram
) -> None:
    alert_id, item_id = await sent_question()
    await end_item(item_id, "expired")
    scripted_telegram.script(
        "editMessageText",
        (400, "Bad Request: message is not modified: specified new message content and "
              "reply markup are exactly the same"),
    )

    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.EDITED
    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is not None
    assert row["edit_attempts"] == 0


async def test_an_alert_deleted_in_telegram_is_final_and_its_excerpt_gone(
    alert_session_factory, sent_question, end_item, scripted_telegram: ScriptedTelegram
) -> None:
    alert_id, item_id = await sent_question()
    await end_item(item_id, "answered_member")
    scripted_telegram.script("editMessageText", (400, "Bad Request: message to edit not found"))

    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.GONE
    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is not None
    assert row["excerpt_shown"] is False
    assert row["last_edit_error_category"] == "telegram_message_gone"
    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)


async def test_crossing_the_retention_age_edits_the_excerpt_out(
    alert_session_factory, sent_question, scripted_telegram: ScriptedTelegram
) -> None:
    alert_id, _item_id = await sent_question(opened_ago=timedelta(days=2))
    assert (await _row(alert_session_factory, alert_id))["excerpt_shown"] is True
    # Two days old: past a one-day retention, as if the days had passed (FR-535).
    aged = RenderSettings(panel_base_url=None, retention_days=1)

    assert alert_id in await changed_alerts(alert_session_factory, aged)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, aged)

    assert outcome is RefreshOutcome.EDITED
    [edit] = scripted_telegram.calls_to("editMessageText")
    assert TEXT_NOT_HELD in edit["text"]
    assert "exam" not in edit["text"]
    assert edit["reply_markup"]["inline_keyboard"]  # still open: the keyboard stays
    row = await _row(alert_session_factory, alert_id)
    assert row["excerpt_shown"] is False
    assert row["final_at"] is None
    assert alert_id not in await changed_alerts(alert_session_factory, aged)


async def test_an_unchanged_state_is_not_edited(
    alert_session_factory, sent_question, scripted_telegram: ScriptedTelegram
) -> None:
    alert_id, _ = await sent_question()

    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.UNCHANGED
    assert scripted_telegram.calls_to("editMessageText") == []


async def test_failed_edits_are_retried_up_to_the_limit_then_left(
    alert_session_factory, sent_question, end_item, scripted_telegram: ScriptedTelegram
) -> None:
    alert_id, item_id = await sent_question()
    await end_item(item_id, "expired")
    scripted_telegram.script("editMessageText", *[(502, "Bad Gateway")] * MAX_EDIT_ATTEMPTS)

    outcomes = []
    for _ in range(MAX_EDIT_ATTEMPTS):
        assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
        outcomes.append(
            await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
        )

    assert outcomes == [RefreshOutcome.FAILED] * MAX_EDIT_ATTEMPTS
    row = await _row(alert_session_factory, alert_id)
    assert row["edit_attempts"] == MAX_EDIT_ATTEMPTS
    assert row["last_edit_error_category"] == "telegram_unreachable"
    assert row["final_at"] is None
    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)


# --- incidents (US2, T531) ---


@pytest.fixture
def sent_incident(
    alert_session_factory, make_rule, insert_incident, insert_alert, scripted_telegram,
    destination_chat: Chat, source_chat: Chat, db_now,
):
    """A live incident and its `incident_flagged` alert, delivered to the scripted destination."""

    async def _make() -> tuple[int, int]:
        now: datetime = await db_now()
        rule_id = await make_rule(trigger="incident_flagged", telegram_chat_id=source_chat.id)
        incident_id = await insert_incident(source_chat, detected_at=now - timedelta(minutes=20))
        alert_id = await insert_alert(
            rule_id=rule_id,
            chat=source_chat,
            subject_type="incident",
            subject_id=incident_id,
            trigger="incident_flagged",
        )
        outcome = await deliver(
            alert_session_factory, scripted_telegram.client, alert_id, SETTINGS
        )
        assert outcome is DeliveryOutcome.SENT
        return alert_id, incident_id

    return _make


@pytest.mark.parametrize(
    ("route", "by", "line"),
    [
        ("ban", "moderator", "✅ عولجت — Sara · بحظر العضو الساعة {at}"),
        ("expulsion", "moderator", "✅ عولجت — Sara · بطرده الساعة {at}"),
        ("restriction", "moderator", "✅ عولجت — Sara · بتقييده الساعة {at}"),
        ("ban", "anonymous", "✅ عولجت — مسؤول مجهول الهوية · بحظر العضو الساعة {at}"),
        ("restriction", "administrator", "✅ عولجت — مسؤول · بتقييده الساعة {at}"),
        ("eyes", "moderator", "✅ عولجت — Sara · بتفاعل 👀 الساعة {at}"),
        ("panel_resolve", "moderator", "✅ عولجت — Sara · من اللوحة الساعة {at}"),
        ("panel_resolve", "unlinked", "✅ عولجت — مشغّل اللوحة · من اللوحة الساعة {at}"),
        ("alert_handled", "moderator", "✅ عولجت — Sara · من التنبيه الساعة {at}"),
        ("panel_false_positive", "moderator", "🚫 ليست مخالفة — Sara الساعة {at}"),
        ("panel_false_positive", "unlinked", "🚫 ليست مخالفة — مشغّل اللوحة الساعة {at}"),
        ("alert_false_positive", "moderator", "🚫 ليست مخالفة — Sara الساعة {at}"),
    ],
)
async def test_each_way_an_incident_ends_edits_the_alert_with_its_actor_and_how(
    alert_session_factory, sent_incident, end_incident, scripted_telegram: ScriptedTelegram,
    destination_chat: Chat, moderator: Moderator, route: str, by: str, line: str,
) -> None:
    alert_id, incident_id = await sent_incident()
    posted = await _row(alert_session_factory, alert_id)
    ended_at = await end_incident(
        incident_id,
        route,
        moderator=moderator if by == "moderator" else None,
        actor=by if by in ("anonymous", "administrator") else "moderator",
        alert_id=alert_id,
    )

    assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.EDITED
    [edit] = scripted_telegram.calls_to("editMessageText")
    assert edit["chat_id"] == destination_chat.chat_id
    assert edit["message_id"] == posted["sent_message_id"]
    assert line.format(at=format_time(ended_at, posted["fired_at"])) in edit["text"]
    assert "reply_markup" not in edit  # the keyboard is removed
    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is not None
    assert row["rendered_state"]["status"] in ("resolved", "closed_false_positive")


async def test_an_acknowledged_incident_keeps_its_keyboard(
    alert_session_factory, sent_incident, end_incident, scripted_telegram: ScriptedTelegram,
    moderator: Moderator,
) -> None:
    alert_id, incident_id = await sent_incident()
    await end_incident(incident_id, "acknowledged", moderator=moderator)

    await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    for edit in scripted_telegram.calls_to("editMessageText"):
        assert edit["reply_markup"]["inline_keyboard"]
    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is None


# --- the group cases (US5, T545) ---


async def _set_chat(
    session_factory: async_sessionmaker[AsyncSession], chat_pk: int, **values: Any
) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    async with session_factory() as session:
        await session.execute(
            sa.text(f"UPDATE telegram_chats SET {sets} WHERE id = :id"), {"id": chat_pk, **values}
        )
        await session.commit()


@pytest.fixture
def sent_health(
    alert_session_factory, make_rule, insert_chat, insert_alert, scripted_telegram,
    destination_chat: Chat, db_now,
):
    """A monitored group and its health alert for the current episode, delivered to the scripted
    destination: `group_silent` two hours after its last event, or `bot_not_admin` after the bot
    was removed."""

    async def _make(trigger: str) -> tuple[int, Chat, datetime]:
        now: datetime = await db_now()
        episode_at = now - timedelta(hours=2)
        if trigger == "group_silent":
            chat: Chat = await insert_chat(title="Silent group", last_event_at=episode_at)
            rule_id = await make_rule(trigger=trigger, telegram_chat_id=chat.id, threshold_s=3600)
        else:
            chat = await insert_chat(
                title="Lost group", bot_status="left", bot_status_at=episode_at
            )
            rule_id = await make_rule(trigger=trigger, telegram_chat_id=chat.id)
        alert_id = await insert_alert(
            rule_id=rule_id,
            chat=chat,
            subject_type="chat",
            subject_id=chat.id,
            trigger=trigger,
            episode_at=episode_at,
        )
        outcome = await deliver(
            alert_session_factory, scripted_telegram.client, alert_id, SETTINGS
        )
        assert outcome is DeliveryOutcome.SENT
        return alert_id, chat, episode_at

    return _make


async def test_a_newer_event_edits_the_silence_alert_to_resumed(
    alert_session_factory, sent_health, scripted_telegram: ScriptedTelegram,
    destination_chat: Chat, db_now,
) -> None:
    alert_id, chat, _ = await sent_health("group_silent")
    [send] = scripted_telegram.calls_to("sendMessage")
    assert "🔇 لا نشاط مسجَّل في مجموعة" in send["text"]
    assert "reply_markup" not in send  # a health alert has no button (no panel URL set)
    posted = await _row(alert_session_factory, alert_id)
    resumed_at: datetime = await db_now()
    await _set_chat(alert_session_factory, chat.id, last_event_at=resumed_at)

    assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    again = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.EDITED
    assert again is not RefreshOutcome.EDITED
    [edit] = scripted_telegram.calls_to("editMessageText")
    assert edit["chat_id"] == destination_chat.chat_id
    assert edit["message_id"] == posted["sent_message_id"]
    assert f"عاد النشاط الساعة {format_time(resumed_at, posted['fired_at'])}" in edit["text"]
    row = await _row(alert_session_factory, alert_id)
    assert row["final_at"] is not None
    assert alert_id not in await changed_alerts(alert_session_factory, SETTINGS)


async def test_administrator_again_edits_the_standing_alert(
    alert_session_factory, sent_health, scripted_telegram: ScriptedTelegram, db_now,
) -> None:
    alert_id, chat, _ = await sent_health("bot_not_admin")
    [send] = scripted_telegram.calls_to("sendMessage")
    assert "🛑 البوت لم يعد مشرفاً في مجموعة" in send["text"]
    assert "حالة البوت: غادر" in send["text"]
    posted = await _row(alert_session_factory, alert_id)
    restored_at: datetime = await db_now()
    await _set_chat(
        alert_session_factory, chat.id, bot_status="administrator", bot_status_at=restored_at
    )

    assert alert_id in await changed_alerts(alert_session_factory, SETTINGS)
    outcome = await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)

    assert outcome is RefreshOutcome.EDITED
    [edit] = scripted_telegram.calls_to("editMessageText")
    at = format_time(restored_at, posted["fired_at"])
    assert f"تغيّرت حالة البوت الساعة {at}: مسؤول" in edit["text"]
    assert "حالة البوت: غادر" in edit["text"]  # the standing at firing stays in the body
    assert (await _row(alert_session_factory, alert_id))["final_at"] is not None


async def test_a_further_standing_change_ends_the_old_alert_and_opens_a_new_episode(
    alert_session_factory, sent_health, scripted_telegram: ScriptedTelegram, evaluate,
    fetch_alerts, db_now,
) -> None:
    alert_id, chat, episode_at = await sent_health("bot_not_admin")
    kicked_at: datetime = await db_now()
    await _set_chat(alert_session_factory, chat.id, bot_status="kicked", bot_status_at=kicked_at)

    await refresh(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
    await evaluate()

    [edit] = scripted_telegram.calls_to("editMessageText")
    assert "تغيّرت حالة البوت" in edit["text"] and "طُرد" in edit["text"]
    episodes = [a["episode_at"] for a in await fetch_alerts("chat", chat.id)]
    assert episodes == [episode_at, kicked_at]
