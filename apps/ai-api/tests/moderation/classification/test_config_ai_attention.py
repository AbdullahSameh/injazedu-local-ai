"""`MODERATION_AI_ATTENTION_FROM` — TG-M5.1's dated switch (D-TG-164, decision 4). Blank and unset
are one state, off; a value is an instant with an explicit offset; a naive one exits naming the
variable, never a stack trace — the same fail-fast pattern as every other moderation setting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.application.moderation.attention import AiAttention, ai_attention_from_settings
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "DATABASE_URL",
        "REDIS_URL",
        "MODERATION_AI_ATTENTION_FROM",
        "MODERATION_ITEM_MAX_AGE_S",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.moderation_ai_attention_from is None
    assert ai_attention_from_settings(settings) is None


def test_blank_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_AI_ATTENTION_FROM", "")

    assert ai_attention_from_settings(load_settings()) is None


def test_an_instant_with_an_offset_switches_on_with_the_item_max_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_AI_ATTENTION_FROM", "2026-10-04T09:00:00+03:00")
    monkeypatch.setenv("MODERATION_ITEM_MAX_AGE_S", "3600")

    settings = load_settings()

    expected = datetime(2026, 10, 4, 9, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    assert settings.moderation_ai_attention_from == expected
    assert ai_attention_from_settings(settings) == AiAttention(
        enabled_from=datetime(2026, 10, 4, 6, 0, 0, tzinfo=UTC), max_age_s=3600
    )


def test_a_naive_instant_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_AI_ATTENTION_FROM", "2026-10-04T09:00:00")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_AI_ATTENTION_FROM" in err
    assert "Traceback" not in err


def test_a_value_that_is_not_an_instant_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_AI_ATTENTION_FROM", "yes")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_AI_ATTENTION_FROM" in err
    assert "Traceback" not in err
