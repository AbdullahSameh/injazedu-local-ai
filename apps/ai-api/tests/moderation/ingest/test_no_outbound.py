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
_CONTROL_SOURCE_DIR = _REPO_ROOT / "apps" / "ai-control" / "app"
_CONTROL_VIEWS_DIR = _REPO_ROOT / "apps" / "ai-control" / "resources" / "views"

# TG-M3's four new actors (`app/workers/tasks/moderation/`) and the Live Attention Queue panel
# page are already inside `_APP_SOURCE_DIR`'s glob below for the Python side; these two directories
# extend the same check to the PHP side, which the pre-existing scan never reached (SC-020).
_OUTBOUND_INDICATOR_PATTERN = re.compile(
    "|".join(_FORBIDDEN_METHODS) + r"|Http::|GuzzleHttp|curl_"
)


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


def test_no_new_worker_actor_references_an_outbound_call() -> None:
    """TG-M3's four new actors (`evaluate_attention`, `match_response`, `sweep_unjudged_bursts`,
    `expire_stale_items`) — this milestone opens, matches, ages and expires items, and posts
    nothing (FR-071, SC-020)."""
    actors_dir = _APP_SOURCE_DIR / "workers" / "tasks" / "moderation"
    offenders = [
        path
        for path in actors_dir.glob("*.py")
        if _OUTBOUND_INDICATOR_PATTERN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"forbidden method referenced in: {offenders}"


def test_the_live_attention_queue_panel_makes_no_outbound_call() -> None:
    """FR-072, SC-020: the Live Attention Queue is a read screen plus two guarded writes to
    `attention_items` — dismiss and hand-open. Neither, nor anything else on the page, may call
    the Bot API or any other outbound HTTP client."""
    offenders = [
        path
        for directory in (_CONTROL_SOURCE_DIR, _CONTROL_VIEWS_DIR)
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix == ".php"
        and _OUTBOUND_INDICATOR_PATTERN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"forbidden method referenced in: {offenders}"
