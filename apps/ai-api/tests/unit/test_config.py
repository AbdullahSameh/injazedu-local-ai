from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"


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
    ):
        monkeypatch.delenv(var, raising=False)


def test_missing_database_url_exits_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "DATABASE_URL" in err
    assert "Traceback" not in err


def test_missing_redis_url_exits_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "REDIS_URL" in err
    assert "Traceback" not in err


def test_heartbeat_ttl_not_exceeding_interval_is_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_S", "20")
    monkeypatch.setenv("WORKER_HEARTBEAT_TTL_S", "15")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "WORKER_HEARTBEAT_TTL_S" in err
    assert "WORKER_HEARTBEAT_INTERVAL_S" in err


def test_valid_configuration_loads_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_S", "5")
    monkeypatch.setenv("WORKER_HEARTBEAT_TTL_S", "15")

    settings = load_settings()

    assert settings.database_url == VALID_DATABASE_URL
    assert settings.redis_url == VALID_REDIS_URL
