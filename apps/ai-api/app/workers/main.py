"""Dramatiq worker entrypoint. Run with: dramatiq app.workers.main --processes 2 --threads 4."""

from __future__ import annotations

import dramatiq

from app.infrastructure.config import load_settings
from app.infrastructure.logging import configure_logging
from app.infrastructure.queue import make_broker

settings = load_settings()
configure_logging(settings.log_level)
dramatiq.set_broker(make_broker(settings))

from app.workers.tasks import diagnostics as _diagnostics  # noqa: E402,F401
from app.workers.tasks.moderation import (  # noqa: E402,F401
    drain_pending_updates as _drain_pending_updates,
)
from app.workers.tasks.moderation import (  # noqa: E402,F401
    evaluate_attention as _evaluate_attention,
)
from app.workers.tasks.moderation import (  # noqa: E402,F401
    expire_stale_items as _expire_stale_items,
)
from app.workers.tasks.moderation import (  # noqa: E402,F401
    match_response as _match_response,
)
from app.workers.tasks.moderation import process_update as _process_update  # noqa: E402,F401
from app.workers.tasks.moderation import (  # noqa: E402,F401
    sweep_unjudged_bursts as _sweep_unjudged_bursts,
)
