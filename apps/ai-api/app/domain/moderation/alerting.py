"""TG-M6 alerting's pure definitions (`specs/013-tg-m6-alerts/contracts/alerting.md`).

Pure: the standard library only (`zoneinfo` included), no I/O, no clock, no session. Every instant
is passed in. The evaluator, delivery, the press gate and the renderer all read these, so each rule
has one definition:

- the triggers, subject types, press actions and press outcomes;
- quiet hours (R7, F5, D-TG-223): `[from, to)` windows in `Asia/Riyadh`, crossing midnight when
  `to < from`;
- the repeat index (F3, D-TG-213): never back-filled;
- the dedupe key (FR-522): `{rule}:{subject_type}:{subject_id}[@{episode}]:{repeat_index}`;
- callback data (B1, T2): `a:<alert_id>:<h|f|t>`, and nothing else;
- the severity order (R4): `low < medium < high`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

# D-TG-223 / Finding 31: the panel's one display timezone.
ALERT_TIMEZONE = ZoneInfo("Asia/Riyadh")

# data-model §3: `alerts.dedupe_key` is VARCHAR(160).
DEDUPE_KEY_MAX = 160

# FR-540, V1: at most this many delivery attempts per alert.
MAX_DELIVERY_ATTEMPTS = 5

# U3: at most this many consecutive failed edits per alert, then the tick stops trying.
MAX_EDIT_ATTEMPTS = 5


class Trigger(StrEnum):
    QUESTION_WAITING = "question_waiting"
    INCIDENT_FLAGGED = "incident_flagged"
    INCIDENT_UNHANDLED = "incident_unhandled"
    GROUP_SILENT = "group_silent"
    BOT_NOT_ADMIN = "bot_not_admin"


class SubjectType(StrEnum):
    ATTENTION_ITEM = "attention_item"
    INCIDENT = "incident"
    CHAT = "chat"


class PressAction(StrEnum):
    HANDLED = "h"
    FALSE_POSITIVE = "f"
    TAKE = "t"


class PressOutcome(StrEnum):
    """`alerting.md` §5 and `alert-messages.md` §5: what a press led to."""

    RECORDED = "recorded"
    RECORDED_NOT_TEAM = "recorded_not_team"
    ALREADY_TAKEN = "already_taken"
    ALREADY_ENDED = "already_ended"
    NOT_A_MODERATOR = "not_a_moderator"
    INVALID = "invalid"


SUBJECT_OF: dict[Trigger, SubjectType] = {
    Trigger.QUESTION_WAITING: SubjectType.ATTENTION_ITEM,
    Trigger.INCIDENT_FLAGGED: SubjectType.INCIDENT,
    Trigger.INCIDENT_UNHANDLED: SubjectType.INCIDENT,
    Trigger.GROUP_SILENT: SubjectType.CHAT,
    Trigger.BOT_NOT_ADMIN: SubjectType.CHAT,
}

# B1: `h` and `f` on incidents, `t` on questions, nothing on a group's health.
ACTIONS_FOR: dict[SubjectType, frozenset[PressAction]] = {
    SubjectType.INCIDENT: frozenset({PressAction.HANDLED, PressAction.FALSE_POSITIVE}),
    SubjectType.ATTENTION_ITEM: frozenset({PressAction.TAKE}),
    SubjectType.CHAT: frozenset(),
}

# The three act kinds a press records (D-TG-217).
ACT_KIND: dict[PressAction, str] = {
    PressAction.HANDLED: "alert_handled",
    PressAction.FALSE_POSITIVE: "alert_false_positive",
    PressAction.TAKE: "alert_take",
}


# --- quiet hours ---


@dataclass(frozen=True)
class QuietWindow:
    """`[start, end)` in `ALERT_TIMEZONE`. `end < start` crosses midnight."""

    start: time
    end: time

    def contains(self, local: time) -> bool:
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


_HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


def _parse_hhmm(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    match = _HHMM_RE.match(value)
    if match is None:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def parse_quiet_hours(raw: Any) -> tuple[tuple[QuietWindow, ...], int]:
    """The rule's windows, and how many entries were skipped as malformed: not an object, a bad
    `HH:MM`, or `from == to` (R7). The database only checks that `quiet_hours` is an array; the
    panel validates the shape, and this parser never trusts it."""
    if not isinstance(raw, list):
        return (), 0 if raw in (None, []) else 1
    windows: list[QuietWindow] = []
    skipped = 0
    for entry in raw:
        start = _parse_hhmm(entry.get("from")) if isinstance(entry, dict) else None
        end = _parse_hhmm(entry.get("to")) if isinstance(entry, dict) else None
        if start is None or end is None or start == end:
            skipped += 1
            continue
        windows.append(QuietWindow(start=start, end=end))
    return tuple(windows), skipped


def in_quiet_hours(windows: tuple[QuietWindow, ...], instant: datetime) -> bool:
    """Whether `instant` (timezone-aware) falls inside any window, judged in `Asia/Riyadh`."""
    if instant.tzinfo is None:
        raise ValueError("in_quiet_hours needs a timezone-aware instant")
    local = instant.astimezone(ALERT_TIMEZONE).time().replace(tzinfo=None)
    return any(window.contains(local) for window in windows)


# --- repeats ---


def due_repeat_index(
    first_fired_at: datetime,
    now: datetime,
    every_s: int | None,
    max_repeats: int | None,
) -> int:
    """F3: `least(floor((now − first_fired_at) / every_s), max_repeats)`, or 0 for a rule with no
    repeats. The caller inserts index k only when no alert for that rule, subject and episode has
    an index ≥ k, so after an outage the missed indexes are never back-filled."""
    if every_s is None or max_repeats is None or every_s <= 0 or max_repeats <= 0:
        return 0
    elapsed = (now - first_fired_at).total_seconds()
    if elapsed <= 0:
        return 0
    return min(math.floor(elapsed / every_s), max_repeats)


# --- the dedupe key ---

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def episode_token(episode_at: datetime) -> int:
    """Microseconds since the epoch, exactly: two episodes a second apart never share a key."""
    return (episode_at - _EPOCH) // timedelta(microseconds=1)


def dedupe_key(
    rule_id: int,
    subject_type: SubjectType | str,
    subject_id: int,
    episode_at: datetime | None,
    repeat_index: int,
) -> str:
    """`{rule}:{subject_type}:{subject_id}[@{episode}]:{repeat_index}` (data-model §3)."""
    episode = f"@{episode_token(episode_at)}" if episode_at is not None else ""
    key = f"{rule_id}:{SubjectType(subject_type).value}:{subject_id}{episode}:{repeat_index}"
    if len(key) > DEDUPE_KEY_MAX:
        raise ValueError("dedupe key longer than the column")
    return key


# --- callback data (B1, T2) ---

_CALLBACK_RE = re.compile(r"^a:([1-9][0-9]{0,17}):([hft])$")


def encode_callback(alert_id: int, action: PressAction) -> str:
    if alert_id <= 0:
        raise ValueError("alert_id must be positive")
    return f"a:{alert_id}:{PressAction(action).value}"


def decode_callback(data: Any) -> tuple[int, PressAction] | None:
    """`(alert_id, action)` for exactly `a:<positive id>:<h|f|t>`, else `None`. The data alone is
    never trusted: the gate also requires it to name the alert posted as the pressed message."""
    if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
        return None
    match = _CALLBACK_RE.match(data)
    if match is None:
        return None
    return int(match.group(1)), PressAction(match.group(2))


# --- severity (R4) ---

SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def severity_at_least(severity: str, minimum: str | None) -> bool:
    """Whether `severity` meets a rule's `min_severity` in the order `low < medium < high`. No
    minimum matches everything; an unknown value matches nothing."""
    if minimum is None:
        return True
    if severity not in SEVERITY_ORDER or minimum not in SEVERITY_ORDER:
        return False
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[minimum]
