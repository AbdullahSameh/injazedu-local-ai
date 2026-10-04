"""AI classification — eligibility, consistency and routing
(`contracts/classification-pipeline.md` §3, §6; `data-model.md` §2, tasks.md T018).

Pure: no I/O, no clock, no session, no import outside the standard library and
`app.domain.moderation.attention` (for the one shared acknowledgement matcher, E8). This is the
**only** definition of eligibility and routing (pipeline contract N7), and — since TG-M5.1 — of
whether a prediction proposes a question item (`specs/009-tg-m5-1-ai-attention/contracts/
attention-opening.md` G1-G6): the classifier and `open_item` call these functions directly, the
panel reads their stored outputs, and no test helper recomputes an expected route, eligibility or
proposal — it calls the function or asserts the stored row.
"""

from __future__ import annotations

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

# TG-M5.1 (attention-opening contract G4, D-TG-165): both instructions say needs_response is "Always
# false for SPAM_OR_AD, ABUSE and CHITCHAT" — a true value on one of these contradicts itself, the
# question-side counterpart of R8's two-way consistency.
NO_RESPONSE_CATEGORIES: frozenset[str] = frozenset({"SPAM_OR_AD", "ABUSE", "CHITCHAT"})


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
) -> tuple[str, str | None]:
    """`(route, route_reason)`, R1-R6 top to bottom, first match wins (D-TG-142). `floor` and
    `threshold` are ignored on the catch-up path (R1) — the operator's command passes thresholds
    that are never in force, so `None` there is deliberate (`ck_classification_thresholds`)."""
    if path == "catch_up":
        return "measurement_only", None
    assert floor is not None and threshold is not None
    if prediction.confidence < floor:
        return "review", None
    if not is_consistent(prediction):
        return "possible_violation", "inconsistent"
    if not prediction.needs_moderation:
        return "none", None
    if prediction.confidence >= threshold:
        return "incident", None
    return "possible_violation", "uncertain"


def proposes_attention(*, path: str, route: str, needs_response: bool, category: str) -> bool:
    """TG-M5.1's gate, the prediction's own side (attention-opening contract G1-G4): whether a
    stored prediction proposes that its message needs a moderator's answer. Live only (G2 — catch-up
    is measurement only); never below the floor (G3 — FR-030, read from the stored route, never
    recomputed); and never on a category the instruction says needs no answer (G4). The violation
    side's route is otherwise irrelevant (decision 1: both units of work, independently)."""
    return (
        path == "live"
        and route != "review"
        and needs_response
        and category not in NO_RESPONSE_CATEGORIES
    )


def within_attention_window(
    *, recorded_at: datetime, opened_at: datetime, enabled_from: datetime, max_age_s: int
) -> bool:
    """TG-M5.1's gate, the timing side (contract G5-G6): the prediction was recorded at or after
    `MODERATION_AI_ATTENTION_FROM` (G5 — switching on never reaches back), and before the item it
    would open is `MODERATION_ITEM_MAX_AGE_S` old (G6 — never an item born expired). Both are
    stored instants compared with each other — no clock is read here."""
    return recorded_at >= enabled_from and recorded_at - opened_at < timedelta(seconds=max_age_s)
