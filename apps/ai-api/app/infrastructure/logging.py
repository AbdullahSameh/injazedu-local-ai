"""JSON line logging to stdout — stdlib only, no new dependency (FR-009, research D-15)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_EXTRA_KEYS = (
    "update_id",
    "chat_id",
    "message_id",
    "item_id",
    "incident_id",
    "alert_id",
    "actor",
)


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

    # httpx logs every request's full URL at INFO (its own documented behaviour, not a bug in
    # this codebase) — and Telegram's Bot API puts the credential *in the URL path*
    # (`/bot<TOKEN>/<method>`), unlike a bearer header. At the default INFO level that would
    # print the token verbatim on every call. The JsonFormatter's `_EXTRA_KEYS` whitelist only
    # guards structured `extra=` fields (D-TG-24); it does nothing for a third-party logger's own
    # message string, so the credential must never reach this logger's INFO level at all.
    logging.getLogger("httpx").setLevel(logging.WARNING)
