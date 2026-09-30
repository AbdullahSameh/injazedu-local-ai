"""Migration lifecycle for revision 0007 — message_classifications,
message_classification_attempts, moderation_incidents' new column and links, attention_items'
deferred FK, and model_profiles' widened role check (Principle I: migrations that transform
schema; data-model.md §1-§5).

Runs against `injaz_ai_test` only. TEST_DATABASE_URL already carries the ai_migrator identity.
Column types are not asserted here — exempt under `plan.md`'s Constitution Check.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

APP_DIR = Path(__file__).resolve().parents[3]
BASELINE_REVISION = "0006"
HEAD_REVISION = "0007"

_NEW_TABLES = ("message_classifications", "message_classification_attempts")
_PRIOR_TABLES = (
    "telegram_updates",
    "ingestion_state",
    "ingestion_gaps",
    "telegram_chats",
    "telegram_users",
    "moderators",
    "telegram_messages",
    "moderator_group_assignments",
    "attention_items",
    "model_runs",
    "model_profiles",
    "users",
    "moderation_incidents",
    "moderation_actions",
)
_PRIOR_VIEWS = ("moderation_incident_evidence", "moderation_incident_state")
_NEW_INDEXES = (
    "uq_classification_current",
    "ix_classifications_possible",
    "ix_classifications_profile",
    "uq_attempt_exclusion",
    "ix_attempts_message",
)
_NEW_COLUMN = "prompted_by_classification_id"
_NEW_CONSTRAINTS = (
    ("moderation_incidents", "fk_incident_classification"),
    ("moderation_incidents", "fk_incident_prompted_by"),
    ("moderation_incidents", "ck_incident_ai_link"),
    ("moderation_incidents", "ck_incident_prompted_by"),
    ("attention_items", "fk_attention_classification"),
)


def _alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return cfg


def _current_revision(sqlalchemy_url: str) -> str | None:
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            table_exists = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar_one()
            if table_exists is None:
                return None
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        engine.dispose()


@pytest.fixture
def test_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture(autouse=True)
def _empty_schema(test_url: str) -> Iterator[None]:
    """Every test in this file starts from, and ends at, an empty schema."""

    def _drop_all() -> None:
        engine = create_engine(test_url)
        try:
            with engine.begin() as conn:
                for view in _PRIOR_VIEWS:
                    conn.execute(text(f"DROP VIEW IF EXISTS {view} CASCADE"))
                for table in (*_NEW_TABLES, *_PRIOR_TABLES):
                    conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            engine.dispose()

    _drop_all()
    yield
    _drop_all()


def _relation_exists(test_url: str, name: str) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(f"SELECT to_regclass('{name}')")).scalar_one() is not None
    finally:
        engine.dispose()


def _index_exists(test_url: str, name: str) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = :name"), {"name": name}
            ).first()
            return row is not None
    finally:
        engine.dispose()


def _column_exists(test_url: str, table: str, column: str) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = :column"
                ),
                {"table": table, "column": column},
            ).first()
            return row is not None
    finally:
        engine.dispose()


def _constraint_exists(test_url: str, table: str, name: str) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "WHERE t.relname = :table AND c.conname = :name"
                ),
                {"table": table, "name": name},
            ).first()
            return row is not None
    finally:
        engine.dispose()


def _role_check_definition(test_url: str) -> str:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                     "WHERE conname = 'ck_model_profiles_role'")
            ).scalar_one()
    finally:
        engine.dispose()


def test_empty_to_0007(test_url: str) -> None:
    assert _current_revision(test_url) is None

    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    for table in _NEW_TABLES:
        assert _relation_exists(test_url, table), (
            f"{table} missing after upgrade to {HEAD_REVISION}"
        )
    assert _column_exists(test_url, "moderation_incidents", _NEW_COLUMN)
    for table, name in _NEW_CONSTRAINTS:
        assert _constraint_exists(test_url, table, name), f"{name} missing on {table}"
    assert "moderation" in _role_check_definition(test_url)


def test_new_indexes_exist(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    for index_name in _NEW_INDEXES:
        assert _index_exists(test_url, index_name), f"{index_name} missing after upgrade"


def test_head_down_to_0006_up_returns_to_the_identical_version_with_no_manual_repair(
    test_url: str,
) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, HEAD_REVISION)
    head_revision = _current_revision(test_url)
    assert head_revision == HEAD_REVISION

    command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == BASELINE_REVISION

    for table in _NEW_TABLES:
        assert not _relation_exists(
            test_url, table
        ), f"{table} still present after downgrade to {BASELINE_REVISION}"
    assert not _column_exists(test_url, "moderation_incidents", _NEW_COLUMN)
    for table, name in _NEW_CONSTRAINTS:
        assert not _constraint_exists(
            test_url, table, name
        ), f"{name} still present on {table} after downgrade to {BASELINE_REVISION}"
    assert "moderation" not in _role_check_definition(test_url)

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == head_revision
