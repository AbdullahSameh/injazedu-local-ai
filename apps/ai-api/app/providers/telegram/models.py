"""Value shapes for the Telegram provider (`contracts/telegram-provider.md` §3, data-model.md §5).

`TelegramUpdate` models only what routing needs — `update_id`, the kind, the chat id — plus
`raw` carrying the whole update for storage. The provider deliberately does not model the Bot
API's object graph: a Bot API addition never breaks ingestion because TG-M2+ reads what it needs
out of the stored payload.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Mirrors `ck_telegram_updates_type` (data-model.md §1). An unrecognised kind maps to "unknown"
# and is stored regardless (FR-012) — this is not a validated Literal for that reason.
UpdateKind = str


class TelegramUpdate(BaseModel):
    update_id: int
    kind: UpdateKind
    chat_id: int | None
    raw: dict[str, Any]


class BotIdentity(BaseModel):
    bot_id: int
    username: str | None


class WebhookInfo(BaseModel):
    """Only what `tg-doctor` needs to assert: the platform's inbound delivery is not configured."""

    url: str


class ChatMemberStatus(BaseModel):
    status: str
    can_delete_messages: bool | None = None
