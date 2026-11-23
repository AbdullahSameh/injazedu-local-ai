"""`make tg-doctor` — is Telegram ingestion set up correctly? (`contracts/health-ingestion.md`
§2, FR-036).

Composition root, exempt from the reverse boundary check by directory — may read moderation
tables and call the provider directly, mirroring `make doctor`'s shape: prose, non-zero on a
real problem, useful with no credential present. Never prints the credential (FR-039); reports
only its presence.

TG-M6 D5 (`specs/013-tg-m6-alerts/contracts/alerting.md` §1): the alert destination — whether one is
designated, the bot's standing there (read-only `getChatMember`: it must be a member or an
administrator to post), and that it is not monitored. With no destination, alerts are recorded
as not sent (D4); that is a problem only while a rule is enabled.
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.moderation.incident import RESOLVING_REACTION, allows_resolving_reaction
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.models_moderation import alert_rules, ingestion_state, telegram_chats
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
                    telegram_chats.c.chat_id,
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
    no_eyes: list[str] = []
    for row in chat_rows:
        title = row.title or "(untitled)"
        can_delete = "yes" if row.bot_can_delete else "no"
        monitored = "monitored" if row.is_monitored else "not monitored"
        flag = ""
        if row.is_monitored and row.bot_status != "administrator":
            flag = "   ⚠ not admin"
            not_admin.append(title)
        elif row.is_monitored:
            flag = await _eyes_flag(active_client, chat_id=row.chat_id)
            if flag.startswith("   ⚠"):
                no_eyes.append(title)
        print(f"    {title:<30} {row.bot_status:<14} can_delete={can_delete:<4} {monitored}{flag}")

    if not_admin:
        print(f"\n⚠ {len(not_admin)} monitored chat(s) where the bot is not an administrator.")
        print("  chat_member and message_reaction updates are NOT being delivered, silently.")
        exit_code = 1

    if no_eyes:
        print(
            f"\n⚠ {len(no_eyes)} monitored chat(s) whose reactions do not include "
            f"{RESOLVING_REACTION}."
        )
        print("  A moderator cannot resolve an incident there with a reaction (TG-M4.1).")
        exit_code = 1

    if not await _destination_ok(active_client, session_factory, bot_id=identity.bot_id):
        exit_code = 1

    return exit_code


# D5: the bot can post in the destination as a member or an administrator.
_POSTING_STANDINGS = ("member", "administrator")


async def _destination_ok(
    client: TelegramProvider,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
) -> bool:
    """TG-M6 D5, one line: designated or not, the bot's standing there, and not monitored."""
    async with session_factory() as session:
        destination = (
            await session.execute(
                sa.select(
                    telegram_chats.c.chat_id,
                    telegram_chats.c.title,
                    telegram_chats.c.is_monitored,
                ).where(telegram_chats.c.is_alert_destination.is_(True))
            )
        ).one_or_none()
        enabled_rules = (
            await session.execute(
                sa.select(sa.func.count()).select_from(alert_rules).where(
                    alert_rules.c.is_enabled.is_(True)
                )
            )
        ).scalar_one()

    if destination is None:
        if enabled_rules:
            print(
                f"  alert destination     NONE — {enabled_rules} enabled rule(s); "
                "every alert is recorded as not sent"
            )
            return False
        print("  alert destination     none designated (no rule is enabled)")
        return True

    title = destination.title or "(untitled)"
    problems: list[str] = []
    try:
        member = await client.get_chat_member(chat_id=destination.chat_id, user_id=bot_id)
        standing = member.status
        if standing in _POSTING_STANDINGS:
            posting = f"bot can post ({standing})"
        else:
            posting = f"bot CANNOT post ({standing})"
            problems.append("bot cannot post")
    except TelegramError as exc:
        posting = f"bot standing unknown — {exc.category}"
        problems.append("bot standing unknown")
    monitored = "MONITORED" if destination.is_monitored else "not monitored"
    if destination.is_monitored:
        problems.append("monitored")

    flag = "   ⚠" if problems else ""
    print(f"  alert destination     designated — {title}; {posting}; {monitored}{flag}")
    return not problems


async def _eyes_flag(client: TelegramProvider, *, chat_id: int) -> str:
    """TG-M4.1 E9: whether moderators can react 👀 in this chat — read-only `getChat`. A failed
    read is reported, not guessed."""
    try:
        available = await client.get_chat_available_reactions(chat_id=chat_id)
    except TelegramError as exc:
        return f"   ? {RESOLVING_REACTION} unknown — {exc.category}"
    if allows_resolving_reaction(available):
        return f"   {RESOLVING_REACTION} allowed"
    return f"   ⚠ {RESOLVING_REACTION} not allowed"


def main() -> None:
    settings = load_settings()
    session_factory = make_session_factory(make_engine(settings))
    sys.exit(asyncio.run(_run(settings, session_factory=session_factory)))


if __name__ == "__main__":
    main()
