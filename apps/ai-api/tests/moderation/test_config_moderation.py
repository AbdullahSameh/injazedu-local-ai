"""Validators for the five moderation settings (data-model.md §1, contracts/environment.md).

Same fail-fast pattern as the gateway settings: a bad value exits naming the variable, never a
stack trace. FR-008, FR-010, SC-005.
"""

from __future__ import annotations

import pytest
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"

_MODERATION_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_UPDATES",
    "MODERATION_BURST_GAP_S",
    "MODERATION_ITEM_MAX_AGE_S",
    "MODERATION_GROUP_ANSWER_WINDOW_S",
    "MODERATION_TEXT_RETENTION_DAYS",
    "MODERATION_PANEL_BASE_URL",
)


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "DATABASE_URL",
        "REDIS_URL",
        *_MODERATION_VARS,
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_defaults_load_with_no_moderation_variables_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.telegram_bot_token is None
    assert settings.telegram_allowed_updates == (
        "message,edited_message,my_chat_member,chat_member,message_reaction,callback_query"
    )
    assert settings.moderation_burst_gap_s == 90
    assert settings.moderation_item_max_age_s == 86400
    assert settings.moderation_text_retention_days == 90


def test_telegram_bot_token_absent_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    settings = load_settings()

    assert settings.telegram_bot_token is None


def test_telegram_bot_token_empty_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")

    settings = load_settings()

    assert settings.telegram_bot_token is None


def test_telegram_allowed_updates_empty_is_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ALLOWED_UPDATES", "")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "TELEGRAM_ALLOWED_UPDATES" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("env_var", "field_name"),
    [
        ("MODERATION_BURST_GAP_S", "MODERATION_BURST_GAP_S"),
        ("MODERATION_ITEM_MAX_AGE_S", "MODERATION_ITEM_MAX_AGE_S"),
        ("MODERATION_GROUP_ANSWER_WINDOW_S", "MODERATION_GROUP_ANSWER_WINDOW_S"),
        ("MODERATION_TEXT_RETENTION_DAYS", "MODERATION_TEXT_RETENTION_DAYS"),
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_duration_rejects_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_var: str,
    field_name: str,
    value: int,
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv(env_var, str(value))

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert field_name in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "env_var",
    [
        "MODERATION_BURST_GAP_S",
        "MODERATION_ITEM_MAX_AGE_S",
        "MODERATION_GROUP_ANSWER_WINDOW_S",
        "MODERATION_TEXT_RETENTION_DAYS",
    ],
)
def test_duration_positive_value_is_accepted(
    monkeypatch: pytest.MonkeyPatch, env_var: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv(env_var, "1")

    load_settings()  # must not raise or exit


def test_the_group_answer_window_defaults_to_thirty_minutes_blank_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_api_env(monkeypatch)
    assert load_settings().moderation_group_answer_window_s == 1800
    monkeypatch.setenv("MODERATION_GROUP_ANSWER_WINDOW_S", "")
    assert load_settings().moderation_group_answer_window_s == 1800


# --- TG-M6: MODERATION_PANEL_BASE_URL (data-model §7, D-TG-224) ---


@pytest.mark.parametrize("value", [None, ""])
def test_the_panel_base_url_absent_or_blank_means_no_panel_link(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    _clear_ai_api_env(monkeypatch)
    if value is not None:
        monkeypatch.setenv("MODERATION_PANEL_BASE_URL", value)

    assert load_settings().moderation_panel_base_url is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://panel.example.org", "https://panel.example.org"),
        ("https://panel.example.org/", "https://panel.example.org"),
        ("http://localhost:8080", "http://localhost:8080"),
    ],
)
def test_the_panel_base_url_is_kept_without_a_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_PANEL_BASE_URL", value)

    assert load_settings().moderation_panel_base_url == expected


@pytest.mark.parametrize(
    "value", ["panel.example.org", "ftp://panel.example.org", "https://", "javascript:alert(1)"]
)
def test_a_malformed_panel_base_url_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_PANEL_BASE_URL", value)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_PANEL_BASE_URL" in err
    assert "Traceback" not in err
