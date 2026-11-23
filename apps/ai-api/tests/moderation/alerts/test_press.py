"""Presses (`contracts/alerting.md` §5 B1-B7): a button in the alert group is an act like a panel
act, recorded at most once, and only for a declared, active moderator.

US2 (T530): ✅ and 🚫 on an incident alert. US3 (T534): 🙋 on a question alert.

A press is a captured `callback_query` naming the posted alert's own message. Alerts are written
directly as posted (`sent_chat_id`, `sent_message_id`), so no test here depends on the evaluator.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from app.application.moderation.alert_delivery import DeliveryOutcome, deliver
from app.application.moderation.alert_press import derive_alert_press, press_answer
from app.application.moderation.alert_render import answer_text
from app.application.moderation.alerting import RenderSettings
from app.domain.moderation.alerting import PressAction, PressOutcome, encode_callback
from app.workers.tasks.moderation.answer_alert_press import answer_alert_press_once
from app.workers.tasks.moderation.process_update import process_update_row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.alerts.conftest import Chat, Moderator, ScriptedTelegram

SETTINGS = RenderSettings(panel_base_url=None, retention_days=90)


# --- helpers ---


@pytest_asyncio.fixture
def posted_alert(insert_alert, destination_chat: Chat):
    """An alert as `deliver` leaves it: `sent` to the destination, with its message id."""

    async def _post(
        *, rule_id: int, chat: Chat, subject_type: str, subject_id: int, trigger: str
    ) -> tuple[int, int]:
        message_id = random.randint(1, 2_000_000_000)
        alert_id = await insert_alert(
            rule_id=rule_id,
            chat=chat,
            subject_type=subject_type,
            subject_id=subject_id,
            trigger=trigger,
            delivery_status="sent",
            sent_chat_id=destination_chat.chat_id,
            sent_message_id=message_id,
        )
        return alert_id, message_id

    return _post


@pytest_asyncio.fixture
def press(insert_update, destination_chat: Chat):
    """A captured press: `from.id` pressed `data` on message `message_id` in `chat_id` (the
    destination by default). Returns the update's row id; its `received_at` is the database's
    `now()`."""

    async def _press(
        *,
        message_id: int,
        data: str,
        tg_user_id: int,
        chat_id: int | None = None,
    ) -> int:
        target = destination_chat.chat_id if chat_id is None else chat_id
        body: dict[str, Any] = {
            "id": f"cbq-{random.randint(1, 10**12)}",
            "from": {"id": tg_user_id, "is_bot": False, "first_name": "Someone"},
            "message": {
                "message_id": message_id,
                "chat": {"id": target, "type": "supergroup"},
                "date": 0,
            },
            "chat_instance": "1",
            "data": data,
        }
        row_id: int = await insert_update("callback_query", body, chat_id=target)
        return row_id

    return _press


async def _acts(
    session_factory: async_sessionmaker[AsyncSession], *, alert_id: int | None = None,
    update_id: int | None = None,
) -> list[dict[str, Any]]:
    clauses, params = [], {}
    if alert_id is not None:
        clauses.append("alert_id = :alert")
        params["alert"] = alert_id
    if update_id is not None:
        clauses.append("source_update_id = :update")
        params["update"] = update_id
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT * FROM moderation_actions WHERE " + " AND ".join(clauses)
                    + " ORDER BY id"
                ),
                params,
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def _one(
    session_factory: async_sessionmaker[AsyncSession], sql: str, **params: Any
) -> dict[str, Any]:
    async with session_factory() as session:
        return dict((await session.execute(sa.text(sql), params)).mappings().one())


async def _received_at(session_factory: async_sessionmaker[AsyncSession], update: int) -> datetime:
    row = await _one(session_factory, "SELECT received_at FROM telegram_updates WHERE id = :id",
                     id=update)
    received: datetime = row["received_at"]
    return received


@pytest_asyncio.fixture
async def incident_alert(make_rule, insert_incident, posted_alert, source_chat: Chat, db_now):
    """A live incident and its posted `incident_flagged` alert: `(incident_id, alert_id,
    message_id)`."""
    now: datetime = await db_now()
    rule_id = await make_rule(trigger="incident_flagged", telegram_chat_id=source_chat.id)
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(minutes=20))
    alert_id, message_id = await posted_alert(
        rule_id=rule_id, chat=source_chat, subject_type="incident", subject_id=incident_id,
        trigger="incident_flagged",
    )
    return incident_id, alert_id, message_id


@pytest_asyncio.fixture
async def question_alert(make_rule, insert_item, posted_alert, source_chat: Chat, db_now):
    """An open question and its posted `question_waiting` alert: `(item_id, alert_id,
    message_id)`."""
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    alert_id, message_id = await posted_alert(
        rule_id=rule_id, chat=source_chat, subject_type="attention_item", subject_id=item_id,
        trigger="question_waiting",
    )
    return item_id, alert_id, message_id


def _data(alert_id: int, action: PressAction) -> str:
    return encode_callback(alert_id, action)


# --- incidents: ✅ and 🚫 (US2, T530) ---


async def test_handled_resolves_the_incident_and_assigns_the_team_member(
    alert_session_factory, incident_alert, press, moderator: Moderator, source_chat: Chat,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=moderator.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.RECORDED
    [act] = await _acts(alert_session_factory, alert_id=alert_id)
    assert act["action_type"] == "alert_handled"
    assert act["action_strength"] == "confirmation"
    assert act["moderation_incident_id"] == incident_id
    assert act["source_update_id"] == update
    assert act["telegram_chat_id"] == source_chat.id  # the source group, never the alert group
    assert act["actor_moderator_id"] == moderator.moderator_id
    assert act["actor_telegram_user_id"] == moderator.telegram_user_id
    assert act["panel_user_id"] is None
    assert act["occurred_at"] == await _received_at(alert_session_factory, update)  # B3
    state = await _one(
        alert_session_factory,
        "SELECT s.status, s.resolution_kind, s.resolved_by_moderator_id, "
        "       a.assigned_moderator_id, a.assigned_via "
        "FROM moderation_incident_state s "
        "JOIN moderation_incident_assignee a ON a.incident_id = s.incident_id "
        "WHERE s.incident_id = :id",
        id=incident_id,
    )
    assert state == {
        "status": "resolved",
        "resolution_kind": "alert_handled",
        "resolved_by_moderator_id": moderator.moderator_id,
        "assigned_moderator_id": moderator.moderator_id,
        "assigned_via": "alert_handled",
    }


async def test_not_a_violation_closes_the_incident_as_a_false_positive(
    alert_session_factory, incident_alert, press, moderator: Moderator,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id,
                         data=_data(alert_id, PressAction.FALSE_POSITIVE),
                         tg_user_id=moderator.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.RECORDED
    [act] = await _acts(alert_session_factory, alert_id=alert_id)
    assert act["action_type"] == "alert_false_positive"
    assert act["action_strength"] is None
    assert act["note"] is None
    state = await _one(
        alert_session_factory,
        "SELECT status, close_kind, closed_by_moderator_id, closed_by_user_id "
        "FROM moderation_incident_state WHERE incident_id = :id",
        id=incident_id,
    )
    assert state == {
        "status": "closed_false_positive",
        "close_kind": "alert_false_positive",
        "closed_by_moderator_id": moderator.moderator_id,
        "closed_by_user_id": None,
    }


async def test_an_outsider_moderator_resolves_without_being_assigned(
    alert_session_factory, incident_alert, press, insert_moderator,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    outsider: Moderator = await insert_moderator(display_name="Omar")  # on no team
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=outsider.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.RECORDED
    state = await _one(
        alert_session_factory,
        "SELECT s.status, a.assigned_moderator_id FROM moderation_incident_state s "
        "JOIN moderation_incident_assignee a ON a.incident_id = s.incident_id "
        "WHERE s.incident_id = :id",
        id=incident_id,
    )
    assert state == {"status": "resolved", "assigned_moderator_id": None}


@pytest.mark.parametrize("who", ["unknown", "inactive", "declared_after"])
async def test_a_press_by_anyone_but_an_active_declared_moderator_records_nothing(
    alert_session_factory, incident_alert, press, insert_moderator, source_chat: Chat,
    db_now, who: str,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    if who == "unknown":
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
    elif who == "inactive":
        tg_user_id = (
            await insert_moderator(display_name="Former", team_chat=source_chat, is_active=False)
        ).tg_user_id
    else:
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=tg_user_id)
    if who == "declared_after":
        # The same person, declared a minute after their press arrived.
        later = await _received_at(alert_session_factory, update) + timedelta(minutes=1)
        async with alert_session_factory() as session:
            telegram_user_id = (
                await session.execute(
                    sa.text(
                        "INSERT INTO telegram_users (tg_user_id, display_name) "
                        "VALUES (:tg, 'Late') RETURNING id"
                    ),
                    {"tg": tg_user_id},
                )
            ).scalar_one()
            await session.execute(
                sa.text(
                    "INSERT INTO moderators (telegram_user_id, display_name, is_active, "
                    "created_at) VALUES (:u, 'Late', true, :at)"
                ),
                {"u": telegram_user_id, "at": later},
            )
            await session.commit()

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.NOT_A_MODERATOR
    assert await _acts(alert_session_factory, update_id=update) == []
    state = await _one(
        alert_session_factory,
        "SELECT status FROM moderation_incident_state WHERE incident_id = :id", id=incident_id,
    )
    assert state["status"] == "open"


@pytest.mark.parametrize("forgery", ["other_alert", "take_on_incident", "not_an_alert", "garbage",
                                     "other_chat"])
async def test_a_press_that_fails_the_gate_is_invalid(
    alert_session_factory, incident_alert, question_alert, press, moderator: Moderator,
    insert_chat, forgery: str,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    _item_id, question_alert_id, _ = question_alert
    data, target_message, chat_id = _data(alert_id, PressAction.HANDLED), message_id, None
    if forgery == "other_alert":
        data = _data(question_alert_id, PressAction.HANDLED)
    elif forgery == "take_on_incident":
        data = _data(alert_id, PressAction.TAKE)
    elif forgery == "not_an_alert":
        target_message = random.randint(1, 2_000_000_000)
    elif forgery == "garbage":
        data = f"a:{alert_id}:h:extra"
    else:
        chat_id = (await insert_chat(title="Elsewhere", is_monitored=False)).chat_id
    update = await press(message_id=target_message, data=data, tg_user_id=moderator.tg_user_id,
                         chat_id=chat_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.INVALID
    assert await _acts(alert_session_factory, update_id=update) == []


async def test_a_press_on_an_incident_already_ended_records_nothing(
    alert_session_factory, incident_alert, press, end_incident, moderator: Moderator,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    await end_incident(incident_id, "panel_resolve")
    update = await press(message_id=message_id,
                         data=_data(alert_id, PressAction.FALSE_POSITIVE),
                         tg_user_id=moderator.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.ALREADY_ENDED
    assert await _acts(alert_session_factory, alert_id=alert_id) == []
    answer = await press_answer(alert_session_factory, update, outcome)
    assert answer.text == "انتهى هذا البند: عولجت"


async def test_two_concurrent_presses_record_one_act(
    alert_session_factory, incident_alert, press, moderator: Moderator, insert_moderator,
    source_chat: Chat,
) -> None:
    incident_id, alert_id, message_id = incident_alert
    other: Moderator = await insert_moderator(display_name="Huda", team_chat=source_chat)
    first = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                        tg_user_id=moderator.tg_user_id)
    second = await press(message_id=message_id,
                         data=_data(alert_id, PressAction.FALSE_POSITIVE),
                         tg_user_id=other.tg_user_id)

    outcomes = await asyncio.gather(
        derive_alert_press(alert_session_factory, first),
        derive_alert_press(alert_session_factory, second),
    )

    assert sorted(outcomes) == sorted([PressOutcome.RECORDED, PressOutcome.ALREADY_ENDED])
    assert len(await _acts(alert_session_factory, alert_id=alert_id)) == 1


async def test_re_running_one_press_gives_one_act_and_the_same_outcome(
    alert_session_factory, incident_alert, press, moderator: Moderator,
) -> None:
    _incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=moderator.tg_user_id)

    outcomes = [await derive_alert_press(alert_session_factory, update) for _ in range(2)]
    outcomes += await asyncio.gather(
        derive_alert_press(alert_session_factory, update),
        derive_alert_press(alert_session_factory, update),
    )

    assert outcomes == [PressOutcome.RECORDED] * 4
    assert len(await _acts(alert_session_factory, alert_id=alert_id)) == 1


async def test_process_update_derives_the_press_then_enqueues_its_answer(
    alert_session_factory, incident_alert, press, moderator: Moderator,
) -> None:
    _incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=moderator.tg_user_id)
    enqueued: list[tuple[int, str]] = []

    await process_update_row(
        alert_session_factory, update, send_answer=lambda *args: enqueued.append(args)
    )

    assert enqueued == [(update, "recorded")]
    assert len(await _acts(alert_session_factory, alert_id=alert_id)) == 1
    processed = await _one(
        alert_session_factory, "SELECT processed_at FROM telegram_updates WHERE id = :id",
        id=update,
    )
    assert processed["processed_at"] is not None


async def test_deriving_a_press_calls_no_telegram_method(
    alert_session_factory, incident_alert, press, moderator: Moderator,
    scripted_telegram: ScriptedTelegram,
) -> None:
    _incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=moderator.tg_user_id)

    await derive_alert_press(alert_session_factory, update)

    assert scripted_telegram.calls == []


@pytest.mark.parametrize(
    ("outcome", "action", "expected"),
    [
        (PressOutcome.RECORDED, PressAction.HANDLED, "تم: عولجت المخالفة"),
        (PressOutcome.RECORDED, PressAction.FALSE_POSITIVE, "تم: أُغلقت كرصد خاطئ"),
        (PressOutcome.NOT_A_MODERATOR, PressAction.HANDLED, "هذه الأزرار للمشرفين المعتمدين فقط"),
        (PressOutcome.INVALID, PressAction.TAKE, "هذا الزر لم يعد صالحاً"),
    ],
)
async def test_the_answer_actor_answers_each_outcome_in_the_alert_group_only(
    alert_session_factory, incident_alert, press, moderator: Moderator, insert_moderator,
    scripted_telegram: ScriptedTelegram, destination_chat: Chat, outcome: PressOutcome,
    action: PressAction, expected: str,
) -> None:
    _incident_id, alert_id, message_id = incident_alert
    presser = (
        moderator if outcome is not PressOutcome.NOT_A_MODERATOR
        else Moderator(0, 0, random.randint(10_000_000, 2_000_000_000), "Nobody")
    )
    update = await press(message_id=message_id, data=_data(alert_id, action),
                         tg_user_id=presser.tg_user_id)
    derived = await derive_alert_press(alert_session_factory, update)
    assert derived is outcome

    await answer_alert_press_once(
        alert_session_factory, scripted_telegram.client, SETTINGS, update, derived
    )

    [answer] = scripted_telegram.calls_to("answerCallbackQuery")
    assert answer["text"] == expected
    assert answer["callback_query_id"].startswith("cbq-")
    edits = scripted_telegram.calls_to("editMessageText")
    assert all(edit["chat_id"] == destination_chat.chat_id for edit in edits)
    assert set(scripted_telegram.methods()) <= {"answerCallbackQuery", "editMessageText"}


async def test_a_press_too_old_to_answer_is_ignored_and_the_alert_still_refreshed(
    alert_session_factory, incident_alert, press, moderator: Moderator,
    scripted_telegram: ScriptedTelegram,
) -> None:
    _incident_id, alert_id, message_id = incident_alert
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.HANDLED),
                         tg_user_id=moderator.tg_user_id)
    outcome = await derive_alert_press(alert_session_factory, update)
    scripted_telegram.script(
        "answerCallbackQuery",
        (400, "Bad Request: query is too old and response timeout expired or query ID is invalid"),
    )

    await answer_alert_press_once(
        alert_session_factory, scripted_telegram.client, SETTINGS, update, outcome
    )

    assert scripted_telegram.methods() == ["answerCallbackQuery", "editMessageText"]


# --- questions: 🙋 (US3, T534) ---


async def _item(session_factory: async_sessionmaker[AsyncSession], item_id: int) -> dict[str, Any]:
    return await _one(
        session_factory,
        "SELECT i.status, i.opened_at, i.first_response_at, a.assigned_moderator_id, "
        "       a.assigned_via "
        "FROM attention_items i LEFT JOIN attention_item_assignee a "
        "  ON a.attention_item_id = i.id WHERE i.id = :id",
        id=item_id,
    )


async def test_a_team_member_takes_the_question_without_closing_it(
    alert_session_factory, question_alert, press, moderator: Moderator, source_chat: Chat,
) -> None:
    item_id, alert_id, message_id = question_alert
    before = await _item(alert_session_factory, item_id)
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                         tg_user_id=moderator.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.RECORDED
    [act] = await _acts(alert_session_factory, alert_id=alert_id)
    assert act["action_type"] == "alert_take"
    assert act["moderation_incident_id"] is None
    assert act["telegram_chat_id"] == source_chat.id
    after = await _item(alert_session_factory, item_id)
    assert (after["status"], after["opened_at"], after["first_response_at"]) == (
        before["status"], before["opened_at"], before["first_response_at"]
    ) == ("open", before["opened_at"], None)
    assert (after["assigned_moderator_id"], after["assigned_via"]) == (
        moderator.moderator_id, "alert"
    )
    answer = await press_answer(alert_session_factory, update, outcome)
    assert answer.text == "تم: السؤال لك"


async def test_a_take_by_a_moderator_off_the_team_is_recorded_and_assigns_nobody(
    alert_session_factory, question_alert, press, insert_moderator,
) -> None:
    item_id, alert_id, message_id = question_alert
    outsider: Moderator = await insert_moderator(display_name="Omar")
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                         tg_user_id=outsider.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.RECORDED_NOT_TEAM
    assert len(await _acts(alert_session_factory, alert_id=alert_id)) == 1
    assert (await _item(alert_session_factory, item_id))["assigned_moderator_id"] is None
    answer = await press_answer(alert_session_factory, update, outcome)
    assert answer.text == answer_text(PressOutcome.RECORDED_NOT_TEAM)


async def test_a_second_take_is_recorded_and_the_first_taker_keeps_it(
    alert_session_factory, question_alert, press, moderator: Moderator, insert_moderator,
    source_chat: Chat,
) -> None:
    item_id, alert_id, message_id = question_alert
    second: Moderator = await insert_moderator(display_name="Huda", team_chat=source_chat)
    first_press = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                              tg_user_id=moderator.tg_user_id)
    assert await derive_alert_press(alert_session_factory, first_press) is PressOutcome.RECORDED
    second_press = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                               tg_user_id=second.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, second_press)

    assert outcome is PressOutcome.ALREADY_TAKEN
    assert len(await _acts(alert_session_factory, alert_id=alert_id)) == 2
    assert (await _item(alert_session_factory, item_id))["assigned_moderator_id"] == (
        moderator.moderator_id
    )
    answer = await press_answer(alert_session_factory, second_press, outcome)
    assert answer.text == "سُجّل. يتولّاه Sara"
    # Re-running either press gives its own outcome again (B6).
    assert await derive_alert_press(alert_session_factory, first_press) is PressOutcome.RECORDED
    assert await derive_alert_press(alert_session_factory, second_press) is (
        PressOutcome.ALREADY_TAKEN
    )


async def test_a_take_after_the_answer_records_nothing(
    alert_session_factory, question_alert, press, end_item, moderator: Moderator,
) -> None:
    item_id, alert_id, message_id = question_alert
    await end_item(item_id, "answered_member")
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                         tg_user_id=moderator.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.ALREADY_ENDED
    assert await _acts(alert_session_factory, alert_id=alert_id) == []
    answer = await press_answer(alert_session_factory, update, outcome)
    assert answer.text == "انتهى هذا البند: أُجيب عنه"


async def test_a_take_by_an_inactive_moderator_records_nothing(
    alert_session_factory, question_alert, press, insert_moderator, source_chat: Chat,
) -> None:
    item_id, alert_id, message_id = question_alert
    former: Moderator = await insert_moderator(
        display_name="Former", team_chat=source_chat, is_active=False
    )
    update = await press(message_id=message_id, data=_data(alert_id, PressAction.TAKE),
                         tg_user_id=former.tg_user_id)

    outcome = await derive_alert_press(alert_session_factory, update)

    assert outcome is PressOutcome.NOT_A_MODERATOR
    assert await _acts(alert_session_factory, alert_id=alert_id) == []
    assert (await _item(alert_session_factory, item_id))["assigned_moderator_id"] is None


async def test_handled_and_not_a_violation_are_invalid_on_a_question(
    alert_session_factory, question_alert, press, moderator: Moderator,
) -> None:
    _item_id, alert_id, message_id = question_alert
    for action in (PressAction.HANDLED, PressAction.FALSE_POSITIVE):
        update = await press(message_id=message_id, data=_data(alert_id, action),
                             tg_user_id=moderator.tg_user_id)
        assert await derive_alert_press(alert_session_factory, update) is PressOutcome.INVALID


async def test_the_taken_alert_names_the_taker_and_keeps_its_keyboard(
    alert_session_factory, make_rule, insert_item, insert_alert, press, moderator: Moderator,
    scripted_telegram: ScriptedTelegram, destination_chat: Chat, source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=600,
        repeat_every_s=600, max_repeats=2,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    alert_id = await insert_alert(
        rule_id=rule_id, chat=source_chat, subject_type="attention_item", subject_id=item_id,
        trigger="question_waiting", rule_values={"max_repeats": 2},
    )
    assert (
        await deliver(alert_session_factory, scripted_telegram.client, alert_id, SETTINGS)
        is DeliveryOutcome.SENT
    )
    [sent] = scripted_telegram.calls_to("sendMessage")
    posted = await _one(
        alert_session_factory, "SELECT sent_message_id FROM alerts WHERE id = :id", id=alert_id
    )
    update = await press(message_id=posted["sent_message_id"],
                         data=_data(alert_id, PressAction.TAKE), tg_user_id=moderator.tg_user_id)
    outcome = await derive_alert_press(alert_session_factory, update)

    await answer_alert_press_once(
        alert_session_factory, scripted_telegram.client, SETTINGS, update, outcome
    )

    [edit] = scripted_telegram.calls_to("editMessageText")
    assert edit["chat_id"] == destination_chat.chat_id
    assert "🙋 يتولّاه Sara" in edit["text"]
    assert "من التنبيه" in edit["text"]
    [[take_button]] = edit["reply_markup"]["inline_keyboard"]
    assert take_button["callback_data"] == _data(alert_id, PressAction.TAKE)
    assert "🙋 يتولّاه" not in sent["text"]  # the team line before, the taker after

    # The next repeat's responsible line names the taker.
    repeat_id = await insert_alert(
        rule_id=rule_id, chat=source_chat, subject_type="attention_item", subject_id=item_id,
        trigger="question_waiting", repeat_index=1, rule_values={"max_repeats": 2},
    )
    assert (
        await deliver(alert_session_factory, scripted_telegram.client, repeat_id, SETTINGS)
        is DeliveryOutcome.SENT
    )
    repeat = scripted_telegram.calls_to("sendMessage")[-1]
    assert "تذكير 1 من 2" in repeat["text"]
    assert (
        f'المسؤول: <a href="tg://user?id={moderator.tg_user_id}">Sara</a> · من التنبيه'
        in repeat["text"]
    )

