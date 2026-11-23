"""The bot stays silent in every monitored group (FR-001, FR-038, SC-015,
`contracts/telegram-provider.md` §8, `contracts/ingestion-guarantees.md` G5), rewritten for TG-M6
(D-TG-227, `contracts/alerting.md` N1, N2, N10).

TG-M6 gives the provider exactly three outbound methods, for the alert group only. The guarantee
becomes three mechanical checks:

1. **Never-methods.** No ban, restrict, unban, delete, react or pin method exists on the provider,
   and no such Bot API name appears anywhere in the application source (N2).
2. **One caller.** The three outbound Bot API names appear only in the provider's client, and the
   three provider methods are called only from `app/application/moderation/alert_delivery.py`, which
   checks the target inside the same transaction before every send or edit (D-TG-227's runtime
   guard, tested in `tests/moderation/alerts/test_deliver.py`).
3. **The panel never calls out** (N10): no Bot API name and no HTTP client in the PHP source.

Absence is normally a smell to test for; here silence is a headline guarantee whose violation is a
visible incident in a real student group, so these assertions scan the source directly rather than
trusting a narrower unit test to catch a regression.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.providers.telegram.client import TelegramClient, TelegramProvider

# N2: never, anywhere. `pinChatMessage` joins TG-M4's list in TG-M6 (D-TG-227).
_NEVER_METHODS = (
    "setMessageReaction",
    "deleteMessage",
    "pinChatMessage",
    "banChatMember",
    "restrictChatMember",
    "unbanChatMember",
    "banChatSenderChat",
    "unbanChatSenderChat",
)
_NEVER_PYTHON_NAMES = (
    "set_message_reaction",
    "delete_message",
    "pin_chat_message",
    "ban_chat_member",
    "restrict_chat_member",
    "unban_chat_member",
    "ban_chat_sender_chat",
    "unban_chat_sender_chat",
    "send_photo",
    "send_document",
    "forward_message",
    "copy_message",
)

# TG-M6's only outbound methods: their Bot API names and the provider's Python names.
_OUTBOUND_METHODS = ("sendMessage", "editMessageText", "answerCallbackQuery")
_OUTBOUND_PYTHON_NAMES = ("send_message", "edit_message_text", "answer_callback_query")

_REPO_ROOT = Path(__file__).resolve().parents[5]
_APP_SOURCE_DIR = _REPO_ROOT / "apps" / "ai-api" / "app"
_PROVIDER_CLIENT = _APP_SOURCE_DIR / "providers" / "telegram" / "client.py"
_ALERT_DELIVERY = _APP_SOURCE_DIR / "application" / "moderation" / "alert_delivery.py"
_CONTROL_SOURCE_DIR = _REPO_ROOT / "apps" / "ai-control" / "app"
_CONTROL_VIEWS_DIR = _REPO_ROOT / "apps" / "ai-control" / "resources" / "views"

_PHP_OUTBOUND_PATTERN = re.compile(
    "|".join((*_NEVER_METHODS, *_OUTBOUND_METHODS)) + r"|Http::|GuzzleHttp|curl_"
)
# A call or attribute access of a provider method, not its definition.
_OUTBOUND_CALL_PATTERN = re.compile(
    r"(?<!def )\b(" + "|".join(_OUTBOUND_PYTHON_NAMES) + r")\s*\("
)


def _python_sources() -> list[Path]:
    return sorted(_APP_SOURCE_DIR.rglob("*.py"))


# --- 1. never-methods ---


def test_no_never_method_exists_on_the_provider() -> None:
    for name in (*_NEVER_METHODS, *_NEVER_PYTHON_NAMES):
        assert not hasattr(TelegramProvider, name), f"{name} must not exist on TelegramProvider"
        assert not hasattr(TelegramClient, name), f"{name} must not exist on TelegramClient"


def test_no_never_method_name_appears_anywhere_in_the_application_source() -> None:
    pattern = re.compile("|".join(_NEVER_METHODS))
    offenders = [path for path in _python_sources() if pattern.search(path.read_text("utf-8"))]
    assert offenders == [], f"forbidden Bot API method referenced in: {offenders}"


def test_the_provider_has_exactly_the_three_outbound_methods() -> None:
    for name in _OUTBOUND_PYTHON_NAMES:
        assert hasattr(TelegramProvider, name), f"{name} missing from TelegramProvider"
        assert hasattr(TelegramClient, name), f"{name} missing from TelegramClient"
    client_source = _PROVIDER_CLIENT.read_text("utf-8")
    bot_api_methods = set(re.findall(r'_request\(\s*"(\w+)"', client_source))
    assert bot_api_methods == {
        "getMe",
        "getUpdates",
        "getWebhookInfo",
        "getChatMember",
        "getChat",
        *_OUTBOUND_METHODS,
    }


# --- 2. one caller ---


def test_the_outbound_bot_api_names_appear_only_in_the_provider_client() -> None:
    pattern = re.compile("|".join(_OUTBOUND_METHODS))
    offenders = [
        path
        for path in _python_sources()
        if path != _PROVIDER_CLIENT and pattern.search(path.read_text("utf-8"))
    ]
    assert offenders == [], f"outbound Bot API method named outside the provider: {offenders}"


def test_the_outbound_methods_are_called_only_from_alert_delivery() -> None:
    offenders = [
        path
        for path in _python_sources()
        if path not in (_PROVIDER_CLIENT, _ALERT_DELIVERY)
        and _OUTBOUND_CALL_PATTERN.search(path.read_text("utf-8"))
    ]
    assert offenders == [], f"outbound provider method called outside alert_delivery: {offenders}"


def test_the_provider_client_never_calls_its_own_outbound_methods() -> None:
    """The client defines the three methods; nothing inside it chains one into another."""
    assert _OUTBOUND_CALL_PATTERN.search(_PROVIDER_CLIENT.read_text("utf-8")) is None


def test_no_worker_actor_calls_telegram_directly() -> None:
    """Actors reach Telegram only through `alert_delivery` (FR-071, SC-020, D-TG-227)."""
    actors_dir = _APP_SOURCE_DIR / "workers" / "tasks" / "moderation"
    pattern = re.compile(
        "|".join((*_NEVER_METHODS, *_OUTBOUND_METHODS)) + r"|Http::|GuzzleHttp|curl_"
    )
    offenders = [
        path
        for path in actors_dir.glob("*.py")
        if pattern.search(path.read_text("utf-8"))
        or _OUTBOUND_CALL_PATTERN.search(path.read_text("utf-8"))
    ]
    assert offenders == [], f"actor calls Telegram directly: {offenders}"


# --- 3. the panel and the poller ---


def test_the_panel_makes_no_outbound_call() -> None:
    """N10, FR-072, SC-020: the panel is read screens plus guarded writes to the database. It may
    never call the Bot API or any other outbound HTTP client, so every alert edit comes from Python
    (D-TG-216)."""
    offenders = [
        path
        for directory in (_CONTROL_SOURCE_DIR, _CONTROL_VIEWS_DIR)
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix == ".php"
        and _PHP_OUTBOUND_PATTERN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"outbound call referenced in: {offenders}"


def test_set_webhook_is_not_implemented() -> None:
    # `getWebhookInfo` exists solely so `tg-doctor` can assert one is NOT configured (§8.2);
    # `setWebhook` itself must not exist anywhere on the provider.
    assert hasattr(TelegramProvider, "get_webhook_info")
    assert not hasattr(TelegramProvider, "set_webhook")
    assert not hasattr(TelegramClient, "set_webhook")
    assert "setWebhook" not in _PROVIDER_CLIENT.read_text(encoding="utf-8")


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
