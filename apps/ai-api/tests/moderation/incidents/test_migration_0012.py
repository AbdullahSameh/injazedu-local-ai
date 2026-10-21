"""Revision `0012` (`docs/plan/telegram/tg-eyes-reaction-resolution-plan.md` E1): a moderator's
👀 reaction is recorded as a confirmation.

- `ck_actions_strength` lets a `reaction` row carry `confirmation` as well as `acknowledgement`.
- `ck_actions_reaction_confirmation` refuses a confirming reaction without 👀 among its added
  reactions.

Modelled on `test_migration_0010.py`, against `injaz_ai_test` only (Principle II): the lifecycle
starts from, and ends at, an empty schema; the planted violations run in one rolled-back
transaction on a schema at head.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

APP_DIR = Path(__file__).resolve().parents[3]
BASELINE_REVISION = "0011"
HEAD_REVISION = "0012"

_TABLES = (
    "message_attention_attempts",
    "message_attention_judgements",
    "message_classification_attempts",
    "message_classifications",
    "moderation_actions",
    "moderation_incidents",
    "attention_items",
    "moderator_group_assignments",
    "telegram_messages",
    "moderators",
    "telegram_users",
    "telegram_chats",
    "ingestion_gaps",
    "ingestion_state",
    "telegram_updates",
    "model_runs",
    "model_profiles",
    "users",
)
_VIEWS = (
    "moderation_incident_assignee",
    "attention_item_assignee",
    "moderation_team_intervals",
    "moderation_incident_evidence",
    "moderation_incident_state",
)


def _alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return cfg


@pytest.fixture
def test_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _drop_all(test_url: str) -> None:
    engine = create_engine(test_url)
    try:
        with engine.begin() as conn:
            for view in _VIEWS:
                conn.execute(text(f"DROP VIEW IF EXISTS {view} CASCADE"))
            for table in _TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


@pytest.fixture
def empty_schema(test_url: str) -> Iterator[None]:
    """The lifecycle tests start from, and end at, an empty schema."""
    _drop_all(test_url)
    yield
    _drop_all(test_url)


def _scalar(test_url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()
    finally:
        engine.dispose()


def _current_revision(test_url: str) -> str | None:
    if _scalar(test_url, "SELECT to_regclass('alembic_version')") is None:
        return None
    revision: str | None = _scalar(test_url, "SELECT version_num FROM alembic_version")
    return revision


def _constraint_definition(test_url: str, table: str, name: str) -> str | None:
    definition: str | None = _scalar(
        test_url,
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :n",
        {"t": table, "n": name},
    )
    return definition


def _schema_fingerprint(test_url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every column, constraint and index in `public`, each with its definition."""
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, "
                    "coalesce(column_default, '') FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            ).all()
            constraints = conn.execute(
                text(
                    "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) "
                    "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'public'"
                )
            ).all()
            indexes = conn.execute(
                text(
                    "SELECT tablename, indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public'"
                )
            ).all()
    finally:
        engine.dispose()
    return {
        "columns": frozenset(tuple(str(v) for v in row) for row in columns),
        "constraints": frozenset(tuple(str(v) for v in row) for row in constraints),
        "indexes": frozenset(tuple(str(v) for v in row) for row in indexes),
    }


# --- The lifecycle ------------------------------------------------------------------------------


@pytest.mark.usefixtures("empty_schema")
def test_empty_to_0012(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    strength = _constraint_definition(test_url, "moderation_actions", "ck_actions_strength")
    assert strength is not None
    assert "'confirmation'" in strength.split("OR")[0]
    assert _constraint_definition(
        test_url, "moderation_actions", "ck_actions_reaction_confirmation"
    ) is not None


@pytest.mark.usefixtures("empty_schema")
def test_the_downgrade_drops_exactly_what_the_upgrade_added(test_url: str) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, BASELINE_REVISION)
    before = _schema_fingerprint(test_url)

    command.upgrade(cfg, HEAD_REVISION)
    assert _schema_fingerprint(test_url) != before

    command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == BASELINE_REVISION
    assert _schema_fingerprint(test_url) == before

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


