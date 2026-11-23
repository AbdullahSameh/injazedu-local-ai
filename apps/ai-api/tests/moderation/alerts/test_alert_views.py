"""The two views revision `0013` replaces in place (data-model §5, D-TG-218), and its downgrade.

- `moderation_incident_state`: an `alert_false_positive` closes like `panel_false_positive`, with
  `close_kind` and `closed_by_moderator_id` appended; an `alert_handled` resolves as a confirmation.
  0012's 18 columns keep their names and order.
- `attention_item_assignee`: an `alert_take` by a team member assigns via `'alert'`, under the same
  live bound, team check and tie order as the other three acts.
- The downgrade refuses while an alert act exists, and otherwise returns the schema to exactly what
  0012 left, then upgrades back.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.infrastructure.models_moderation import moderation_actions
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_APP_DIR = Path(__file__).resolve().parents[3]

# 0012's columns of `moderation_incident_state`, in order (0006's definition).
_STATE_COLUMNS_0012 = [
    "incident_id",
    "status",
    "first_acknowledgement_at",
    "acknowledgement_kind",
    "acknowledged_by_moderator_id",
    "acknowledged_by_user_id",
    "first_enforcement_at",
    "first_confirmation_at",
    "resolved_at",
    "resolution_kind",
    "resolution_strength",
    "resolved_by_moderator_id",
    "resolved_by_telegram_user_id",
    "resolved_by_anonymous",
    "resolved_by_user_id",
    "closed_at",
    "closed_by_user_id",
    "close_reason",
]


async def _state(
    session_factory: async_sessionmaker[AsyncSession], incident_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.text("SELECT * FROM moderation_incident_state WHERE incident_id = :id"),
                {"id": incident_id},
            )
        ).mappings().one()
    return dict(row)


async def _assignee(
    session_factory: async_sessionmaker[AsyncSession], item_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.text("SELECT * FROM attention_item_assignee WHERE attention_item_id = :id"),
                {"id": item_id},
            )
        ).mappings().one()
    return dict(row)


# --- moderation_incident_state ---


async def test_an_alert_false_positive_closes_the_incident(
    alert_session_factory, db_now, source_chat, moderator, make_rule, insert_incident,
    insert_alert, insert_act,
) -> None:
    now = await db_now()
    incident = await insert_incident(source_chat, detected_at=now - timedelta(minutes=30))
    rule = await make_rule(trigger="incident_flagged")
    alert = await insert_alert(
        rule_id=rule, chat=source_chat, subject_type="incident", subject_id=incident,
        trigger="incident_flagged",
    )
    pressed_at = now - timedelta(minutes=5)

    await insert_act(
        source_chat, action_type="alert_false_positive", occurred_at=pressed_at,
        actor=moderator, alert_id=alert, incident_id=incident,
    )

    state = await _state(alert_session_factory, incident)
    assert state["status"] == "closed_false_positive"
    assert state["closed_at"] == pressed_at
    assert state["close_kind"] == "alert_false_positive"
    assert state["closed_by_moderator_id"] == moderator.moderator_id
    assert state["closed_by_user_id"] is None
    assert state["close_reason"] is None


async def test_a_panel_false_positive_still_closes_with_its_kind(
    alert_session_factory, db_now, source_chat, insert_incident, insert_act,
) -> None:
    now = await db_now()
    incident = await insert_incident(source_chat, detected_at=now - timedelta(minutes=30))

    await insert_act(
        source_chat, action_type="panel_false_positive", occurred_at=now - timedelta(minutes=5),
        incident_id=incident, panel_user_id=7, note="a student's own course link",
    )

    state = await _state(alert_session_factory, incident)
    assert state["status"] == "closed_false_positive"
    assert state["close_kind"] == "panel_false_positive"
    assert state["closed_by_user_id"] == 7
    assert state["closed_by_moderator_id"] is None
    assert state["close_reason"] == "a student's own course link"


async def test_an_alert_handled_resolves_as_a_confirmation(
    alert_session_factory, db_now, source_chat, moderator, make_rule, insert_incident,
    insert_alert, insert_act,
) -> None:
    now = await db_now()
    incident = await insert_incident(source_chat, detected_at=now - timedelta(minutes=30))
    rule = await make_rule(trigger="incident_flagged")
    alert = await insert_alert(
        rule_id=rule, chat=source_chat, subject_type="incident", subject_id=incident,
        trigger="incident_flagged",
    )
    pressed_at = now - timedelta(minutes=5)

    await insert_act(
        source_chat, action_type="alert_handled", action_strength="confirmation",
        occurred_at=pressed_at, actor=moderator, alert_id=alert, incident_id=incident,
    )

    state = await _state(alert_session_factory, incident)
    assert state["status"] == "resolved"
    assert state["resolution_kind"] == "alert_handled"
    assert state["resolution_strength"] == "confirmation"
    assert state["first_confirmation_at"] == pressed_at
    assert state["resolved_at"] == pressed_at
    assert state["resolved_by_moderator_id"] == moderator.moderator_id
    assert state["close_kind"] is None


async def test_the_state_view_keeps_0012s_columns_in_order(alert_session_factory) -> None:
    async with alert_session_factory() as session:
        columns = (
            await session.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'moderation_incident_state' ORDER BY ordinal_position"
                )
            )
        ).scalars().all()

    assert list(columns) == [*_STATE_COLUMNS_0012, "close_kind", "closed_by_moderator_id"]


# --- attention_item_assignee: the take branch ---


async def _take(
    insert_alert, insert_act, *, rule: int, chat, item: int, actor, at, k: int = 0
) -> int:
    alert = await insert_alert(
        rule_id=rule, chat=chat, subject_type="attention_item", subject_id=item,
        trigger="question_waiting", repeat_index=k,
    )
    return int(
        await insert_act(
            chat, action_type="alert_take", occurred_at=at, actor=actor, alert_id=alert
        )
    )


async def test_a_team_members_take_assigns_via_alert(
    alert_session_factory, db_now, source_chat, moderator, make_rule, insert_item, insert_alert,
    insert_act,
) -> None:
    now = await db_now()
    item = await insert_item(source_chat, opened_at=now - timedelta(minutes=20))
    rule = await make_rule(trigger="question_waiting", threshold_s=600)
    taken_at = now - timedelta(minutes=5)

    await _take(insert_alert, insert_act, rule=rule, chat=source_chat, item=item,
                actor=moderator, at=taken_at)

    assignee = await _assignee(alert_session_factory, item)
    assert assignee["assigned_moderator_id"] == moderator.moderator_id
    assert assignee["assigned_via"] == "alert"
    assert assignee["assigned_at"] == taken_at


async def test_a_non_team_take_assigns_nobody(
    alert_session_factory, db_now, source_chat, insert_moderator, make_rule, insert_item,
    insert_alert, insert_act,
) -> None:
    now = await db_now()
    outsider = await insert_moderator(display_name="Outsider")  # on no team
    item = await insert_item(source_chat, opened_at=now - timedelta(minutes=20))
    rule = await make_rule(trigger="question_waiting", threshold_s=600)

    await _take(insert_alert, insert_act, rule=rule, chat=source_chat, item=item,
                actor=outsider, at=now - timedelta(minutes=5))

    assert (await _assignee(alert_session_factory, item))["assigned_moderator_id"] is None


async def test_a_take_after_the_first_response_is_ignored(
    alert_session_factory, db_now, source_chat, moderator, make_rule, insert_item, insert_alert,
    insert_act, insert_message,
) -> None:
    now = await db_now()
    opened_at = now - timedelta(minutes=20)
    item = await insert_item(source_chat, opened_at=opened_at)
    answered_at = now - timedelta(minutes=10)
    answer = await insert_message(source_chat, sent_at=answered_at, text="Tomorrow")
    async with alert_session_factory() as session:
        # Answered by a member: no reply branch row, so only the take could assign.
        await session.execute(
            sa.text(
                "UPDATE attention_items SET status = 'answered', first_response_at = :at, "
                "first_response_message_id = :m, first_response_kind = 'group_message' "
                "WHERE id = :id"
            ),
            {"at": answered_at, "m": answer, "id": item},
        )
        await session.commit()
    rule = await make_rule(trigger="question_waiting", threshold_s=600)

    await _take(insert_alert, insert_act, rule=rule, chat=source_chat, item=item,
                actor=moderator, at=now - timedelta(minutes=5))

    assert (await _assignee(alert_session_factory, item))["assigned_moderator_id"] is None


async def test_on_a_tied_instant_a_reaction_wins_over_a_take(
    alert_session_factory, db_now, source_chat, moderator, insert_moderator, make_rule,
    insert_item, insert_alert, insert_act,
) -> None:
    now = await db_now()
    reactor = await insert_moderator(display_name="Reactor", team_chat=source_chat)
    item = await insert_item(source_chat, opened_at=now - timedelta(minutes=20))
    async with alert_session_factory() as session:
        anchor = (
            await session.execute(
                sa.text("SELECT telegram_message_id FROM attention_items WHERE id = :id"),
                {"id": item},
            )
        ).scalar_one()
    rule = await make_rule(trigger="question_waiting", threshold_s=600)
    tied = now - timedelta(minutes=5)

    await _take(insert_alert, insert_act, rule=rule, chat=source_chat, item=item,
                actor=moderator, at=tied)
    await insert_act(
        source_chat, action_type="reaction", action_strength="acknowledgement", occurred_at=tied,
        actor=reactor, target_message_id=anchor,
        detail={"added": [{"type": "emoji", "emoji": "👍"}]},
    )

    assignee = await _assignee(alert_session_factory, item)
    assert assignee["assigned_moderator_id"] == reactor.moderator_id
    assert assignee["assigned_via"] == "reaction"


async def test_an_earlier_take_wins_over_a_later_reaction(
    alert_session_factory, db_now, source_chat, moderator, insert_moderator, make_rule,
    insert_item, insert_alert, insert_act,
) -> None:
    now = await db_now()
    reactor = await insert_moderator(display_name="Reactor", team_chat=source_chat)
    item = await insert_item(source_chat, opened_at=now - timedelta(minutes=20))
    async with alert_session_factory() as session:
        anchor = (
            await session.execute(
                sa.text("SELECT telegram_message_id FROM attention_items WHERE id = :id"),
                {"id": item},
            )
        ).scalar_one()
    rule = await make_rule(trigger="question_waiting", threshold_s=600)

    await _take(insert_alert, insert_act, rule=rule, chat=source_chat, item=item,
                actor=moderator, at=now - timedelta(minutes=6))
    await insert_act(
        source_chat, action_type="reaction", action_strength="acknowledgement",
        occurred_at=now - timedelta(minutes=5), actor=reactor, target_message_id=anchor,
        detail={"added": [{"type": "emoji", "emoji": "👍"}]},
    )

    assignee = await _assignee(alert_session_factory, item)
    assert assignee["assigned_moderator_id"] == moderator.moderator_id
    assert assignee["assigned_via"] == "alert"


# --- the downgrade (data-model §6) ---


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _fingerprint(url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every column (views included), constraint, index and view definition in `public`. Not
    column positions: a dropped and re-added column takes a new attribute number."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            parts = {
                "columns": conn.execute(
                    text(
                        "SELECT table_name, column_name, data_type, is_nullable, "
                        "coalesce(column_default, '') "
                        "FROM information_schema.columns WHERE table_schema = 'public'"
                    )
                ).all(),
                "constraints": conn.execute(
                    text(
                        "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) "
                        "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = 'public'"
                    )
                ).all(),
                "indexes": conn.execute(
                    text(
                        "SELECT tablename, indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                ).all(),
                "views": conn.execute(
                    text(
                        "SELECT viewname, definition FROM pg_views WHERE schemaname = 'public'"
                    )
                ).all(),
            }
    finally:
        engine.dispose()
    return {k: frozenset(tuple(str(v) for v in row) for row in rows) for k, rows in parts.items()}


async def test_the_downgrade_refuses_while_an_alert_act_exists(
    db_now, source_chat, moderator, make_rule, insert_incident, insert_alert, insert_act,
) -> None:
    url = os.environ["TEST_DATABASE_URL"]
    now = await db_now()
    incident = await insert_incident(source_chat, detected_at=now - timedelta(minutes=30))
    rule = await make_rule(trigger="incident_flagged")
    alert = await insert_alert(
        rule_id=rule, chat=source_chat, subject_type="incident", subject_id=incident,
        trigger="incident_flagged",
    )
    await insert_act(
        source_chat, action_type="alert_false_positive", occurred_at=now - timedelta(minutes=5),
        actor=moderator, alert_id=alert, incident_id=incident,
    )

    with pytest.raises(Exception, match="cannot downgrade 0013"):
        command.downgrade(_alembic_config(url), "0012")

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0013"
    finally:
        engine.dispose()


async def test_the_downgrade_round_trips_without_alert_acts(
    alert_session_factory, alert_test_database_url: str,
) -> None:
    async with alert_session_factory() as session:
        # A crashed earlier run may have left alert acts; nothing else in the suite makes them.
        await session.execute(
            moderation_actions.delete().where(moderation_actions.c.alert_id.is_not(None))
        )
        await session.commit()
    cfg = _alembic_config(alert_test_database_url)
    at_head = _fingerprint(alert_test_database_url)

    command.downgrade(cfg, "0012")
    try:
        after = _fingerprint(alert_test_database_url)
        tables = {row[0] for row in after["columns"]}
        assert "alerts" not in tables and "alert_rules" not in tables
        engine = create_engine(alert_test_database_url)
        try:
            with engine.connect() as conn:
                state_columns = conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'moderation_incident_state' "
                        "ORDER BY ordinal_position"
                    )
                ).scalars().all()
        finally:
            engine.dispose()
        assert list(state_columns) == _STATE_COLUMNS_0012
        constraints = {row[1]: row[2] for row in after["constraints"]}
        assert "alert_" not in constraints["ck_actions_type"]
        assert "ck_actions_alert_link" not in constraints
    finally:
        command.upgrade(cfg, "head")

    assert _fingerprint(alert_test_database_url) == at_head
