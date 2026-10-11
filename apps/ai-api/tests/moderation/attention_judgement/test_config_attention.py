"""`MODERATION_ATTENTION_PROMPT_VERSION` (TG-M5.3, `data-model.md` §7, D-TG-189, `tasks.md` T017).

Blank and unset are one state: no attention instruction, so no call and nothing recorded (FR-307).
A value must be in `ATTENTION_PROMPT_VERSIONS` (`attention_v1` since the freeze, T074); a value
outside it exits naming the variable, never with a stack trace — the fail-fast pattern of
`tests/moderation/classification/test_config_classification.py`.
"""

from __future__ import annotations

import pytest
from app.infrastructure import config
from app.infrastructure.config import load_settings

VALID_DATABASE_URL = "postgresql+psycopg://ai_app:x@localhost:5432/injaz_ai"
VALID_REDIS_URL = "redis://localhost:6379/0"


def _clear_ai_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "REDIS_URL", "MODERATION_ATTENTION_PROMPT_VERSION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", VALID_REDIS_URL)


def test_unset_is_no_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)

    assert load_settings().moderation_attention_prompt_version is None


def test_blank_is_no_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_ATTENTION_PROMPT_VERSION", "")

    assert load_settings().moderation_attention_prompt_version is None


@pytest.mark.parametrize("value", ["attention_v1", "classify_v2", "nonsense"])
def test_a_version_outside_the_allowlist_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """With the allowlist as it was before the freeze (empty), even `attention_v1` is refused; a
    classification instruction is never an attention one."""
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setattr(config, "ATTENTION_PROMPT_VERSIONS", ())
    monkeypatch.setenv("MODERATION_ATTENTION_PROMPT_VERSION", value)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "MODERATION_ATTENTION_PROMPT_VERSION" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("value", ["classify_v2", "attention_v2"])
def test_the_frozen_allowlist_refuses_anything_else(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_ATTENTION_PROMPT_VERSION", value)

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert exc_info.value.code == 1
    assert "MODERATION_ATTENTION_PROMPT_VERSION" in capsys.readouterr().err


def test_the_frozen_version_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """T074: `attention_v1` is the one selectable attention instruction."""
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setenv("MODERATION_ATTENTION_PROMPT_VERSION", "attention_v1")

    assert config.ATTENTION_PROMPT_VERSIONS == ("attention_v1",)
    assert load_settings().moderation_attention_prompt_version == "attention_v1"


def test_a_version_in_the_allowlist_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_api_env(monkeypatch)
    monkeypatch.setattr(config, "ATTENTION_PROMPT_VERSIONS", ("attention_test",))
    monkeypatch.setenv("MODERATION_ATTENTION_PROMPT_VERSION", "attention_test")

    assert load_settings().moderation_attention_prompt_version == "attention_test"
