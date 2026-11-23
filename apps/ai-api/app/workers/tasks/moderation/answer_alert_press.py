"""`answer_alert_press` — answers a press in the alert group, then refreshes its alert
(`contracts/alerting.md` §5 B7). Runs on the `default` queue.

`process_update` enqueues it after `derive_alert_press` has recorded the act (or nothing), with the
outcome. The answer is `alert-messages.md` §5's text for that outcome, sent through
`alert_delivery.answer_press` (its guard refuses a press in a monitored chat). A press too old to
answer, or an answer whose outcome is unknown, is logged by category and ignored. The pressed
alert is then refreshed whatever the answer did, so its text follows the act at once rather than
at the next tick.
"""

from __future__ import annotations

import logging

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alert_delivery import answer_press, refresh
from app.application.moderation.alert_press import press_answer
from app.application.moderation.alerting import RenderSettings
from app.domain.moderation.alerting import PressOutcome
from app.infrastructure.config import load_settings
from app.infrastructure.db import run_with_worker_session
from app.providers.telegram.client import TelegramProvider
from app.workers.tasks.moderation.deliver_alert import render_settings, telegram_client

logger = logging.getLogger(__name__)


async def answer_alert_press_once(
    session_factory: async_sessionmaker[AsyncSession],
    client: TelegramProvider,
    settings: RenderSettings,
    update_row_id: int,
    outcome: PressOutcome,
) -> None:
    answer = await press_answer(session_factory, update_row_id, outcome)
    try:
        if answer.callback_query_id is not None:
            await answer_press(
                session_factory,
                client,
                chat_id=answer.chat_id,
                callback_query_id=answer.callback_query_id,
                text=answer.text,
            )
    finally:
        if answer.alert_id is not None:
            await refresh(session_factory, client, answer.alert_id, settings)


@dramatiq.actor(max_retries=2, min_backoff=1_000, max_backoff=5_000)
def answer_alert_press(update_row_id: int, outcome: str) -> None:
    settings = load_settings()
    client = telegram_client(settings)
    run_with_worker_session(
        lambda session_factory: answer_alert_press_once(
            session_factory, client, render_settings(settings), update_row_id, PressOutcome(outcome)
        ),
        settings,
    )
