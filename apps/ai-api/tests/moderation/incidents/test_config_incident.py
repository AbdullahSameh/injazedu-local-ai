"""Validator for `MODERATION_INCIDENT_MAX_AGE_S` (data-model.md §1, research D-TG-122).

Same fail-fast pattern as the other moderation settings: a bad value exits naming the variable,
never a stack trace.
"""

from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "REDIS_URL", "MODERATION_INCIDENT_MAX_AGE_S"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_default_is_86400(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.moderation_incident_max_age_s == 86400


@pytest.mark.parametrize("value", [0, -1])
def test_rejects_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: int
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_INCIDENT_MAX_AGE_S", str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_INCIDENT_MAX_AGE_S" in err
    assert "Traceback" not in err


def test_positive_value_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_INCIDENT_MAX_AGE_S", "3600")

    settings = load_settings()

    assert settings.moderation_incident_max_age_s == 3600
