"""Validators for the nine GATEWAY_* settings (research D-31–D-33, D-37; contracts/environment.md).

Same fail-fast pattern as M0's heartbeat check: a bad value exits naming the variable, never a
stack trace.
"""

from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"

_GATEWAY_VARS = (
    "GATEWAY_CALL_TIMEOUT_S",
    "GATEWAY_MAX_RETRIES",
    "GATEWAY_RETRY_BASE_S",
    "GATEWAY_BREAKER_THRESHOLD",
    "GATEWAY_BREAKER_OPEN_S",
    "GATEWAY_LANE_LEASE_TTL_S",
    "GATEWAY_LANE_RENEW_S",
    "GATEWAY_PROFILE_CACHE_TTL_S",
    "GATEWAY_CAPTURE_PAYLOADS",
)


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "DATABASE_URL",
        "REDIS_URL",
        "OLLAMA_BASE_URL",
        "API_PORT",
        "LOG_LEVEL",
        "WORKER_PROCESSES",
        "WORKER_THREADS",
        "WORKER_HEARTBEAT_INTERVAL_S",
        "WORKER_HEARTBEAT_TTL_S",
        *_GATEWAY_VARS,
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_defaults_load_with_no_gateway_variables_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.gateway_call_timeout_s == 180
    assert settings.gateway_max_retries == 2
    assert settings.gateway_lane_lease_ttl_s == 30
    assert settings.gateway_lane_renew_s == 10
    assert settings.gateway_capture_payloads is False


def test_lane_renew_must_be_less_than_lease_ttl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_LANE_LEASE_TTL_S", "10")
    monkeypatch.setenv("GATEWAY_LANE_RENEW_S", "10")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "GATEWAY_LANE_RENEW_S" in err
    assert "GATEWAY_LANE_LEASE_TTL_S" in err
    assert "Traceback" not in err


def test_lane_renew_less_than_lease_ttl_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_LANE_LEASE_TTL_S", "30")
    monkeypatch.setenv("GATEWAY_LANE_RENEW_S", "10")

    settings = load_settings()

    assert settings.gateway_lane_lease_ttl_s == 30
    assert settings.gateway_lane_renew_s == 10


@pytest.mark.parametrize(
    "value",
    [0, -1],
)
def test_call_timeout_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: int
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_CALL_TIMEOUT_S", str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "GATEWAY_CALL_TIMEOUT_S" in err
    assert "Traceback" not in err


def test_max_retries_must_be_non_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_MAX_RETRIES", "-1")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "GATEWAY_MAX_RETRIES" in err
    assert "Traceback" not in err


def test_max_retries_zero_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_MAX_RETRIES", "0")

    settings = load_settings()

    assert settings.gateway_max_retries == 0
