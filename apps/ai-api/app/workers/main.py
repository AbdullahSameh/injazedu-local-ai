"""Dramatiq worker entrypoint. Run with: dramatiq app.workers.main --processes 2 --threads 4."""

from __future__ import annotations

import dramatiq

from app.infrastructure.config import load_settings
from app.infrastructure.logging import configure_logging
from app.infrastructure.queue import make_broker

settings = load_settings()
configure_logging(settings.log_level)
dramatiq.set_broker(make_broker(settings))
