"""Migration lifecycle for revision 0003 — telegram_updates, ingestion_state, ingestion_gaps,
telegram_chats (Principle I: migrations that transform schema; SC-019).

Runs against `injaz_ai_test` only. TEST_DATABASE_URL already carries the ai_migrator identity.
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
BASELINE_REVISION = "0002"
HEAD_REVISION = "0003"

_NEW_TABLES = ("telegram_updates", "ingestion_state", "ingestion_gaps", "telegram_chats")


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
                # TG-M2's tables FK into telegram_chats/telegram_users, so they must drop first.
                for table in (
                    "moderator_group_assignments",
                    "telegram_messages",
                    "moderators",
                    "telegram_users",
                    *_NEW_TABLES,
                    "model_runs",
                    "model_profiles",
                    "users",
                ):
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            engine.dispose()

    _drop_all()
    yield
    _drop_all()


def _constraint_exists(test_url: str, name: str) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(
                    text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": name}
                ).first()
                is not None
            )
    finally:
        engine.dispose()


def _index_exists(test_url: str, name: str, *, partial: bool = False) -> bool:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": name}
            ).first()
            if row is None:
                return False
            if partial:
                return "WHERE" in row[0]
            return True
    finally:
        engine.dispose()


def test_empty_to_0003(test_url: str) -> None:
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


def test_unique_constraints_exist(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _constraint_exists(test_url, "uq_telegram_updates_bot_update")
    assert _constraint_exists(test_url, "uq_telegram_chats_chat_id")


def test_check_constraints_exist(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _constraint_exists(test_url, "ck_telegram_updates_type")
    assert _constraint_exists(test_url, "ck_ingestion_gaps_reason")
    assert _constraint_exists(test_url, "ck_telegram_chats_bot_status")


def test_partial_pending_index_exists(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _index_exists(test_url, "ix_telegram_updates_pending", partial=True)


def test_head_down_to_0002_up_returns_to_the_identical_version_with_no_manual_repair(
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

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == head_revision
