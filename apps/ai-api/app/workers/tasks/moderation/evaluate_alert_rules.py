"""`evaluate_alert_rules` — fires alerts and finds alerts to edit (`contracts/alerting.md` §3, §6).
Enqueued by the tick's lease winner once per `MODERATION_TICK_INTERVAL_S`; runs on the `default`
queue.

One evaluation inserts into `alerts` only (F7) and every returned non-suppressed id is sent to
`deliver_alert` at once; only then does the refresh scan compare each followed alert's computed
render state with its stored one and send every changed alert to `refresh_alert`, so a failing
scan never strands a fired alert as `pending`. Never retried by the broker: the next tick
evaluates again, and F2/F3 make that harmless (F8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alerting import (
    Evaluation,
    RenderSettings,
    changed_alerts,
    evaluate_once,
)
from app.infrastructure.config import load_settings
from app.infrastructure.db import run_with_worker_session
from app.workers.tasks.moderation.deliver_alert import deliver_alert, render_settings
from app.workers.tasks.moderation.refresh_alert import refresh_alert

logger = logging.getLogger(__name__)


def _ignore(_alert_id: int) -> None:
    return None


async def evaluate_alert_rules_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: RenderSettings,
    *,
    send_delivery: Callable[[int], object] = _ignore,
    send_refresh: Callable[[int], object] = _ignore,
) -> tuple[Evaluation, list[int]]:
    async with session_factory() as session:
        evaluation = await evaluate_once(session)
    for alert_id in evaluation.to_deliver:
        send_delivery(alert_id)
    changed = await changed_alerts(session_factory, settings)
    for alert_id in changed:
        send_refresh(alert_id)
    return evaluation, changed


@dramatiq.actor(max_retries=0)
def evaluate_alert_rules() -> None:
    settings = load_settings()
    evaluation, changed = run_with_worker_session(
        lambda session_factory: evaluate_alert_rules_once(
            session_factory,
            render_settings(settings),
            send_delivery=deliver_alert.send,
            send_refresh=refresh_alert.send,
        ),
        settings,
    )
    if evaluation.skipped_windows:
        logger.warning(
            "alert rules: %d malformed quiet-hours windows skipped", evaluation.skipped_windows
        )
    logger.info(
        "alert rules evaluated: %d to deliver, %d suppressed, %d to refresh",
        len(evaluation.to_deliver),
        len(evaluation.suppressed),
        len(changed),
    )
