"""The ingestion health probe (`contracts/health-ingestion.md` §1, D-TG-31).

Lives inside the moderation boundary out of necessity — probe 4 proved `app/application/probes/`
fails `make check` the instant it reads a moderation table (research.md Finding 2). Composed at
the composition root (`app/main.py`) and wired into `/health` only when present
(`app/api/v1/health.py`), so this module is never imported outside the moderation boundary.

⚠ Returns `IngestionProbeResult`, never `health_service.ComponentReport` directly: the forward
boundary check permits a moderation module to import `app.application.moderation` only, not
`app.application.health_service` (the reverse rule's own exemption doesn't reach this direction).
`app/main.py` — a composition root, unrestricted — does the wrapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import (
    ingestion_gaps,
    ingestion_state,
    telegram_chats,
    telegram_updates,
)
from app.providers.telegram.client import TelegramClient, TelegramProvider
from app.providers.telegram.errors import TelegramAuthError, TelegramError

REQUIRED = False


@dataclass(frozen=True)
class IngestionProbeResult:
    """Mirrors `health_service.ComponentReport`'s shape without importing it (see module
    docstring). `status` is one of `ComponentState`'s own values — `"ok"`, `"degraded"`,
    `"down"` — so `app/main.py` can wrap this as `ComponentState(result.status)` verbatim."""

    status: str
    required: bool
    detail: str
    ingestion: dict[str, Any]

# "chats_silent_over_6h" — the most likely silent failure to go unnoticed (contracts/
# health-ingestion.md §1): a bot demoted without being removed stops receiving several kinds
# with no error anywhere.
_SILENT_THRESHOLD_S = 6 * 3600

_EMPTY_BOT_SCOPED_FIELDS: dict[str, Any] = {
    "last_update_at": None,
    "seconds_since_last_poll": None,
    "pending_updates": 0,
    "consecutive_failures": 0,
    "open_gaps": 0,
    "stood_down": False,
}


async def _chat_fields(engine: AsyncEngine) -> dict[str, Any]:
    """`telegram_chats` carries no `bot_id` (data-model.md §4: chats are global), so these three
    fields are independent of whether identity has resolved."""
    async with engine.connect() as conn:
        monitored_chats = (
            await conn.execute(
                sa.select(sa.func.count())
                .select_from(telegram_chats)
                .where(telegram_chats.c.is_monitored.is_(True))
            )
        ).scalar_one()

        silent_cutoff = datetime.now(UTC) - timedelta(seconds=_SILENT_THRESHOLD_S)
        chats_silent_over_6h = (
            await conn.execute(
                sa.select(sa.func.count())
                .select_from(telegram_chats)
                .where(
                    telegram_chats.c.is_monitored.is_(True),
                    sa.or_(
                        telegram_chats.c.last_event_at.is_(None),
                        telegram_chats.c.last_event_at < silent_cutoff,
                    ),
                )
            )
        ).scalar_one()

        bot_not_admin_in = (
            await conn.execute(
                sa.select(telegram_chats.c.title)
                .where(
                    telegram_chats.c.is_monitored.is_(True),
                    telegram_chats.c.bot_status != "administrator",
                )
                .order_by(telegram_chats.c.title)
            )
        ).scalars().all()

    return {
        "monitored_chats": monitored_chats,
        "chats_silent_over_6h": chats_silent_over_6h,
        "bot_not_admin_in": [title for title in bot_not_admin_in if title is not None],
    }


async def _bot_scoped_fields(engine: AsyncEngine, bot_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        state_row = (
            await conn.execute(
                sa.select(
                    ingestion_state.c.last_event_at,
                    ingestion_state.c.last_poll_at,
                    ingestion_state.c.consecutive_failures,
                    ingestion_state.c.stood_down_at,
                ).where(ingestion_state.c.bot_id == bot_id)
            )
        ).one_or_none()
        pending_updates = (
            await conn.execute(
                sa.select(sa.func.count())
                .select_from(telegram_updates)
                .where(
                    telegram_updates.c.bot_id == bot_id, telegram_updates.c.processed_at.is_(None)
                )
            )
        ).scalar_one()
        open_gaps = (
            await conn.execute(
                sa.select(sa.func.count())
                .select_from(ingestion_gaps)
                .where(ingestion_gaps.c.bot_id == bot_id, ingestion_gaps.c.gap_end_at.is_(None))
            )
        ).scalar_one()

    if state_row is None:
        return {
            **_EMPTY_BOT_SCOPED_FIELDS,
            "pending_updates": pending_updates,
            "open_gaps": open_gaps,
        }

    now = datetime.now(UTC)
    seconds_since_last_poll = (
        int((now - state_row.last_poll_at).total_seconds())
        if state_row.last_poll_at is not None
        else None
    )
    return {
        "last_update_at": state_row.last_event_at,
        "seconds_since_last_poll": seconds_since_last_poll,
        "pending_updates": pending_updates,
        "consecutive_failures": state_row.consecutive_failures,
        "open_gaps": open_gaps,
        "stood_down": state_row.stood_down_at is not None,
    }


async def check(
    *,
    engine: AsyncEngine,
    settings: Settings,
    client: TelegramProvider | None = None,
) -> IngestionProbeResult:
    """Renders the eight FR-034 fields plus `credential`, `bot_identity` and `stood_down`
    (`contracts/health-ingestion.md` §1). `required=False` throughout (G6): a deliberately
    stopped or never-configured bot must never make the system look unready.

    `bot_identity` is resolved with a live, read-only `get_me()` call — the same call
    `tg-doctor` makes — because the process that actually holds this state (`ai-telegram`) is a
    separate one, and TG-M1 adds no shared channel for it to report identity failures back
    through. This mirrors `model_runtime`'s own probe, which already calls Ollama live; `get_me`
    carries none of `getUpdates`' single-consumer constraint (`contracts/telegram-provider.md`
    §1), so this adds no second poller.
    """
    chat_fields = await _chat_fields(engine)
    token = settings.telegram_bot_token

    if token is None:
        return IngestionProbeResult(
            status="ok",
            required=REQUIRED,
            detail="no credential configured",
            ingestion={
                "credential": "absent",
                "bot_identity": "not_attempted",
                **_EMPTY_BOT_SCOPED_FIELDS,
                **chat_fields,
            },
        )

    active_client = client if client is not None else TelegramClient(
        token, base_url=settings.telegram_api_base_url
    )
    try:
        identity = await active_client.get_me()
    except TelegramAuthError:
        return IngestionProbeResult(
            status="down",
            required=REQUIRED,
            detail="credential rejected",
            ingestion={
                "credential": "configured",
                "bot_identity": "rejected",
                **_EMPTY_BOT_SCOPED_FIELDS,
                **chat_fields,
            },
        )
    except TelegramError:
        return IngestionProbeResult(
            status="degraded",
            required=REQUIRED,
            detail="platform unreachable",
            ingestion={
                "credential": "configured",
                "bot_identity": "unreachable",
                **_EMPTY_BOT_SCOPED_FIELDS,
                **chat_fields,
            },
        )

    bot_scoped = await _bot_scoped_fields(engine, identity.bot_id)
    detail = f"resolved as @{identity.username}" if identity.username else "resolved"
    return IngestionProbeResult(
        status="ok",
        required=REQUIRED,
        detail=detail,
        ingestion={
            "credential": "configured",
            "bot_identity": "resolved",
            **bot_scoped,
            **chat_fields,
        },
    )
