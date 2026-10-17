"""Revision `0009` (`docs/plan/side/panel-users-and-sorting-plan.md` §4): `moderators.user_id` and
`uq_moderators_user_id`.

Modelled on `tests/moderation/attention_judgement/test_migration_0008.py`, against `injaz_ai_test`
only (Principle II):
- **The lifecycle:** each starts from, and ends at, an empty schema. The downgrade must drop
  exactly what the upgrade added — the schema at `0008` before the upgrade and after the downgrade
  are compared object by object.
- **The planted violation:** one transaction on a schema at head, a minimal baseline seeded in SQL,
  one invalid write, the constraint psycopg names, then a rollback.
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
BASELINE_REVISION = "0008"
HEAD_REVISION = "0009"

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
_VIEWS = ("moderation_incident_evidence", "moderation_incident_state")


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


def _column_nullable(test_url: str, table: str, column: str) -> str | None:
    nullable: str | None = _scalar(
        test_url,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c",
        {"t": table, "c": column},
    )
    return nullable


def _constraint_definition(test_url: str, table: str, name: str) -> str | None:
    definition: str | None = _scalar(
        test_url,
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :n",
        {"t": table, "n": name},
    )
    return definition


def _schema_fingerprint(test_url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every table, column, constraint and index in `public`, each with its definition — the
    schema compared before the upgrade and after the downgrade."""
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
def test_empty_to_0009(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    assert _column_nullable(test_url, "moderators", "user_id") == "YES"
    assert _constraint_definition(test_url, "moderators", "uq_moderators_user_id") == (
        "UNIQUE (user_id)"
    )


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
    assert _column_nullable(test_url, "moderators", "user_id") is None

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


# --- The planted violation ----------------------------------------------------------------------


@pytest.fixture
def conn(test_url: str) -> Iterator[Connection]:
    """One transaction on a schema at head, always rolled back."""
    if _constraint_definition(test_url, "moderators", "uq_moderators_user_id") is None:
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


def _moderator(conn: Connection, user_id: int | None) -> int:
    telegram_user_id = conn.execute(
        text("INSERT INTO telegram_users (tg_user_id) VALUES (:tg) RETURNING id"),
        {"tg": random.randint(10**12, 10**13)},
    ).scalar_one()
    moderator_id: int = conn.execute(
        text(
            "INSERT INTO moderators (telegram_user_id, display_name, user_id) "
            "VALUES (:tu, 'Moderator', :u) RETURNING id"
        ),
        {"tu": telegram_user_id, "u": user_id},
    ).scalar_one()
    return moderator_id


def test_moderators_without_a_panel_account_never_collide(conn: Connection) -> None:
    _moderator(conn, None)
    _moderator(conn, None)


def test_one_panel_account_maps_to_at_most_one_moderator(conn: Connection) -> None:
    user_id = random.randint(10**9, 10**10)
    _moderator(conn, user_id)

    with pytest.raises(IntegrityError) as exc:
        _moderator(conn, user_id)

    assert exc.value.orig is not None
    assert exc.value.orig.diag.constraint_name == "uq_moderators_user_id"
