"""The attention judgement — its intents, the one derivation of needs-response, eligibility, and
the opening gate's judgement side (TG-M5.3, `specs/011-tg-m5-3-attention-judgement/contracts/
attention-judgement.md` §2, §4, §6; `data-model.md` §9).

Pure: no I/O, no clock, no session, no import outside the standard library,
`app.domain.moderation.attention` (the rule set's own `evaluate`, for AE2) and
`app.domain.moderation.classification` (`MessageFacts` and `eligibility`, for AE1).

**The single-derivation rule (S2, N2).** `needs_response_for(intent)` — `intent == "asking"` — is
the only definition of whether a judged message needs the team. The judgement stores its result
once, at insert, and nothing recomputes it: no CHECK, PHP, SQL, prompt or test helper restates the
mapping. The same holds for eligibility (AE1–AE2), the gate (A1–A2) and the veto (V): the judge,
`open_item` and the qualification call these functions directly.
"""

from __future__ import annotations

from app.domain.moderation.attention import evaluate
from app.domain.moderation.classification import MessageFacts, eligibility

# S3: the closed answer, in the contract's order. `ck_attention_judgement_intent` holds the
# same six.
INTENTS: tuple[str, ...] = ("asking", "discussion", "informing", "social", "offering", "other")

# V: the categories whose current classification keeps a member from opening a question item.
# CHITCHAT is never vetoed, and a member with no classification is not either.
_VETO_CATEGORIES: frozenset[str] = frozenset({"SPAM_OR_AD", "ABUSE"})


def needs_response_for(intent: str) -> bool:
    """S2: whether a message of this intent needs an answer, action, clarification or decision
    from the team — only `asking` does. The single derivation."""
    return intent == "asking"


def attention_exclusion(facts: MessageFacts) -> str | None:
    """AE1–AE2: the reason a message is not judged, or `None` when it is.

    AE1 is the classification's own eligibility, E1–E8, first match wins. AE2 follows it: a
    message whose own first-posted, normalised words open rule set v1 is excluded as
    `rule_opens`, since every burst containing it opens by rule and its judgement could never be
    read (D-TG-186). `facts.text` is already normalised by `load_facts`; only the words are
    evaluated — no mention or reply signal, which belongs to a burst, not a message."""
    reason = eligibility(facts)
    if reason is not None:
        return reason
    if evaluate([facts.text]):
        return "rule_opens"
    return None


def judgement_proposes(*, path: str, needs_response: bool) -> bool:
    """A1–A2: whether a stored judgement proposes that its message opens a question item. Live
    only (catch-up opens nothing), and only when its stored `needs_response` is true."""
    return path == "live" and needs_response


def vetoed(category: str | None) -> bool:
    """V: whether a burst member's current classification keeps it from opening — an advert or
    abuse. `None` (no classification) never vetoes: the two judgements are independent, and a
    missing classification is not evidence of an advert."""
    return category in _VETO_CATEGORIES
