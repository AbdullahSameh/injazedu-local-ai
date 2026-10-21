"""Revision `0011` (`specs/012-tg-m2-1-group-teams/data-model.md` §1-§5).

The index swap, `attention_items.closed_by_moderator_id` and three views. Modelled on
`test_migration_0009.py`, against `injaz_ai_test` only (Principle II):
- **The lifecycle:** each test starts from, and ends at, an empty schema. The downgrade drops
  exactly what the upgrade added, and it refuses while a group has two current members.
- **The planted violation:** one transaction on a schema at head, with a minimal baseline seeded
  in SQL and one invalid write. The test checks the constraint psycopg names, then rolls back.
"""

from __future__ import annotations

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
BASELINE_REVISION = "0010"
HEAD_REVISION = "0011"

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


def _index_definition(test_url: str, name: str) -> str | None:
    definition: str | None = _scalar(
        test_url, "SELECT indexdef FROM pg_indexes WHERE indexname = :n", {"n": name}
    )
    return definition


def _view_exists(test_url: str, name: str) -> bool:
    return _scalar(test_url, "SELECT to_regclass(:n)", {"n": name}) is not None


def _schema_fingerprint(test_url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every column, constraint, index and view in `public`, each with its definition — the schema
    compared before the upgrade and after the downgrade."""
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
            views = conn.execute(
                text(
                    "SELECT viewname, definition FROM pg_views WHERE schemaname = 'public'"
                )
            ).all()
    finally:
        engine.dispose()
    return {
        "columns": frozenset(tuple(str(v) for v in row) for row in columns),
        "constraints": frozenset(tuple(str(v) for v in row) for row in constraints),
        "indexes": frozenset(tuple(str(v) for v in row) for row in indexes),
        "views": frozenset(tuple(str(v) for v in row) for row in views),
    }


# --- The lifecycle ------------------------------------------------------------------------------


@pytest.mark.usefixtures("empty_schema")
def test_empty_to_0011(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    assert _index_definition(test_url, "uq_assignment_one_current_primary") is None
    membership = _index_definition(test_url, "uq_assignment_one_current_membership")
    assert membership is not None
    assert "(telegram_chat_id, moderator_id)" in membership
    assert "WHERE (valid_to IS NULL)" in membership
    for view in (
        "moderation_team_intervals",
        "attention_item_assignee",
        "moderation_incident_assignee",
    ):
        assert _view_exists(test_url, view), view


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
def test_the_downgrade_refuses_while_a_group_has_two_current_members(test_url: str) -> None:
    """data-model §1: restoring "one current primary" over a team would have to discard an
    ownership fact. It fails loudly instead."""
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, HEAD_REVISION)
    engine = create_engine(test_url)
    try:
        with engine.begin() as conn:
            chat_id = _chat(conn)
            for _ in range(2):
                _membership(conn, chat_id, _moderator(conn))
    finally:
        engine.dispose()

    with pytest.raises(IntegrityError):
        command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


# --- The planted violation ----------------------------------------------------------------------


@pytest.fixture
def conn(test_url: str) -> Iterator[Connection]:
    """One transaction on a schema at head, always rolled back."""
    if _index_definition(test_url, "uq_assignment_one_current_membership") is None:
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


def _chat(conn: Connection) -> int:
    chat_id: int = conn.execute(
        text(
            "INSERT INTO telegram_chats (chat_id, chat_type) VALUES (:c, 'supergroup') RETURNING id"
        ),
        {"c": -random.randint(10**12, 10**13)},
    ).scalar_one()
    return chat_id


def _moderator(conn: Connection) -> int:
    telegram_user_id = conn.execute(
        text("INSERT INTO telegram_users (tg_user_id) VALUES (:tg) RETURNING id"),
        {"tg": random.randint(10**12, 10**13)},
    ).scalar_one()
    moderator_id: int = conn.execute(
        text(
            "INSERT INTO moderators (telegram_user_id, display_name) "
            "VALUES (:tu, 'Moderator') RETURNING id"
        ),
        {"tu": telegram_user_id},
    ).scalar_one()
    return moderator_id


def _membership(conn: Connection, chat_id: int, moderator_id: int, role: str = "primary") -> None:
    conn.execute(
        text(
            "INSERT INTO moderator_group_assignments "
            "(telegram_chat_id, moderator_id, assignment_role, valid_from) "
            "VALUES (:c, :m, :r, now())"
        ),
        {"c": chat_id, "m": moderator_id, "r": role},
    )


def test_two_moderators_may_be_current_members_of_one_group(conn: Connection) -> None:
    chat_id = _chat(conn)
    first, second = _moderator(conn), _moderator(conn)
    _membership(conn, chat_id, first)
    _membership(conn, chat_id, second)

    team = conn.execute(
        text(
            "SELECT moderator_id FROM moderation_team_intervals "
            "WHERE telegram_chat_id = :c ORDER BY moderator_id"
        ),
        {"c": chat_id},
    ).scalars().all()
    assert team == sorted([first, second])


def test_one_moderator_is_current_in_one_group_at_most_once(conn: Connection) -> None:
    chat_id = _chat(conn)
    moderator_id = _moderator(conn)
    _membership(conn, chat_id, moderator_id)

    with pytest.raises(IntegrityError) as exc:
        _membership(conn, chat_id, moderator_id, role="backup")

    assert exc.value.orig is not None
    assert exc.value.orig.diag.constraint_name == "uq_assignment_one_current_membership"
