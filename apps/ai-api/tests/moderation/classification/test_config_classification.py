"""Validators for the four AI Classification settings (`data-model.md` §1, `plan.md` operator
item 3): `MODERATION_CONFIDENCE_FLOOR`, `MODERATION_INCIDENT_CONFIDENCE`,
`MODERATION_CLASSIFY_MAX_ATTEMPTS`, `MODERATION_CLASSIFY_RETRY_BASE_S`.

Same fail-fast pattern as the other moderation settings: a bad value exits naming the variable,
never a stack trace (`tasks.md` T004).
"""

from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"

_CLASSIFICATION_VARS = (
    "MODERATION_CONFIDENCE_FLOOR",
    "MODERATION_INCIDENT_CONFIDENCE",
    "MODERATION_CLASSIFY_MAX_ATTEMPTS",
    "MODERATION_CLASSIFY_RETRY_BASE_S",
)


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "REDIS_URL", *_CLASSIFICATION_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.moderation_confidence_floor == 0.60
    assert settings.moderation_incident_confidence == 0.85
    assert settings.moderation_classify_max_attempts == 5
    assert settings.moderation_classify_retry_base_s == 30


@pytest.mark.parametrize(
    ("var", "field_name", "default"),
    [
        ("MODERATION_CONFIDENCE_FLOOR", "moderation_confidence_floor", 0.60),
        ("MODERATION_INCIDENT_CONFIDENCE", "moderation_incident_confidence", 0.85),
        ("MODERATION_CLASSIFY_MAX_ATTEMPTS", "moderation_classify_max_attempts", 5),
        ("MODERATION_CLASSIFY_RETRY_BASE_S", "moderation_classify_retry_base_s", 30),
    ],
)
def test_empty_string_reads_the_default(
    monkeypatch: pytest.MonkeyPatch, var: str, field_name: str, default: float
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv(var, "")

    settings = load_settings()

    assert getattr(settings, field_name) == default


def test_floor_above_threshold_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_CONFIDENCE_FLOOR", "0.9")
    monkeypatch.setenv("MODERATION_INCIDENT_CONFIDENCE", "0.8")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_CONFIDENCE_FLOOR" in err
    assert "MODERATION_INCIDENT_CONFIDENCE" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", ["1.2", "-0.1"])
def test_confidence_floor_out_of_range_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_CONFIDENCE_FLOOR", value)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_CONFIDENCE_FLOOR" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", ["1.2", "-0.1"])
def test_incident_confidence_out_of_range_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_INCIDENT_CONFIDENCE", value)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_INCIDENT_CONFIDENCE" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", [0, -1])
def test_max_attempts_rejects_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: int
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_CLASSIFY_MAX_ATTEMPTS", str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_CLASSIFY_MAX_ATTEMPTS" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", [0, -1])
def test_retry_base_rejects_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: int
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_CLASSIFY_RETRY_BASE_S", str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_CLASSIFY_RETRY_BASE_S" in err
    assert "Traceback" not in err


def test_a_valid_configuration_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_CONFIDENCE_FLOOR", "0.5")
    monkeypatch.setenv("MODERATION_INCIDENT_CONFIDENCE", "0.9")
    monkeypatch.setenv("MODERATION_CLASSIFY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("MODERATION_CLASSIFY_RETRY_BASE_S", "15")

    settings = load_settings()

    assert settings.moderation_confidence_floor == 0.5
    assert settings.moderation_incident_confidence == 0.9
    assert settings.moderation_classify_max_attempts == 3
    assert settings.moderation_classify_retry_base_s == 15
