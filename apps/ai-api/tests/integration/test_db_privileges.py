"""ai_control and ai_app are refused DDL; both can still SELECT/UPDATE `users` (FR-013, SC-005,
contracts/database-roles.md). Runs against `injaz_ai_test` only (Principle II).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

APP_DIR = Path(__file__).resolve().parents[2]

ROLES = [("ai_control", "AI_CONTROL_PASSWORD"), ("ai_app", "AI_APP_PASSWORD")]


def _role_url(role: str, password_env: str) -> str:
    password = os.environ.get(password_env)
    if not password:
        pytest.skip(f"{password_env} is not set — cannot connect as {role} for this test")
    url = make_url(os.environ["TEST_DATABASE_URL"]).set(username=role, password=password)
    return url.render_as_string(hide_password=False)


@pytest.fixture(autouse=True)
def _migrated_schema() -> Iterator[None]:
    test_url = os.environ["TEST_DATABASE_URL"]
    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_url)

    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.mark.parametrize(("role", "password_env"), ROLES)
def test_role_is_refused_create_table(role: str, password_env: str) -> None:
    engine = create_engine(_role_url(role, password_env))
    try:
        with engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text("CREATE TABLE nope (id int)"))
    finally:
        engine.dispose()


@pytest.mark.parametrize(("role", "password_env"), ROLES)
def test_role_is_refused_drop_table_users(role: str, password_env: str) -> None:
    engine = create_engine(_role_url(role, password_env))
    try:
        with engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text("DROP TABLE users"))
    finally:
        engine.dispose()


@pytest.mark.parametrize(("role", "password_env"), ROLES)
def test_role_is_refused_alter_table_users(role: str, password_env: str) -> None:
    engine = create_engine(_role_url(role, password_env))
    try:
        with engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text("ALTER TABLE users ADD COLUMN nope int"))
    finally:
        engine.dispose()


@pytest.mark.parametrize(("role", "password_env"), ROLES)
def test_role_can_select_and_update_users(role: str, password_env: str) -> None:
    engine = create_engine(_role_url(role, password_env))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (name, email, password) "
                    "VALUES ('t', 't@example.com', 'x') ON CONFLICT DO NOTHING"
                )
            )
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM users")).fetchall()
            assert len(rows) >= 1
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET name = 'updated' WHERE email = 't@example.com'"))
    finally:
        engine.dispose()
