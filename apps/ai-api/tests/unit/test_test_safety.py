"""The Principle II guard predicate, unit-tested against accepted and rejected URL shapes
(FR-028, SC-010, research D-21).
"""

from __future__ import annotations

import pytest
from app.infrastructure.test_safety import check_test_database_url

DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"

ACCEPTED = [
    pytest.param(
        "postgresql+psycopg://ai_migrator:x@localhost:5432/injaz_ai_test",
        id="localhost-with-_test-marker",
    ),
    pytest.param(
        "postgresql+psycopg://ai_migrator:x@127.0.0.1:5432/injaz_ai_test",
        id="127.0.0.1-with-_test-marker",
    ),
    pytest.param(
        "postgresql+psycopg://ai_migrator:x@[::1]:5432/injaz_ai_test",
        id="ipv6-loopback-with-_test-marker",
    ),
]

REJECTED = [
    pytest.param(None, "TEST_DATABASE_URL is not set", id="unset"),
    pytest.param("", "TEST_DATABASE_URL is not set", id="empty-string"),
    pytest.param("not a url", "not a valid database URL", id="unparseable"),
    pytest.param(
        "postgresql+psycopg://ai_migrator:x@localhost:5432/injaz_ai",
        'does not contain "_test"',
        id="no-_test-marker",
    ),
    pytest.param(
        "postgresql+psycopg://ai_migrator:x@prod.example.com:5432/injaz_ai_test",
        "is not local",
        id="non-local-host",
    ),
]


@pytest.mark.parametrize("test_database_url", ACCEPTED)
def test_accepted_urls_are_safe(test_database_url: str) -> None:
    assert check_test_database_url(test_database_url, DATABASE_URL) is None


@pytest.mark.parametrize(("test_database_url", "expected_reason"), REJECTED)
def test_rejected_urls_name_the_reason(test_database_url: str | None, expected_reason: str) -> None:
    reason = check_test_database_url(test_database_url, DATABASE_URL)

    assert reason is not None
    assert expected_reason in reason


def test_rejected_when_identical_to_database_url() -> None:
    same_url = "postgresql+psycopg://ai_migrator:x@localhost:5432/injaz_ai_test"

    reason = check_test_database_url(same_url, database_url=same_url)

    assert reason is not None
    assert "identical to DATABASE_URL" in reason


def test_accepted_when_no_database_url_is_configured() -> None:
    reason = check_test_database_url(
        "postgresql+psycopg://ai_migrator:x@localhost:5432/injaz_ai_test", None
    )

    assert reason is None
