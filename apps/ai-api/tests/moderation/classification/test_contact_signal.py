"""The advert guard (R4b), pure (`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md`
Step 1). A SPAM_OR_AD prediction opens an incident only when the message carries a structured
outside-contact signal; without one it is listed on Possible Violations (`no_contact_signal`).
Day one in production: three student requests ("who has collections…", "anyone know a group…")
were opened as adverts with no link, phone, handle or forward at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.application.moderation.text import normalize, redact
from app.domain.moderation.classification import (
    CONTACT_PLACEHOLDERS,
    Prediction,
    has_contact_signal,
    route_prediction,
)

_FLOOR = Decimal("0.600")
_THRESHOLD = Decimal("0.850")
_NO_FLAGS = {"has_url": False, "has_phone": False, "has_mention": False, "forwarded": False}


def _prediction(category: str = "SPAM_OR_AD", severity: str = "medium") -> Prediction:
    return Prediction(
        category=category,
        needs_response=False,
        needs_moderation=True,
        severity=severity,
        confidence=Decimal("0.950"),
    )


# --- has_contact_signal ------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["has_url", "has_phone", "has_mention", "forwarded"])
def test_each_entity_flag_is_a_signal(flag: str) -> None:
    flags = {**_NO_FLAGS, flag: True}
    assert has_contact_signal(entity_flags=flags, redacted_text="نص عادي") is True


@pytest.mark.parametrize(
    "raw",
    [
        "سجلوا من هنا https://example.com/x",
        "تواصل على 0551234567",
        "راسلني @some_seller",
        "ايميلي seller@example.com",
    ],
)
def test_each_redaction_placeholder_is_a_signal(raw: str) -> None:
    redacted_text = redact(normalize(raw))
    assert has_contact_signal(entity_flags=_NO_FLAGS, redacted_text=redacted_text) is True


def test_the_placeholders_are_exactly_what_the_redactor_writes() -> None:
    redacted_text = redact("https://a.example b@example.com @handle_x 0551234567")
    assert len(CONTACT_PLACEHOLDERS) == 4
    assert all(placeholder in redacted_text for placeholder in CONTACT_PLACEHOLDERS)


@pytest.mark.parametrize(
    "raw",
    [
        # The three day-one false incidents (operator-supplied examples).
        "الله يجزاكم خير الى عندها تجميعات. رياض اطفال. الرخصه المهنيه",
        "يخوان احد يعرف قروب رخصة تربية اسلامية؟",
        "احتاج الى تجمعات تربية خاصة فكري او اعاقة فكرية",
    ],
)
def test_a_plain_request_carries_no_signal(raw: str) -> None:
    redacted_text = redact(normalize(raw))
    assert has_contact_signal(entity_flags=_NO_FLAGS, redacted_text=redacted_text) is False


def test_missing_flags_read_as_false() -> None:
    assert has_contact_signal(entity_flags={}, redacted_text="نص") is False


# --- R4b: route_prediction ---------------------------------------------------------------------


def test_r4b_advert_without_a_signal_is_listed_not_opened() -> None:
    assert route_prediction(
        _prediction(),
        floor=_FLOOR,
        threshold=_THRESHOLD,
        path="live",
        has_contact_signal=False,
    ) == ("possible_violation", "no_contact_signal")


def test_r4b_advert_with_a_signal_still_opens() -> None:
    assert route_prediction(
        _prediction(),
        floor=_FLOOR,
        threshold=_THRESHOLD,
        path="live",
        has_contact_signal=True,
    ) == ("incident", None)


def test_r4b_leaves_abuse_unchanged() -> None:
    assert route_prediction(
        _prediction(category="ABUSE"),
        floor=_FLOOR,
        threshold=_THRESHOLD,
        path="live",
        has_contact_signal=False,
    ) == ("incident", None)


def test_r4b_comes_after_the_floor_and_consistency_rules() -> None:
    low = Prediction(
        category="SPAM_OR_AD",
        needs_response=False,
        needs_moderation=True,
        severity="medium",
        confidence=Decimal("0.300"),
    )
    assert route_prediction(
        low, floor=_FLOOR, threshold=_THRESHOLD, path="live", has_contact_signal=False
    ) == ("review", None)
    inconsistent = _prediction(severity="none")
    assert route_prediction(
        inconsistent, floor=_FLOOR, threshold=_THRESHOLD, path="live", has_contact_signal=False
    ) == ("possible_violation", "inconsistent")


def test_r4b_never_applies_on_catch_up() -> None:
    assert route_prediction(
        _prediction(), floor=None, threshold=None, path="catch_up", has_contact_signal=False
    ) == ("measurement_only", None)
