"""Session-wide safety net: no test may run against a non-test database (Principle II)."""

from __future__ import annotations

import os

import pytest
from app.infrastructure.test_safety import check_test_database_url


@pytest.fixture(scope="session", autouse=True)
def _test_database_guard() -> None:
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    database_url = os.environ.get("DATABASE_URL")

    reason = check_test_database_url(test_database_url, database_url)
    if reason is not None:
        pytest.exit(f"Refusing to run: unsafe TEST_DATABASE_URL — {reason}", returncode=1)
