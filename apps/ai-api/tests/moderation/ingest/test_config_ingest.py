"""Validators for the six TG-M1 ingestion settings (config.py, .env.example).

Same fail-fast pattern as the gateway and TG-M0 moderation settings: a bad value exits naming
the variable, never a stack trace. FR-041; `TELEGRAM_POLL_LIMIT` additionally enforces the Bot
API's own 1-100 ceiling (D-TG-40, SC-020).
"""

from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"

_INGEST_VARS = (
    "TELEGRAM_API_BASE_URL",
    "TELEGRAM_POLL_TIMEOUT_S",
    "TELEGRAM_POLL_LIMIT",
    "TELEGRAM_CONFLICT_STANDDOWN_COUNT",
    "MODERATION_GAP_MIN_SILENCE_S",
    "MODERATION_STALL_RESYNC_S",
)


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "REDIS_URL", *_INGEST_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_defaults_load_with_no_ingest_variables_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.telegram_api_base_url == "https://api.telegram.org"
    assert settings.telegram_poll_timeout_s == 30
    assert settings.telegram_poll_limit == 100
    assert settings.telegram_conflict_standdown_count == 5
    assert settings.moderation_gap_min_silence_s == 300
    assert settings.moderation_stall_resync_s == 691200


@pytest.mark.parametrize(
    "env_var",
    [
        "TELEGRAM_POLL_TIMEOUT_S",
        "TELEGRAM_CONFLICT_STANDDOWN_COUNT",
        "MODERATION_GAP_MIN_SILENCE_S",
        "MODERATION_STALL_RESYNC_S",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_duration_or_count_rejects_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_var: str,
    value: int,
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv(env_var, str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert env_var in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "env_var",
    [
        "TELEGRAM_POLL_TIMEOUT_S",
        "TELEGRAM_CONFLICT_STANDDOWN_COUNT",
        "MODERATION_GAP_MIN_SILENCE_S",
        "MODERATION_STALL_RESYNC_S",
    ],
)
def test_duration_or_count_positive_value_is_accepted(
    monkeypatch: pytest.MonkeyPatch, env_var: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv(env_var, "1")

    load_settings()  # must not raise or exit


@pytest.mark.parametrize("value", [0, -1, 101, 1000])
def test_telegram_poll_limit_rejects_values_outside_1_to_100(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: int,
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_POLL_LIMIT", str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "TELEGRAM_POLL_LIMIT" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", [1, 50, 100])
def test_telegram_poll_limit_accepts_the_full_bot_api_range(
    monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_POLL_LIMIT", str(value))

    settings = load_settings()  # must not raise or exit

    assert settings.telegram_poll_limit == value
