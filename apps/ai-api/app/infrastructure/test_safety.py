"""The Principle II guard: a pure predicate deciding whether a test database URL is safe.

Extracted from tests/conftest.py so the negative cases are unit-testable without a real
misconfigured database (research D-21).
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", None}


def check_test_database_url(test_database_url: str | None, database_url: str | None) -> str | None:
    """Return None if `test_database_url` is safe to run tests against, else a reason string."""
    if not test_database_url:
        return "TEST_DATABASE_URL is not set"

    try:
        test_url = make_url(test_database_url)
    except Exception as exc:  # noqa: BLE001 — any parse failure is a rejection, not a crash
        return f"TEST_DATABASE_URL is not a valid database URL: {exc}"

    database_name = test_url.database or ""
    if "_test" not in database_name:
        return f'database name "{database_name}" does not contain "_test"'

    if database_url and test_database_url == database_url:
        return "TEST_DATABASE_URL is identical to DATABASE_URL"

    if test_url.host not in _LOCAL_HOSTS:
        return f'host "{test_url.host}" is not local'

    return None
