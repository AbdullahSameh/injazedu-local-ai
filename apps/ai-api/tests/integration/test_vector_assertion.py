"""The baseline migration fails loudly with a readable message when `vector` is absent — it must
never silently skip (spec edge case, research D-03). Runs against `injaz_ai_test` only.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

APP_DIR = Path(__file__).resolve().parents[2]


def _superuser_url() -> str:
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        pytest.skip(
            "POSTGRES_PASSWORD is not set — cannot drop/recreate the extension for this test"
        )
    user = os.environ.get("POSTGRES_USER", "postgres")
    url = make_url(os.environ["TEST_DATABASE_URL"]).set(username=user, password=password)
    return url.render_as_string(hide_password=False)


@pytest.fixture
def superuser_engine() -> Iterator[Engine]:
    engine = create_engine(_superuser_url())
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
            conn.execute(text("DROP TABLE IF EXISTS users"))
        engine.dispose()


def test_migration_fails_loudly_when_vector_extension_is_absent(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DROP EXTENSION IF EXISTS vector CASCADE"))

    test_url = os.environ["TEST_DATABASE_URL"]
    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_url)

    with pytest.raises(RuntimeError, match="vector"):
        command.upgrade(cfg, "head")
