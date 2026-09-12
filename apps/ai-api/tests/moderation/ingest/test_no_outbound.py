"""US6 — the bot stays silent (FR-001, FR-038, SC-015, `contracts/telegram-provider.md` §8,
`contracts/ingestion-guarantees.md` G5).

Absence is normally a smell to test for; here silence is a headline guarantee whose violation is
a visible incident in a real student group, so these assertions check the provider's shape and
scan the change set directly rather than trusting a narrower unit test to catch a regression.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.providers.telegram.client import TelegramClient, TelegramProvider

# The Bot API's admin/send methods (`contracts/telegram-provider.md` §1, §8) — none may exist on
# this provider in TG-M1, and none may be called anywhere in the application source.
_FORBIDDEN_METHODS = (
    "sendMessage",
    "setMessageReaction",
    "deleteMessage",
    "banChatMember",
    "restrictChatMember",
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_APP_SOURCE_DIR = _REPO_ROOT / "apps" / "ai-api" / "app"


def test_no_forbidden_method_exists_on_the_provider() -> None:
    for name in _FORBIDDEN_METHODS:
        assert not hasattr(TelegramProvider, name), f"{name} must not exist on TelegramProvider"
        assert not hasattr(TelegramClient, name), f"{name} must not exist on TelegramClient"


def test_no_forbidden_call_appears_anywhere_in_the_application_source() -> None:
    pattern = re.compile("|".join(_FORBIDDEN_METHODS))
    offenders = [
        path
        for path in _APP_SOURCE_DIR.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"forbidden method referenced in: {offenders}"


def test_set_webhook_is_not_implemented() -> None:
    # `getWebhookInfo` exists solely so `tg-doctor` can assert one is NOT configured (§8.2);
    # `setWebhook` itself must not exist anywhere on the provider.
    assert hasattr(TelegramProvider, "get_webhook_info")
    assert not hasattr(TelegramProvider, "set_webhook")
    assert not hasattr(TelegramClient, "set_webhook")
    assert "setWebhook" not in (_APP_SOURCE_DIR / "providers" / "telegram" / "client.py").read_text(
        encoding="utf-8"
    )


def _ai_telegram_service_block() -> str:
    compose = (_REPO_ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    lines = compose.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "ai-telegram:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        # The next top-level (two-space-indented) service key ends this block.
        if re.match(r"^  \S", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def test_ai_telegram_service_declares_no_ports() -> None:
    block = _ai_telegram_service_block()
    assert "ports:" not in block
