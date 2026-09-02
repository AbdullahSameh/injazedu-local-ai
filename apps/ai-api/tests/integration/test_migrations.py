"""Migration lifecycle against `injaz_ai_test` only (Principle II, FR-011, FR-012, SC-006).

TEST_DATABASE_URL already carries the ai_migrator identity (environment.md), so it can drive
Alembic directly — no separate migrator connection is needed for this test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

APP_DIR = Path(__file__).resolve().parents[2]
BASELINE_REVISION = "0001"


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
                conn.execute(text("DROP TABLE IF EXISTS users"))
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            engine.dispose()

    _drop_all()
    yield
    _drop_all()


def test_empty_to_head(test_url: str) -> None:
    assert _current_revision(test_url) is None

    command.upgrade(_alembic_config(test_url), "head")

    assert _current_revision(test_url) == BASELINE_REVISION


def test_reapplying_head_is_a_no_op(test_url: str) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, "head")

    command.upgrade(cfg, "head")  # must not raise

    assert _current_revision(test_url) == BASELINE_REVISION


def test_head_down_one_up_returns_to_the_identical_version_with_no_manual_repair(
    test_url: str,
) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, "head")
    head_revision = _current_revision(test_url)
    assert head_revision is not None

    command.downgrade(cfg, "-1")
    assert _current_revision(test_url) is None

    command.upgrade(cfg, "head")
    assert _current_revision(test_url) == head_revision
