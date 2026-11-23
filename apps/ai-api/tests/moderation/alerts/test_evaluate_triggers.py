"""F1 per trigger, at the boundaries, under the rule in force (`contracts/alerting.md` §2 R5,
§3 F1).

US1 (T520): `question_waiting`. US2 adds the two incident triggers, US5 the two health triggers.

The database is shared, so a global rule also fires on other tests' leftover open items; those
alerts are purged with the rule at teardown, and every assertion reads this test's own subject.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from app.domain.moderation.alerting import SubjectType, dedupe_key
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.alerts.conftest import Chat

THRESHOLD = timedelta(minutes=10)


# --- question_waiting (US1) ---


async def test_one_second_short_of_the_threshold_fires_nothing(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )
    item_id = await insert_item(source_chat, opened_at=now - THRESHOLD + timedelta(seconds=1))

    await evaluate()

    assert await fetch_alerts("attention_item", item_id) == []


async def test_at_the_threshold_one_alert_fires(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )
    opened_at = now - THRESHOLD
    item_id = await insert_item(source_chat, opened_at=opened_at)

    result = await evaluate()

    [alert] = await fetch_alerts("attention_item", item_id)
    assert alert["id"] in result.to_deliver
    assert alert["alert_rule_id"] == rule_id
    assert alert["trigger"] == "question_waiting"
    assert alert["telegram_chat_id"] == source_chat.id  # the source group, never the destination
    assert alert["episode_at"] is None
    assert alert["repeat_index"] == 0
    assert alert["qualified_at"] == opened_at + THRESHOLD


@pytest.mark.parametrize("route", ["answered_moderator", "answered_member", "dismissed", "expired"])
async def test_an_item_that_ended_fires_nothing(
    make_rule, insert_item, end_item, evaluate, fetch_alerts, source_chat: Chat, db_now,
    route: str,
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    await end_item(item_id, route)

    await evaluate()

    assert await fetch_alerts("attention_item", item_id) == []


async def test_the_group_rule_beats_the_global_one(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, insert_chat, db_now
) -> None:
    now: datetime = await db_now()
    global_rule = await make_rule(trigger="question_waiting", threshold_s=60)
    group_rule = await make_rule(
        trigger="question_waiting", telegram_chat_id=source_chat.id, threshold_s=3600
    )
    other_chat = await insert_chat(title="Another group")
    here = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    there = await insert_item(other_chat, opened_at=now - timedelta(minutes=30))
    late = await insert_item(source_chat, opened_at=now - timedelta(hours=2))

    await evaluate()

    assert await fetch_alerts("attention_item", here) == []  # 30 min < the group's hour
    [elsewhere] = await fetch_alerts("attention_item", there)
    assert elsewhere["alert_rule_id"] == global_rule
    [own] = await fetch_alerts("attention_item", late)
    assert own["alert_rule_id"] == group_rule
    assert own["rule_values"]["threshold_s"] == 3600


async def test_a_disabled_group_rule_mutes_the_global_one_for_that_group(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, insert_chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(trigger="question_waiting", threshold_s=60)
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=60,
        is_enabled=False,
    )
    other_chat = await insert_chat(title="Another group")
    muted = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    heard = await insert_item(other_chat, opened_at=now - timedelta(hours=1))

    await evaluate()

    assert await fetch_alerts("attention_item", muted) == []
    assert len(await fetch_alerts("attention_item", heard)) == 1


async def test_a_disabled_global_rule_fires_nothing(
    make_rule, insert_item, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(trigger="question_waiting", threshold_s=60, is_enabled=False)
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))

    await evaluate()

    assert await fetch_alerts("attention_item", item_id) == []


async def test_an_unmonitored_group_fires_nothing(
    make_rule, insert_item, evaluate, fetch_alerts, insert_chat, db_now
) -> None:
    now: datetime = await db_now()
    unmonitored = await insert_chat(is_monitored=False)
    await make_rule(
        trigger="question_waiting", telegram_chat_id=unmonitored.id, threshold_s=60
    )
    item_id = await insert_item(unmonitored, opened_at=now - timedelta(hours=1))

    await evaluate()

    assert await fetch_alerts("attention_item", item_id) == []


# --- incident_flagged and incident_unhandled (US2, T527) ---


async def test_a_live_incident_is_flagged_at_its_detection(
    make_rule, insert_incident, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(trigger="incident_flagged", telegram_chat_id=source_chat.id)
    detected_at = now - timedelta(minutes=2)
    incident_id = await insert_incident(source_chat, detected_at=detected_at)

    result = await evaluate()

    [alert] = await fetch_alerts("incident", incident_id)
    assert alert["id"] in result.to_deliver
    assert alert["alert_rule_id"] == rule_id
    assert alert["trigger"] == "incident_flagged"
    assert alert["telegram_chat_id"] == source_chat.id
    assert alert["qualified_at"] == detected_at


@pytest.mark.parametrize(
    ("filters", "incident", "fires"),
    [
        ({"min_severity": "high"}, {"severity": "medium"}, False),
        ({"min_severity": "medium"}, {"severity": "medium"}, True),
        ({"min_severity": "low"}, {"severity": "high"}, True),
        ({"categories": ["ABUSE"]}, {"category": "SPAM_OR_AD"}, False),
        ({"categories": ["ABUSE", "SPAM_OR_AD"]}, {"category": "SPAM_OR_AD"}, True),
        ({"openers": ["rule", "operator"]}, {"source": "ai"}, False),  # a model-opened incident
        ({"openers": ["operator"]}, {"source": "operator"}, True),
        (
            {"min_severity": "medium", "categories": ["SPAM_OR_AD"], "openers": ["operator"]},
            {"severity": "high", "category": "SPAM_OR_AD", "source": "operator"},
            True,
        ),
        (
            {"min_severity": "medium", "categories": ["SPAM_OR_AD"], "openers": ["operator"]},
            {"severity": "low", "category": "SPAM_OR_AD", "source": "operator"},
            False,
        ),
    ],
)
@pytest.mark.parametrize("trigger", ["incident_flagged", "incident_unhandled"])
async def test_each_filter_lets_its_incidents_in_and_keeps_the_others_out(
    make_rule, insert_incident, insert_ai_incident, evaluate, fetch_alerts, source_chat: Chat,
    db_now, trigger: str, filters: dict[str, Any], incident: dict[str, Any], fires: bool,
) -> None:
    now: datetime = await db_now()
    threshold = {"threshold_s": 600} if trigger == "incident_unhandled" else {}
    await make_rule(trigger=trigger, telegram_chat_id=source_chat.id, **threshold, **filters)
    if incident.get("source") == "ai":
        incident_id = await insert_ai_incident(source_chat, detected_at=now - timedelta(hours=1))
    else:
        incident_id = await insert_incident(
            source_chat, detected_at=now - timedelta(hours=1), **incident
        )

    await evaluate()

    assert len(await fetch_alerts("incident", incident_id)) == (1 if fires else 0)


_TEST_PROFILE = "alerts-test-moderation"


@pytest_asyncio.fixture
async def insert_ai_incident(
    alert_session_factory: async_sessionmaker[AsyncSession], insert_incident
) -> AsyncIterator[Callable[..., Any]]:
    """A model-opened incident. `source = 'ai'` needs its prediction (`ck_incident_ai_link`), so
    the incident is opened as the operator's, then re-pointed at a prediction written for its
    anchor, as `classify_message` would have opened it. The prediction names an inactive profile
    of its own: nothing here may change which profile is active.

    At teardown each incident goes back to the operator's, and the predictions and the profile
    are removed: a leftover `moderation` profile blocks 0007's downgrade for every later
    migration test in the shared database."""
    opened: list[tuple[int, int]] = []  # (incident, prediction)

    async def _insert(chat: Chat, *, detected_at: datetime) -> int:
        incident_id: int = await insert_incident(chat, detected_at=detected_at)
        async with alert_session_factory() as session:
            profile_id = (
                await session.execute(
                    sa.text(
                        "INSERT INTO model_profiles "
                        "(name, provider, base_url, model, role, params, dim, is_active) "
                        "VALUES (:name, 'fake', NULL, 'fake-moderation', 'moderation', "
                        "        '{}'::jsonb, NULL, false) "
                        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                    ),
                    {"name": _TEST_PROFILE},
                )
            ).scalar_one()
            classification_id = (
                await session.execute(
                    sa.text(
                        "INSERT INTO message_classifications "
                        "(telegram_chat_id, telegram_message_id, model_profile_id, "
                        " prompt_version, taxonomy_version, category, needs_response, "
                        " needs_moderation, severity, confidence, path, route, "
                        " confidence_floor, incident_threshold) "
                        "SELECT telegram_chat_id, telegram_message_id, :profile, "
                        "       'classify_v2', 1, 'SPAM_OR_AD', false, true, 'medium', 0.950, "
                        "       'live', 'incident', 0.600, 0.850 "
                        "FROM moderation_incidents WHERE id = :id RETURNING id"
                    ),
                    {"profile": profile_id, "id": incident_id},
                )
            ).scalar_one()
            await session.execute(
                sa.text(
                    "UPDATE moderation_incidents SET source = 'ai', opened_by_user_id = NULL, "
                    "message_classification_id = :c WHERE id = :id"
                ),
                {"c": classification_id, "id": incident_id},
            )
            await session.commit()
        opened.append((incident_id, int(classification_id)))
        return incident_id

    try:
        yield _insert
    finally:
        async with alert_session_factory() as session:
            for incident_id, classification_id in opened:
                await session.execute(
                    sa.text(
                        "UPDATE moderation_incidents SET source = 'operator', "
                        "opened_by_user_id = 1, message_classification_id = NULL WHERE id = :id"
                    ),
                    {"id": incident_id},
                )
                await session.execute(
                    sa.text("DELETE FROM message_classifications WHERE id = :id"),
                    {"id": classification_id},
                )
            await session.execute(
                sa.text(
                    "DELETE FROM model_profiles p WHERE p.name = :name AND NOT EXISTS "
                    "(SELECT 1 FROM message_classifications c WHERE c.model_profile_id = p.id)"
                ),
                {"name": _TEST_PROFILE},
            )
            await session.commit()


@pytest.mark.parametrize("route", ["panel_resolve", "panel_false_positive", "ban", "eyes"])
@pytest.mark.parametrize("trigger", ["incident_flagged", "incident_unhandled"])
async def test_an_incident_that_ended_fires_nothing(
    make_rule, insert_incident, end_incident, evaluate, fetch_alerts, source_chat: Chat,
    moderator, db_now, trigger: str, route: str,
) -> None:
    now: datetime = await db_now()
    threshold = {"threshold_s": 600} if trigger == "incident_unhandled" else {}
    await make_rule(trigger=trigger, telegram_chat_id=source_chat.id, **threshold)
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(hours=1))
    await end_incident(incident_id, route, moderator=moderator)

    await evaluate()

    assert await fetch_alerts("incident", incident_id) == []


@pytest.mark.parametrize("trigger", ["incident_flagged", "incident_unhandled"])
async def test_an_acknowledged_incident_still_qualifies(
    make_rule, insert_incident, end_incident, evaluate, fetch_alerts, source_chat: Chat,
    db_now, trigger: str,
) -> None:
    now: datetime = await db_now()
    threshold = {"threshold_s": 600} if trigger == "incident_unhandled" else {}
    await make_rule(trigger=trigger, telegram_chat_id=source_chat.id, **threshold)
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(hours=1))
    await end_incident(incident_id, "acknowledged")

    await evaluate()

    assert len(await fetch_alerts("incident", incident_id)) == 1


async def test_unhandled_is_measured_from_detection_not_posting(
    make_rule, insert_incident, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await make_rule(
        trigger="incident_unhandled",
        telegram_chat_id=source_chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )
    # Posted two hours ago, flagged only now: not yet unhandled for ten minutes.
    late_flag = await insert_incident(
        source_chat,
        opened_at=now - timedelta(hours=2),
        detected_at=now - THRESHOLD + timedelta(seconds=1),
    )
    detected_at = now - THRESHOLD
    on_time = await insert_incident(
        source_chat, opened_at=now - timedelta(hours=2), detected_at=detected_at
    )

    await evaluate()

    assert await fetch_alerts("incident", late_flag) == []
    [alert] = await fetch_alerts("incident", on_time)
    assert alert["trigger"] == "incident_unhandled"
    assert alert["qualified_at"] == detected_at + THRESHOLD


async def test_both_incident_triggers_alert_once_each_over_two_runs(
    make_rule, insert_incident, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    """F6: at most one alert per subject per evaluation, so the second trigger's alert for the
    same incident comes on the next run."""
    now: datetime = await db_now()
    await make_rule(trigger="incident_flagged", telegram_chat_id=source_chat.id)
    await make_rule(trigger="incident_unhandled", telegram_chat_id=source_chat.id, threshold_s=600)
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(hours=1))

    await evaluate()
    first = [a["trigger"] for a in await fetch_alerts("incident", incident_id)]
    await evaluate()
    await evaluate()
    both = [a["trigger"] for a in await fetch_alerts("incident", incident_id)]

    assert first == ["incident_flagged"]
    assert both == ["incident_flagged", "incident_unhandled"]


async def test_an_incident_flagged_before_the_rule_was_enabled_fires_nothing(
    make_rule, insert_incident, evaluate, fetch_alerts, source_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    incident_id = await insert_incident(source_chat, detected_at=now - timedelta(hours=1))
    await make_rule(
        trigger="incident_flagged",
        telegram_chat_id=source_chat.id,
        enabled_at=now - timedelta(minutes=30),
    )

    await evaluate()

    assert await fetch_alerts("incident", incident_id) == []


# --- group_silent and bot_not_admin (US5, T545) ---


async def _set_chat(
    session_factory: async_sessionmaker[AsyncSession], chat: Chat, **values: Any
) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    async with session_factory() as session:
        await session.execute(
            sa.text(f"UPDATE telegram_chats SET {sets} WHERE id = :id"), {"id": chat.id, **values}
        )
        await session.commit()


async def test_a_group_one_second_short_of_silence_fires_nothing(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now
) -> None:
    now: datetime = await db_now()
    chat: Chat = await insert_chat(last_event_at=now - THRESHOLD + timedelta(seconds=1))
    await make_rule(
        trigger="group_silent",
        telegram_chat_id=chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )

    await evaluate()

    assert await fetch_alerts("chat", chat.id) == []


async def test_a_group_silent_for_the_threshold_alerts_once_for_its_episode(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now
) -> None:
    now: datetime = await db_now()
    last_event_at = now - THRESHOLD
    chat: Chat = await insert_chat(last_event_at=last_event_at)
    rule_id = await make_rule(
        trigger="group_silent",
        telegram_chat_id=chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )

    result = await evaluate()
    await evaluate()

    [alert] = await fetch_alerts("chat", chat.id)
    assert alert["id"] in result.to_deliver
    assert alert["alert_rule_id"] == rule_id
    assert alert["trigger"] == "group_silent"
    assert alert["telegram_chat_id"] == chat.id
    assert alert["episode_at"] == last_event_at
    assert alert["repeat_index"] == 0
    assert alert["qualified_at"] == last_event_at + THRESHOLD
    assert alert["dedupe_key"] == dedupe_key(rule_id, SubjectType.CHAT, chat.id, last_event_at, 0)


async def test_a_later_silence_is_a_new_episode_and_alerts_again(
    alert_session_factory, make_rule, insert_chat, evaluate, fetch_alerts, db_now
) -> None:
    now: datetime = await db_now()
    first_event = now - timedelta(hours=3)
    chat: Chat = await insert_chat(last_event_at=first_event)
    await make_rule(
        trigger="group_silent",
        telegram_chat_id=chat.id,
        threshold_s=int(THRESHOLD.total_seconds()),
    )
    await evaluate()

    # The group spoke again, then fell silent past the threshold once more.
    second_event = now - timedelta(hours=1)
    await _set_chat(alert_session_factory, chat, last_event_at=second_event)
    await evaluate()

    episodes = [(a["episode_at"], a["repeat_index"]) for a in await fetch_alerts("chat", chat.id)]
    assert episodes == [(first_event, 0), (second_event, 0)]


@pytest.mark.parametrize("standing", ["left", "kicked", "restricted", "member"])
async def test_a_standing_other_than_administrator_alerts(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now, standing: str
) -> None:
    now: datetime = await db_now()
    changed_at = now - timedelta(minutes=1)
    chat: Chat = await insert_chat(bot_status=standing, bot_status_at=changed_at)
    await make_rule(trigger="bot_not_admin", telegram_chat_id=chat.id)

    result = await evaluate()

    [alert] = await fetch_alerts("chat", chat.id)
    assert alert["id"] in result.to_deliver
    assert alert["trigger"] == "bot_not_admin"
    assert (alert["episode_at"], alert["qualified_at"]) == (changed_at, changed_at)


@pytest.mark.parametrize("standing", ["administrator", "unknown"])
async def test_administrator_or_unknown_never_alerts(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now, standing: str
) -> None:
    now: datetime = await db_now()
    chat: Chat = await insert_chat(bot_status=standing, bot_status_at=now - timedelta(minutes=1))
    await make_rule(trigger="bot_not_admin", telegram_chat_id=chat.id)

    await evaluate()

    assert await fetch_alerts("chat", chat.id) == []


async def test_a_standing_changed_before_the_rule_was_enabled_fires_nothing(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now
) -> None:
    now: datetime = await db_now()
    chat: Chat = await insert_chat(bot_status="left", bot_status_at=now - timedelta(hours=1))
    await make_rule(
        trigger="bot_not_admin", telegram_chat_id=chat.id, enabled_at=now - timedelta(minutes=30)
    )

    await evaluate()

    assert await fetch_alerts("chat", chat.id) == []


async def test_an_unmonitored_group_never_alerts(
    make_rule, insert_chat, evaluate, fetch_alerts, db_now
) -> None:
    now: datetime = await db_now()
    chat: Chat = await insert_chat(
        is_monitored=False,
        last_event_at=now - timedelta(days=2),
        bot_status="left",
        bot_status_at=now - timedelta(minutes=1),
    )
    await make_rule(trigger="group_silent", telegram_chat_id=chat.id, threshold_s=600)
    await make_rule(trigger="bot_not_admin", telegram_chat_id=chat.id)

    await evaluate()
    await evaluate()

    assert await fetch_alerts("chat", chat.id) == []


async def test_the_alert_group_itself_never_alerts_even_under_global_rules(
    alert_session_factory, make_rule, evaluate, fetch_alerts, destination_chat: Chat, db_now
) -> None:
    now: datetime = await db_now()
    await _set_chat(
        alert_session_factory,
        destination_chat,
        last_event_at=now - timedelta(days=2),
        bot_status_at=now - timedelta(minutes=1),
    )  # silent, and the bot a plain member there
    await make_rule(trigger="group_silent", threshold_s=600)
    await make_rule(trigger="bot_not_admin")

    await evaluate()
    await evaluate()

    assert await fetch_alerts("chat", destination_chat.id) == []
