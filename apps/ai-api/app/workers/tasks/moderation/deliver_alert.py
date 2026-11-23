"""`deliver_alert` — posts one alert to the alert group, at most once (`contracts/alerting.md` §4,
D-TG-215). Runs on the `default` queue.

`alert_delivery.deliver` does the work. A retryable failure (connect-phase, 5xx, an exhausted 429)
is raised as `AlertDeliveryRetryError`, so Dramatiq's own exponential backoff schedules the next
attempt; the claim's `attempts < 5` bounds them whatever the broker does. An unknown outcome is
never raised: it is final (V5).
"""

from __future__ import annotations

import logging

import dramatiq

from app.application.moderation.alert_delivery import DeliveryOutcome, deliver
from app.application.moderation.alerting import RenderSettings
from app.domain.moderation.alerting import MAX_DELIVERY_ATTEMPTS
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import run_with_worker_session
from app.providers.telegram.client import TelegramClient

logger = logging.getLogger(__name__)


class AlertDeliveryRetryError(Exception):
    """Raised so the broker retries a delivery with backoff. Carries the alert id only."""


def render_settings(settings: Settings) -> RenderSettings:
    return RenderSettings(
        panel_base_url=settings.moderation_panel_base_url,
        retention_days=settings.moderation_text_retention_days,
    )


def telegram_client(settings: Settings) -> TelegramClient:
    """The worker's own client for the three outbound methods. The token is required here: the
    `ai-worker` container receives it for delivery alone (T501)."""
    if settings.telegram_bot_token is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set for the alert worker")
    return TelegramClient(settings.telegram_bot_token, base_url=settings.telegram_api_base_url)


@dramatiq.actor(
    max_retries=MAX_DELIVERY_ATTEMPTS - 1, min_backoff=15_000, max_backoff=300_000
)
def deliver_alert(alert_id: int) -> None:
    settings = load_settings()
    client = telegram_client(settings)
    outcome = run_with_worker_session(
        lambda session_factory: deliver(
            session_factory, client, alert_id, render_settings(settings)
        ),
        settings,
    )
    if outcome is DeliveryOutcome.RETRY:
        raise AlertDeliveryRetryError(str(alert_id))
