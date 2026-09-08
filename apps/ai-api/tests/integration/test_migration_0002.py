"""Migration lifecycle for revision 0002 — model_profiles, model_runs (Principle II, FR-009,
FR-011, FR-021, data-model.md §1).

Runs against `injaz_ai_test` only. TEST_DATABASE_URL already carries the ai_migrator identity
(environment.md), so it can drive Alembic directly.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

APP_DIR = Path(__file__).resolve().parents[2]
BASELINE_REVISION = "0001"
HEAD_REVISION = "0002"


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
                conn.execute(text("DROP TABLE IF EXISTS model_runs"))
                conn.execute(text("DROP TABLE IF EXISTS model_profiles"))
                conn.execute(text("DROP TABLE IF EXISTS users"))
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            engine.dispose()

    _drop_all()
    yield
    _drop_all()


def _insert_profile(conn: object, **overrides: object) -> int:
    values: dict[str, object] = {
        "name": "test-profile",
        "provider": "fake",
        "base_url": None,
        "model": "test-model",
        "role": "llm",
        "params": "{}",
        "dim": None,
        "api_key_env": None,
        "is_active": False,
    }
    values.update(overrides)
    result = conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO model_profiles "
            "(name, provider, base_url, model, role, params, dim, api_key_env, is_active) "
            "VALUES (:name, :provider, :base_url, :model, :role, CAST(:params AS JSONB), :dim, "
            ":api_key_env, :is_active) RETURNING id"
        ),
        values,
    )
    return result.scalar_one()  # type: ignore[no-any-return]


def test_empty_to_head(test_url: str) -> None:
    assert _current_revision(test_url) is None

    command.upgrade(_alembic_config(test_url), "head")

    assert _current_revision(test_url) == HEAD_REVISION


def test_head_down_one_up_returns_to_the_identical_version_with_no_manual_repair(
    test_url: str,
) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, "head")
    head_revision = _current_revision(test_url)
    assert head_revision is not None

    command.downgrade(cfg, "-1")
    assert _current_revision(test_url) == BASELINE_REVISION

    command.upgrade(cfg, "head")
    assert _current_revision(test_url) == head_revision


def test_partial_unique_index_refuses_a_second_active_profile_for_one_role(
    test_url: str,
) -> None:
    command.upgrade(_alembic_config(test_url), "head")

    engine = create_engine(test_url)
    try:
        with engine.begin() as conn:
            _insert_profile(conn, name="llm-a", role="llm", is_active=True)

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_profile(conn, name="llm-b", role="llm", is_active=True)

        # A second active profile for the *other* role is unaffected.
        with engine.begin() as conn:
            _insert_profile(
                conn, name="embed-a", role="embedding", dim=768, is_active=True
            )
    finally:
        engine.dispose()


def test_ck_model_profiles_dim_refuses_an_embedding_profile_with_a_null_dim(
    test_url: str,
) -> None:
    command.upgrade(_alembic_config(test_url), "head")

    engine = create_engine(test_url)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_profile(conn, name="embed-bad", role="embedding", dim=None)
    finally:
        engine.dispose()
