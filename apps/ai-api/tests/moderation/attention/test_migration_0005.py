"""Migration lifecycle for revision 0005 — attention_items, telegram_messages' two new columns
(Principle I: migrations that transform schema; data-model.md §1-§2).

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
BASELINE_REVISION = "0004"
HEAD_REVISION = "0005"

_NEW_TABLES = ("attention_items",)
_PRIOR_TABLES = (
    "telegram_updates",
    "ingestion_state",
    "ingestion_gaps",
    "telegram_chats",
    "telegram_users",
    "moderators",
    "telegram_messages",
    "moderator_group_assignments",
    "model_runs",
    "model_profiles",
    "users",
)
_NEW_COLUMNS = ("attention_item_id", "attention_evaluated_at")
_NEW_INDEXES = (
    "ix_attention_open",
    "ix_attention_chat_thread_open",
    "ix_attention_chat",
    "ix_attention_moderator",
    "ix_messages_unjudged",
    "ix_messages_attention_item",
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
                for table in (*_NEW_TABLES, *_PRIOR_TABLES):
                    conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            engine.dispose()

    _drop_all()
    yield
    _drop_all()


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


def test_empty_to_0005(test_url: str) -> None:
    assert _current_revision(test_url) is None

    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            for table in _NEW_TABLES:
                assert (
                    conn.execute(text(f"SELECT to_regclass('{table}')")).scalar_one() is not None
                ), f"{table} missing after upgrade to {HEAD_REVISION}"
    finally:
        engine.dispose()

    for column in _NEW_COLUMNS:
        assert _column_exists(test_url, "telegram_messages", column), f"{column} missing"


def test_new_indexes_exist(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    for index_name in _NEW_INDEXES:
        assert _index_exists(test_url, index_name), f"{index_name} missing after upgrade"


def test_head_down_to_0004_up_returns_to_the_identical_version_with_no_manual_repair(
    test_url: str,
) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, HEAD_REVISION)
    head_revision = _current_revision(test_url)
    assert head_revision == HEAD_REVISION

    command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == BASELINE_REVISION

    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            for table in _NEW_TABLES:
                assert (
                    conn.execute(text(f"SELECT to_regclass('{table}')")).scalar_one() is None
                ), f"{table} still present after downgrade to {BASELINE_REVISION}"
    finally:
        engine.dispose()
    for column in _NEW_COLUMNS:
        assert not _column_exists(
            test_url, "telegram_messages", column
        ), f"{column} still present after downgrade to {BASELINE_REVISION}"

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == head_revision
