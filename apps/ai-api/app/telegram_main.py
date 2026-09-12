"""The Telegram capture entrypoint — composition root, exempt from the reverse boundary check by
directory (D-TG-29). Runs as its own `ai-telegram` container: the poller durably stores events,
detects gaps and stalls, discovers chats, and holds the same-machine single-consumer lease. All
interpretation happens in the worker (source plan §7.3), never here.

`dramatiq.set_broker(...)` must run before `app.application.moderation.ingest` is ever imported:
that module imports `process_update`, whose `@dramatiq.actor` decorator binds to whichever broker
is active *at import time* (mirrors `app/main.py`'s `create_app()` and `app/workers/main.py`).
Importing `ingest` at this module's top level — before `main()` has a chance to set the broker —
would bind `process_update.send(...)` to dramatiq's lazily-created default broker (`localhost`),
unreachable from inside this container, instead of `settings.redis_url`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import make_engine, make_session_factory
from app.infrastructure.logging import configure_logging
from app.infrastructure.queue import make_broker
from app.infrastructure.redis import make_redis_client
from app.providers.telegram.client import TelegramClient, TelegramProvider
from app.providers.telegram.errors import TelegramConflictError, TelegramError

logger = logging.getLogger(__name__)

_POLL_ERROR_BACKOFF_S = 1.0


def _allowed_updates(settings: Settings) -> list[str]:
    return [kind.strip() for kind in settings.telegram_allowed_updates.split(",") if kind.strip()]


async def _poll_once(
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider,
    *,
    bot_id: int,
    bot_username: str | None,
    allowed_updates: list[str],
    settings: Settings,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """One poll cycle. Returns `True` when the caller must stop entirely — a conflict
    stand-down (FR-004a) — and `False` otherwise, stalled-resync or ordinary alike.

    Checks for a stall (`contracts/telegram-provider.md` §5, D-TG-33) before every ordinary
    poll: cheap when nothing is wrong (one read of `ingestion_state`), and the only place a
    strictly-forward offset would otherwise poll forever without ever receiving Telegram's
    renumbered identifier.
    """
    from app.application.moderation.ingest import (
        apply_chat_migration_if_any,
        handle_conflict,
        next_offset,
        record_identifier_jump_if_any,
        record_poll_outcome,
        record_reset_outcome,
        resync_after_stall,
        store_batch,
        upsert_chats_from_batch,
    )

    try:
        resynced = await resync_after_stall(
            session_factory,
            client,
            bot_id=bot_id,
            allowed_updates=allowed_updates,
            limit=settings.telegram_poll_limit,
            timeout_s=settings.telegram_poll_timeout_s,
            stall_window_s=settings.moderation_stall_resync_s,
        )
        if resynced is None:
            offset = await next_offset(session_factory, bot_id=bot_id)
            fetched = await client.get_updates(
                offset=offset,
                limit=settings.telegram_poll_limit,
                timeout_s=settings.telegram_poll_timeout_s,
                allowed_updates=allowed_updates,
            )
        else:
            fetched = resynced
    except TelegramConflictError:
        return await handle_conflict(
            session_factory,
            bot_id=bot_id,
            standdown_count=settings.telegram_conflict_standdown_count,
            sleep=sleep,
        )
    except TelegramError as exc:
        logger.warning("poll failed, retrying: %s", exc.category)
        await sleep(_POLL_ERROR_BACKOFF_S)
        return False

    stored = []
    if fetched:
        if resynced is None:
            # Meaningless on the resync path: a reset is defined as adopting whatever
            # identifier comes back, even a lower one, never as a jump to investigate.
            await record_identifier_jump_if_any(
                session_factory,
                bot_id=bot_id,
                incoming_update_ids=[update.update_id for update in fetched],
                stall_window_s=settings.moderation_stall_resync_s,
            )
        stored = await store_batch(session_factory, bot_id=bot_id, updates=fetched)
        await upsert_chats_from_batch(session_factory, updates=fetched)
        for update in fetched:
            await apply_chat_migration_if_any(session_factory, update=update)

    if resynced is not None:
        await record_reset_outcome(
            session_factory,
            bot_id=bot_id,
            bot_username=bot_username,
            allowed_updates=allowed_updates,
            stored=stored,
        )
    else:
        await record_poll_outcome(
            session_factory,
            bot_id=bot_id,
            bot_username=bot_username,
            allowed_updates=allowed_updates,
            stored=stored,
        )
    return False


async def _run(settings: Settings) -> None:
    from app.application.moderation.ingest import (
        PollLeaseHeldElsewhereError,
        hold_poll_lease,
        record_downtime_if_any,
        resolve_bot_identity,
    )
    from app.workers.tasks.moderation.drain_pending_updates import drain_pending_updates

    assert settings.telegram_bot_token is not None
    client = TelegramClient(settings.telegram_bot_token, base_url=settings.telegram_api_base_url)
    identity = await resolve_bot_identity(client)

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    redis = make_redis_client(settings)
    allowed_updates = _allowed_updates(settings)

    try:
        async with hold_poll_lease(redis):
            # Startup-only reconciliation, inside the lease so only one process on this
            # machine ever runs it concurrently with live capture (G3, D-TG-37).
            await record_downtime_if_any(
                session_factory,
                bot_id=identity.bot_id,
                min_silence_s=settings.moderation_gap_min_silence_s,
            )
            drain_pending_updates.send()

            while True:
                stood_down = await _poll_once(
                    session_factory,
                    client,
                    bot_id=identity.bot_id,
                    bot_username=identity.username,
                    allowed_updates=allowed_updates,
                    settings=settings,
                )
                if stood_down:
                    logger.warning(
                        "stood down after repeated conflicts; requires an explicit restart"
                    )
                    return
    except PollLeaseHeldElsewhereError:
        logger.warning("another capture process already holds the poll lease on this machine")
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    dramatiq.set_broker(make_broker(settings))

    if settings.telegram_bot_token is None:
        logger.info("no TELEGRAM_BOT_TOKEN configured; ingestion not running")
        return

    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
