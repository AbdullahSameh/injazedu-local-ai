"""AI classification — eligibility, consistency and routing
(`contracts/classification-pipeline.md` §3, §6; `data-model.md` §2, tasks.md T018).

Pure: no I/O, no clock, no session, no import outside the standard library and
`app.domain.moderation.attention` (for the one shared acknowledgement matcher, E8). This is the
**only** definition of eligibility and routing (pipeline contract N7): the classifier calls these
functions directly, the panel reads their stored outputs, and no test helper recomputes an
expected route or eligibility — it calls the function or asserts the stored row.

TG-M5.3 (`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §6, D-TG-191):
a prediction no longer proposes a question item. `open_item` reads the attention judgement through
`app.domain.moderation.attention_judgement` (A1-A2, V), and the classification's needs-response is
measurement only. `within_attention_window` (G5-G6) is unchanged and still lives here. TG-M5.1's
`proposes_attention` (G1-G4) and its `NO_RESPONSE_CATEGORIES` are removed, with no second home:
the benchmark judges the attention judgement too (`app/scripts/qualification/attention.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.domain.moderation.attention import is_acknowledgement

# D-TG-08's taxonomy, spelled exactly — an operator's label and a prediction compare without a
# mapping (D-TG-101).
CATEGORIES: tuple[str, ...] = (
    "QUESTION_COURSE",
    "QUESTION_ACCESS",
    "COMPLAINT",
    "CHITCHAT",
    "SPAM_OR_AD",
    "ABUSE",
    "OTHER",
)
SEVERITIES: tuple[str, ...] = ("none", "low", "medium", "high")

# R8's two readings share these sets: a category that can carry a violation at all, and the
# narrower set TG-M4's own incident vocabulary accepts (`incident.CATEGORIES`).
VIOLATION_CATEGORIES: frozenset[str] = frozenset({"SPAM_OR_AD", "ABUSE"})
INCIDENT_CATEGORIES: frozenset[str] = frozenset({"SPAM_OR_AD", "ABUSE", "OTHER"})

TAXONOMY_VERSION = 1

# R4b's structured outside-contact signals: the four placeholders `redact` writes (TG-M0's
# `moderation-text.md` §3), and the message's recorded entity flags. Words such as "خاص" are
# deliberately not signals — "خاصة" (special) appeared in a day-one false positive.
CONTACT_PLACEHOLDERS: tuple[str, ...] = ("«رابط»", "«رقم»", "«بريد»", "«مستخدم»")
_CONTACT_FLAGS: tuple[str, ...] = ("has_url", "has_phone", "has_mention", "forwarded")


@dataclass(frozen=True)
class MessageFacts:
    """The stored facts eligibility (§3) reads, resolved by the caller from `telegram_messages`
    and the message's own captured event — this module has no session to look either up itself."""

    is_service: bool
    media_kind: str | None
    text: str | None
    text_removed: bool
    is_from_moderator: bool
    sender_chat_id: int | None
    group_chat_id: int
    is_automatic_forward: bool


def eligibility(facts: MessageFacts) -> str | None:
    """The first matching exclusion reason (E1-E8, in order), or `None` when the message is
    eligible — including a bot account's message and another channel's message (FR-003)."""
    if facts.text_removed:
        return "text_removed"
    if facts.is_service:
        return "service"
    if facts.media_kind is not None:
        return "media"
    if facts.text is None or not facts.text.strip():
        return "no_text"
    if facts.is_from_moderator:
        return "moderator"
    if facts.sender_chat_id is not None and facts.sender_chat_id == facts.group_chat_id:
        return "group_itself"
    if facts.is_automatic_forward:
        return "linked_channel"
    if is_acknowledgement(facts.text):
        return "acknowledgement"
    return None


@dataclass(frozen=True)
class Prediction:
    """The model's five reported values (§4's `MessageClassificationResult`, confidence already
    quantised by `quantise`)."""

    category: str
    needs_response: bool
    needs_moderation: bool
    severity: str
    confidence: Decimal


def is_consistent(prediction: Prediction) -> bool:
    """R8, both directions (operator item 4, approved): *needs moderation* with a category the
    incident vocabulary accepts and a severity other than `none`; **or** *needs no moderation*
    with a category that is never on its own a violation. Everything else — including an advert
    marked `needs_moderation=False`, and `needs_moderation=True` at `severity='none'` — is
    inconsistent."""
    if prediction.needs_moderation:
        return (
            prediction.category in INCIDENT_CATEGORIES and prediction.severity != "none"
        )
    return prediction.category not in VIOLATION_CATEGORIES


def has_contact_signal(*, entity_flags: Mapping[str, bool], redacted_text: str) -> bool:
    """R4b's input: the message points somewhere outside the group — a link, phone, mention or
    forward entity, or a redacted link, number, email or handle in the words the model read."""
    if any(entity_flags.get(flag, False) for flag in _CONTACT_FLAGS):
        return True
    return any(placeholder in redacted_text for placeholder in CONTACT_PLACEHOLDERS)


def quantise(confidence: float) -> Decimal:
    """Three places, half-up (D-TG-135) — the value routed and stored, never the model's raw
    float."""
    return Decimal(str(confidence)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def route_prediction(
    prediction: Prediction,
    *,
    floor: Decimal | None,
    threshold: Decimal | None,
    path: str,
    has_contact_signal: bool,
) -> tuple[str, str | None]:
    """`(route, route_reason)`, R1-R6 top to bottom, first match wins (D-TG-142). `floor` and
    `threshold` are ignored on the catch-up path (R1) — the operator's command passes thresholds
    that are never in force, so `None` there is deliberate (`ck_classification_thresholds`).

    R4b (2026-10-18): a SPAM_OR_AD prediction with no outside-contact signal is listed, never
    opened — on day one three student requests were opened as adverts at 0.95 with none."""
    if path == "catch_up":
        return "measurement_only", None
    assert floor is not None and threshold is not None
    if prediction.confidence < floor:
        return "review", None
    if not is_consistent(prediction):
        return "possible_violation", "inconsistent"
    if not prediction.needs_moderation:
        return "none", None
    if prediction.category == "SPAM_OR_AD" and not has_contact_signal:
        return "possible_violation", "no_contact_signal"
    if prediction.confidence >= threshold:
        return "incident", None
    return "possible_violation", "uncertain"


def within_attention_window(
    *, recorded_at: datetime, opened_at: datetime, enabled_from: datetime, max_age_s: int
) -> bool:
    """TG-M5.1's gate, the timing side (contract G5-G6): the prediction was recorded at or after
    `MODERATION_AI_ATTENTION_FROM` (G5 — switching on never reaches back), and before the item it
    would open is `MODERATION_ITEM_MAX_AGE_S` old (G6 — never an item born expired). Both are
    stored instants compared with each other — no clock is read here."""
    return recorded_at >= enabled_from and recorded_at - opened_at < timedelta(seconds=max_age_s)
