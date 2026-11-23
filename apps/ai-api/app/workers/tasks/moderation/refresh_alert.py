"""`refresh_alert` — edits a posted alert when its render state changed (`contracts/alerting.md`
§6, D-TG-216). Runs on the `default` queue.

`alert_delivery.refresh` renders from the derived state, edits, sets `final_at` once the subject
has ended and `excerpt_shown` as the new text has it, and resets or records the edit fields. Never
retried by the broker: a failed edit is recorded and retried by the next evaluation, up to
`MAX_EDIT_ATTEMPTS` consecutive failures (U3).
"""

from __future__ import annotations

import logging

import dramatiq

from app.application.moderation.alert_delivery import refresh
from app.infrastructure.config import load_settings
from app.infrastructure.db import run_with_worker_session
from app.workers.tasks.moderation.deliver_alert import render_settings, telegram_client

logger = logging.getLogger(__name__)


@dramatiq.actor(max_retries=0)
def refresh_alert(alert_id: int) -> None:
    settings = load_settings()
    client = telegram_client(settings)
    run_with_worker_session(
        lambda session_factory: refresh(
            session_factory, client, alert_id, render_settings(settings)
        ),
        settings,
    )
