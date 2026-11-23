"""Every CHECK and unique index of revision `0013`, planted (data-model §2-§4, `alerting.md` §11).

Each violation starts from a valid row, changes one thing, and asserts the constraint Postgres
names. Everything runs in one transaction per test, always rolled back, with a savepoint per
plant. The last test pins ORM parity: the CHECK texts in `models_moderation.py` are byte-identical
to the migration's (T503).
"""

from __future__ import annotations

import importlib.util
import random
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from app.infrastructure import models_moderation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0013_moderation_alerts.py"
)


@pytest_asyncio.fixture
async def session(
    alert_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with alert_session_factory() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()


async def _violation(session: AsyncSession, sql: str, params: dict[str, Any]) -> str | None:
    try:
        async with session.begin_nested():
            await session.execute(sa.text(sql), params)
    except IntegrityError as exc:
        return exc.orig.diag.constraint_name  # type: ignore[union-attr]
    return None


async def _scalar(session: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> Any:
    return (await session.execute(sa.text(sql), params or {})).scalar_one()


async def _chat(session: AsyncSession) -> int:
    return int(
        await _scalar(
            session,
            "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
            "VALUES (:c, 'supergroup', true) RETURNING id",
            {"c": -random.randint(10_000_000, 2_000_000_000)},
        )
    )


_RULE_SQL = (
    "INSERT INTO alert_rules (trigger, telegram_chat_id, threshold_s, min_severity, categories, "
    "openers, repeat_every_s, max_repeats, quiet_hours, is_enabled, enabled_at) VALUES "
    "(:trigger, :chat, :threshold_s, :min_severity, CAST(:categories AS jsonb), "
    "CAST(:openers AS jsonb), :repeat_every_s, :max_repeats, CAST(:quiet_hours AS jsonb), "
    ":is_enabled, :enabled_at)"
)


def _rule(chat: int, **overrides: Any) -> dict[str, Any]:
    """A valid chat-scoped `question_waiting` rule, unless overridden."""
    values: dict[str, Any] = {
        "trigger": "question_waiting",
        "chat": chat,
        "threshold_s": 600,
        "min_severity": None,
        "categories": None,
        "openers": None,
        "repeat_every_s": None,
        "max_repeats": None,
        "quiet_hours": "[]",
        "is_enabled": False,
        "enabled_at": None,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"trigger": "something_else", "threshold_s": None}, "ck_alert_rule_trigger"),
        ({"trigger": "incident_flagged", "threshold_s": 600}, "ck_alert_rule_threshold"),
        ({"trigger": "bot_not_admin", "threshold_s": 600}, "ck_alert_rule_threshold"),
        ({"trigger": "question_waiting", "threshold_s": None}, "ck_alert_rule_threshold"),
        ({"trigger": "incident_unhandled", "threshold_s": None}, "ck_alert_rule_threshold"),
        ({"trigger": "group_silent", "threshold_s": None}, "ck_alert_rule_threshold"),
        ({"threshold_s": 0}, "ck_alert_rule_threshold"),
        ({"trigger": "group_silent", "min_severity": "high"}, "ck_alert_rule_filters"),
        ({"trigger": "bot_not_admin", "threshold_s": None, "categories": '["ABUSE"]'},
         "ck_alert_rule_filters"),
        ({"trigger": "question_waiting", "openers": '["rule"]'}, "ck_alert_rule_filters"),
        ({"trigger": "incident_flagged", "threshold_s": None, "min_severity": "urgent"},
         "ck_alert_rule_severity"),
        ({"repeat_every_s": 600}, "ck_alert_rule_repeats"),
        ({"max_repeats": 3}, "ck_alert_rule_repeats"),
        ({"repeat_every_s": 0, "max_repeats": 3}, "ck_alert_rule_repeats"),
        ({"repeat_every_s": 600, "max_repeats": 0}, "ck_alert_rule_repeats"),
        ({"quiet_hours": '{"from": "22:00", "to": "07:00"}'}, "ck_alert_rule_quiet_hours"),
        ({"is_enabled": True, "enabled_at": None}, "ck_alert_rule_enabled_at"),
    ],
)
async def test_a_planted_rule_violation_names_its_constraint(
    session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    chat = await _chat(session)
    assert await _violation(session, _RULE_SQL, _rule(chat)) is None  # the baseline is valid

    other_chat = await _chat(session)
    assert await _violation(session, _RULE_SQL, _rule(other_chat, **overrides)) == constraint


async def test_valid_rules_of_every_trigger_are_accepted(session: AsyncSession) -> None:
    chat = await _chat(session)
    for overrides in (
        {"trigger": "question_waiting", "repeat_every_s": 900, "max_repeats": 2,
         "quiet_hours": '[{"from": "22:00", "to": "07:00"}]'},
        {"trigger": "incident_flagged", "threshold_s": None, "min_severity": "medium",
         "categories": '["SPAM_OR_AD"]', "openers": '["rule", "operator"]'},
        {"trigger": "incident_unhandled", "threshold_s": 1800},
        {"trigger": "group_silent", "threshold_s": 86400, "is_enabled": True,
         "enabled_at": "2026-11-01T00:00:00+00:00"},
        {"trigger": "bot_not_admin", "threshold_s": None},
    ):
        assert await _violation(session, _RULE_SQL, _rule(chat, **overrides)) is None


async def test_one_global_rule_per_trigger(session: AsyncSession) -> None:
    # The first may itself collide with a global rule another test left; either way the second
    # global row for the trigger is refused.
    await _violation(session, _RULE_SQL, _rule(None, trigger="bot_not_admin", threshold_s=None))
    assert (
        await _violation(
            session, _RULE_SQL, _rule(None, trigger="bot_not_admin", threshold_s=None)
        )
        == "uq_alert_rule_global"
    )


async def test_one_rule_per_chat_and_trigger(session: AsyncSession) -> None:
    chat = await _chat(session)
    assert await _violation(session, _RULE_SQL, _rule(chat)) is None
    assert await _violation(session, _RULE_SQL, _rule(chat)) == "uq_alert_rule_chat"
    # A different trigger in the same chat is a different rule.
    assert (
        await _violation(session, _RULE_SQL, _rule(chat, trigger="group_silent")) is None
    )


# --- alerts ---

_ALERT_SQL = (
    "INSERT INTO alerts (alert_rule_id, trigger, telegram_chat_id, subject_type, subject_id, "
    "episode_at, repeat_index, dedupe_key, rule_values, qualified_at, delivery_status, "
    "not_sent_reason, sent_chat_id, sent_message_id) VALUES "
    "(:rule, 'question_waiting', :chat, :subject_type, 1, :episode_at, :repeat_index, :key, "
    "'{}'::jsonb, now(), :status, :reason, :sent_chat_id, :sent_message_id)"
)


async def _rule_row(session: AsyncSession, chat: int) -> int:
    return int(await _scalar(session, _RULE_SQL + " RETURNING id", _rule(chat)))


def _alert(rule: int, chat: int, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "rule": rule,
        "chat": chat,
        "subject_type": "attention_item",
        "episode_at": None,
        "repeat_index": 0,
        "key": f"test:{random.randint(1, 2_000_000_000)}",
        "status": "pending",
        "reason": None,
        "sent_chat_id": None,
        "sent_message_id": None,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"subject_type": "user"}, "ck_alerts_subject_type"),
        ({"subject_type": "chat"}, "ck_alerts_episode"),
        ({"episode_at": "2026-11-01T00:00:00+00:00"}, "ck_alerts_episode"),
        ({"repeat_index": -1}, "ck_alerts_repeat"),
        ({"status": "delivered"}, "ck_alerts_status"),
        ({"status": "not_sent"}, "ck_alerts_not_sent"),
        ({"reason": "no_destination"}, "ck_alerts_not_sent"),
        ({"status": "sent"}, "ck_alerts_posted"),
        ({"status": "sent", "sent_chat_id": -100123}, "ck_alerts_posted"),
        ({"sent_chat_id": -100123, "sent_message_id": 7}, "ck_alerts_posted"),
    ],
)
async def test_a_planted_alert_violation_names_its_constraint(
    session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    chat = await _chat(session)
    rule = await _rule_row(session, chat)
    assert await _violation(session, _ALERT_SQL, _alert(rule, chat)) is None

    assert await _violation(session, _ALERT_SQL, _alert(rule, chat, **overrides)) == constraint


async def test_a_duplicate_dedupe_key_is_refused(session: AsyncSession) -> None:
    chat = await _chat(session)
    rule = await _rule_row(session, chat)
    key = f"dup:{random.randint(1, 2_000_000_000)}"
    assert await _violation(session, _ALERT_SQL, _alert(rule, chat, key=key)) is None

    assert (
        await _violation(session, _ALERT_SQL, _alert(rule, chat, key=key)) == "uq_alerts_dedupe"
    )


async def test_one_alert_per_posted_message(session: AsyncSession) -> None:
    chat = await _chat(session)
    rule = await _rule_row(session, chat)
    posted = {"status": "sent", "sent_chat_id": -100123, "sent_message_id": 42}
    assert await _violation(session, _ALERT_SQL, _alert(rule, chat, **posted)) is None

    assert (
        await _violation(session, _ALERT_SQL, _alert(rule, chat, **posted)) == "uq_alerts_posted"
    )


async def test_a_rule_that_has_alerts_cannot_be_deleted(session: AsyncSession) -> None:
    chat = await _chat(session)
    rule = await _rule_row(session, chat)
    assert await _violation(session, _ALERT_SQL, _alert(rule, chat)) is None

    assert (
        await _violation(session, "DELETE FROM alert_rules WHERE id = :id", {"id": rule})
        == "fk_alerts_rule"
    )


# --- moderation_actions ---

_ACT_SQL = (
    "INSERT INTO moderation_actions (telegram_chat_id, action_type, action_strength, occurred_at, "
    "actor_telegram_user_id, actor_moderator_id, panel_user_id, moderation_incident_id, "
    "source_update_id, alert_id, note) VALUES "
    "(:chat, :type, :strength, now(), :actor_tu, :actor_mod, :panel_user, :incident, :update, "
    ":alert, :note)"
)


async def _act_world(session: AsyncSession) -> dict[str, Any]:
    """A chat, a moderator, an incident, an alert on it, and a fresh captured update."""
    chat = await _chat(session)
    tu = await _scalar(
        session,
        "INSERT INTO telegram_users (tg_user_id) VALUES (:t) RETURNING id",
        {"t": random.randint(10_000_000, 2_000_000_000)},
    )
    mod = await _scalar(
        session,
        "INSERT INTO moderators (telegram_user_id, display_name) VALUES (:tu, 'M') RETURNING id",
        {"tu": tu},
    )
    message_id = random.randint(1, 2_000_000_000)
    update_for_message = await _scalar(
        session,
        "INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload) "
        "VALUES (1, :u, 'message', 1, '{}'::jsonb) RETURNING id",
        {"u": random.randint(10_000_000, 2_000_000_000)},
    )
    await session.execute(
        sa.text(
            "INSERT INTO telegram_messages (telegram_chat_id, message_id, sent_at, "
            "source_update_id) VALUES (:chat, :m, now() - interval '1 hour', :u)"
        ),
        {"chat": chat, "m": message_id, "u": update_for_message},
    )
    incident = await _scalar(
        session,
        "INSERT INTO moderation_incidents (telegram_chat_id, telegram_message_id, opened_at, "
        "detected_at, source, opened_by_user_id, category, severity) VALUES "
        "(:chat, :m, now() - interval '50 minutes', now() - interval '50 minutes', 'operator', "
        "1, 'SPAM_OR_AD', 'medium') RETURNING id",
        {"chat": chat, "m": message_id},
    )
    rule = await _rule_row(session, chat)
    alert = await _scalar(
        session,
        _ALERT_SQL.replace("'question_waiting'", "'incident_flagged'") + " RETURNING id",
        _alert(rule, chat, subject_type="incident"),
    )

    async def fresh_update() -> int:
        return int(
            await _scalar(
                session,
                "INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload) "
                "VALUES (1, :u, 'callback_query', 1, '{}'::jsonb) RETURNING id",
                {"u": random.randint(10_000_000, 2_000_000_000)},
            )
        )

    return {
        "chat": chat,
        "tu": tu,
        "mod": mod,
        "incident": incident,
        "alert": alert,
        "fresh_update": fresh_update,
    }


async def _act(world: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A valid `alert_handled` row, unless overridden."""
    values: dict[str, Any] = {
        "chat": world["chat"],
        "type": "alert_handled",
        "strength": "confirmation",
        "actor_tu": world["tu"],
        "actor_mod": world["mod"],
        "panel_user": None,
        "incident": world["incident"],
        "update": await world["fresh_update"](),
        "alert": world["alert"],
        "note": None,
    }
    values.update(overrides)
    return values


async def test_valid_alert_acts_of_each_kind_are_accepted(session: AsyncSession) -> None:
    world = await _act_world(session)
    assert await _violation(session, _ACT_SQL, await _act(world)) is None
    assert (
        await _violation(
            session,
            _ACT_SQL,
            await _act(world, type="alert_false_positive", strength=None),
        )
        is None
    )
    assert (
        await _violation(
            session, _ACT_SQL, await _act(world, type="alert_take", strength=None, incident=None)
        )
        is None
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"strength": "acknowledgement"}, "ck_actions_strength"),
        ({"type": "alert_false_positive", "strength": "confirmation"}, "ck_actions_strength"),
        ({"type": "alert_take", "strength": "acknowledgement", "incident": None},
         "ck_actions_strength"),
        ({"incident": None}, "ck_actions_panel_link"),
        ({"type": "alert_false_positive", "strength": None, "incident": None},
         "ck_actions_panel_link"),
        ({"type": "alert_take", "strength": None}, "ck_actions_panel_link"),
        ({"alert": None}, "ck_actions_alert_link"),
        ({"type": "alert_take", "strength": None, "incident": None, "alert": None},
         "ck_actions_alert_link"),
        ({"actor_mod": None}, "ck_actions_alert_actor"),
        ({"actor_tu": None}, "ck_actions_alert_actor"),
        ({"update": None}, "ck_actions_provenance"),
    ],
)
async def test_a_planted_alert_act_violation_names_its_constraint(
    session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    world = await _act_world(session)

    assert await _violation(session, _ACT_SQL, await _act(world, **overrides)) == constraint


async def test_a_panel_act_with_an_alert_is_refused(session: AsyncSession) -> None:
    world = await _act_world(session)

    assert (
        await _violation(
            session,
            _ACT_SQL,
            await _act(
                world,
                type="panel_resolve",
                actor_tu=None,
                actor_mod=None,
                panel_user=1,
                update=None,
                note="done",
            ),
        )
        == "ck_actions_alert_link"
    )


async def test_one_act_per_press(session: AsyncSession) -> None:
    world = await _act_world(session)
    update = await world["fresh_update"]()
    assert await _violation(session, _ACT_SQL, await _act(world, update=update)) is None

    assert (
        await _violation(session, _ACT_SQL, await _act(world, update=update))
        == "uq_moderation_actions_source_update"
    )


async def test_an_alert_with_a_button_act_cannot_be_deleted(session: AsyncSession) -> None:
    world = await _act_world(session)
    assert await _violation(session, _ACT_SQL, await _act(world)) is None

    assert (
        await _violation(session, "DELETE FROM alerts WHERE id = :id", {"id": world["alert"]})
        == "fk_actions_alert"
    )


# --- ORM parity (T503) ---


def _migration_module() -> Any:
    spec = importlib.util.spec_from_file_location("migration_0013", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_text(table: sa.Table, name: str) -> str:
    for constraint in table.constraints:
        if isinstance(constraint, sa.CheckConstraint) and constraint.name == name:
            return str(constraint.sqltext)
    raise AssertionError(f"{name} missing from {table.name}")


def test_the_orm_check_texts_equal_the_migrations() -> None:
    migration = _migration_module()
    actions = models_moderation.moderation_actions

    assert _check_text(actions, "ck_actions_type") == migration._NEW_TYPE
    assert _check_text(actions, "ck_actions_strength") == migration._NEW_STRENGTH
    assert _check_text(actions, "ck_actions_panel_link") == migration._NEW_PANEL_LINK
    assert _check_text(actions, "ck_actions_alert_link") == migration._ALERT_LINK
    assert _check_text(actions, "ck_actions_alert_actor") == migration._ALERT_ACTOR
    assert (
        _check_text(models_moderation.telegram_chats, "ck_chat_destination_not_monitored")
        == "NOT (is_alert_destination AND is_monitored)"
    )
    assert "alert_id" in actions.c
    assert "is_alert_destination" in models_moderation.telegram_chats.c
    assert [c.name for c in models_moderation.moderation_incident_state.c][-2:] == [
        "close_kind",
        "closed_by_moderator_id",
    ]