@pytest.mark.usefixtures("empty_schema")
def test_the_downgrade_refuses_while_a_confirming_reaction_is_recorded(test_url: str) -> None:
    """A recorded act is never rewritten: restoring "a reaction only acknowledges" over a 👀
    confirmation would have to, so the downgrade fails loudly instead."""
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, HEAD_REVISION)
    engine = create_engine(test_url)
    try:
        with engine.begin() as connection:
            _reaction(connection, strength="confirmation", emoji="👀")
    finally:
        engine.dispose()

    with pytest.raises(Exception, match="cannot downgrade 0012"):
        command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


# --- The planted violation ----------------------------------------------------------------------


@pytest.fixture
def conn(test_url: str) -> Iterator[Connection]:
    """One transaction on a schema at head, always rolled back."""
    if (
        _constraint_definition(test_url, "moderation_actions", "ck_actions_reaction_confirmation")
        is None
    ):
        command.upgrade(_alembic_config(test_url), "head")
    engine = create_engine(test_url)
    connection = engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()
        engine.dispose()


def _reaction(connection: Connection, *, strength: str, emoji: str) -> None:
    """One moderator's reaction row in a fresh chat, with `emoji` as its only added reaction."""
    chat_pk = connection.execute(
        text(
            "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
            "VALUES (:chat_id, 'group', true) RETURNING id"
        ),
        {"chat_id": -random.randint(10_000_000, 2_000_000_000)},
    ).scalar_one()
    telegram_user_id = connection.execute(
        text("INSERT INTO telegram_users (tg_user_id) VALUES (:tg) RETURNING id"),
        {"tg": random.randint(10_000_000, 2_000_000_000)},
    ).scalar_one()
    moderator_id = connection.execute(
        text(
            "INSERT INTO moderators (telegram_user_id, display_name) "
            "VALUES (:tu, 'Moderator') RETURNING id"
        ),
        {"tu": telegram_user_id},
    ).scalar_one()
    update_pk = connection.execute(
        text(
            "INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload) "
            "VALUES (:bot_id, :update_id, 'message_reaction', :chat_id, '{}'::jsonb) "
            "RETURNING id"
        ),
        {
            "bot_id": random.randint(10_000_000, 2_000_000_000),
            "update_id": random.randint(10_000_000, 2_000_000_000),
            "chat_id": chat_pk,
        },
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO moderation_actions "
            "(telegram_chat_id, action_type, action_strength, occurred_at, "
            " actor_telegram_user_id, actor_moderator_id, target_message_id, source_update_id, "
            " detail) VALUES "
            "(:chat_pk, 'reaction', :strength, now(), :tu, :mod, 1, :update_pk, "
            " CAST(:detail AS jsonb))"
        ),
        {
            "chat_pk": chat_pk,
            "strength": strength,
            "tu": telegram_user_id,
            "mod": moderator_id,
            "update_pk": update_pk,
            "detail": json.dumps({"added": [{"type": "emoji", "emoji": emoji}]}),
        },
    )


def _violated(exc: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    assert exc.value.orig is not None
    name: str | None = exc.value.orig.diag.constraint_name
    return name


def test_a_moderators_eyes_may_be_a_confirmation(conn: Connection) -> None:
    _reaction(conn, strength="confirmation", emoji="👀")


def test_any_reaction_may_still_be_an_acknowledgement(conn: Connection) -> None:
    _reaction(conn, strength="acknowledgement", emoji="👀")
    _reaction(conn, strength="acknowledgement", emoji="👍")


def test_no_other_reaction_may_be_a_confirmation(conn: Connection) -> None:
    with pytest.raises(IntegrityError) as exc:
        _reaction(conn, strength="confirmation", emoji="👍")
    assert _violated(exc) == "ck_actions_reaction_confirmation"


def test_a_reaction_is_never_enforcement(conn: Connection) -> None:
    with pytest.raises(IntegrityError) as exc:
        _reaction(conn, strength="enforcement", emoji="👀")
    assert _violated(exc) == "ck_actions_strength"
