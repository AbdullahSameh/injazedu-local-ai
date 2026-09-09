"""JSON line logging to stdout — stdlib only, no new dependency (FR-009, research D-15)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_EXTRA_KEYS = ("update_id", "chat_id", "message_id", "incident_id", "alert_id", "actor")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # A whitelist by construction, not by filtering (D-TG-24): an unlisted key — including
        # any text-bearing one — has no path to the output, whatever a future call site passes
        # through extra=. "message_id", never "message" — stdlib logging rejects the latter
        # (research.md §0 probe 8).
        for key in _EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
