"""`make tg-doctor` — is Telegram ingestion set up correctly? (`contracts/health-ingestion.md`
§2, FR-036).

Composition root, exempt from the reverse boundary check by directory — may read moderation
tables and call the provider directly, mirroring `make doctor`'s shape: prose, non-zero on a
real problem, useful with no credential present. Never prints the credential (FR-039); reports
only its presence.
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import ingestion_state, telegram_chats
from app.providers.telegram.client import TelegramClient, TelegramProvider
from app.providers.telegram.errors import TelegramError


def _allowed_updates(settings: Settings) -> list[str]:
    return [kind.strip() for kind in settings.telegram_allowed_updates.split(",") if kind.strip()]


async def _run(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider | None = None,
) -> int:
    print("Telegram ingestion diagnostics")

    if settings.telegram_bot_token is None:
        print("  credential            absent")
        print("  (no credential configured — this is the supported offline state)")
        return 0

    print("  credential            present")
    active_client = client if client is not None else TelegramClient(
        settings.telegram_bot_token, base_url=settings.telegram_api_base_url
    )

    try:
        identity = await active_client.get_me()
    except TelegramError as exc:
        print(f"  getMe                 FAILED — {exc.category}")
        return 1

    print(f"  getMe                 ok — @{identity.username} (id {identity.bot_id})")

    exit_code = 0

    webhook = await active_client.get_webhook_info()
    if webhook.url:
        print(f"  webhook               SET to {webhook.url!r}  ← required: NOT set")
        exit_code = 1
    else:
        print("  webhook               NOT set")

    expected = set(_allowed_updates(settings))
    async with session_factory() as session:
        asserted = (
            await session.execute(
                sa.select(ingestion_state.c.allowed_updates).where(
                    ingestion_state.c.bot_id == identity.bot_id
                )
            )
        ).scalar_one_or_none()

        chat_rows = (
            await session.execute(
                sa.select(
                    telegram_chats.c.title,
                    telegram_chats.c.bot_status,
                    telegram_chats.c.bot_can_delete,
                    telegram_chats.c.is_monitored,
                ).order_by(telegram_chats.c.title)
            )
        ).all()

    if asserted is None:
        print("  allowed_updates       not yet asserted (ingestion has not run)")
    else:
        asserted_set = set(asserted)
        if asserted_set != expected:
            print(
                f"  allowed_updates       MISMATCH — configured {sorted(expected)}, "
                f"last asserted {sorted(asserted_set)}"
            )
            exit_code = 1
        else:
            print(f"  allowed_updates       matches configuration ({len(expected)} kinds)")

    print("  chats")
    not_admin: list[str] = []
    for row in chat_rows:
        title = row.title or "(untitled)"
        can_delete = "yes" if row.bot_can_delete else "no"
        monitored = "monitored" if row.is_monitored else "not monitored"
        flag = ""
        if row.is_monitored and row.bot_status != "administrator":
            flag = "   ⚠ not admin"
            not_admin.append(title)
        print(f"    {title:<30} {row.bot_status:<14} can_delete={can_delete:<4} {monitored}{flag}")

    if not_admin:
        print(f"\n⚠ {len(not_admin)} monitored chat(s) where the bot is not an administrator.")
        print("  chat_member and message_reaction updates are NOT being delivered, silently.")
        exit_code = 1

    return exit_code


def main() -> None:
    settings = load_settings()
    session_factory = make_session_factory(make_engine(settings))
    sys.exit(asyncio.run(_run(settings, session_factory=session_factory)))


if __name__ == "__main__":
    main()
