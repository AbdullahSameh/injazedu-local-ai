"""Routing (R1-R6), pure (T020, `contracts/classification-pipeline.md` §6, FR-026..FR-031,
SC-008, SC-009). Calls `route_prediction()` directly with fixed, named cases — never a computed
expectation (pipeline N7): each case states the route the contract's own table names for it.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.moderation.classification import Prediction, quantise, route_prediction

_FLOOR = Decimal("0.600")
_THRESHOLD = Decimal("0.850")


def _prediction(
    *,
    category: str = "SPAM_OR_AD",
    needs_response: bool = False,
    needs_moderation: bool = True,
    severity: str = "high",
    confidence: str = "0.900",
) -> Prediction:
    return Prediction(
        category=category,
        needs_response=needs_response,
        needs_moderation=needs_moderation,
        severity=severity,
        confidence=Decimal(confidence),
    )


# --- R1: catch-up is measurement only, whatever the values ------------------------------------


def test_r1_catch_up_routes_measurement_only_for_a_confident_consistent_violation() -> None:
    prediction = _prediction(confidence="1.000")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="catch_up") == (
        "measurement_only",
        None,
    )


def test_r1_catch_up_routes_measurement_only_for_an_inconsistent_prediction() -> None:
    prediction = _prediction(category="CHITCHAT", needs_moderation=True, confidence="1.000")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="catch_up") == (
        "measurement_only",
        None,
    )


def test_r1_catch_up_ignores_the_floor_and_threshold() -> None:
    prediction = _prediction(confidence="0.001")
    assert route_prediction(prediction, floor=None, threshold=None, path="catch_up") == (
        "measurement_only",
        None,
    )


# --- R2: below the floor -----------------------------------------------------------------------


def test_r2_below_floor_routes_review_even_for_a_consistent_violation() -> None:
    prediction = _prediction(confidence="0.599")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "review",
        None,
    )


def test_r9_exactly_at_the_floor_is_not_below_it() -> None:
    """R9: `0.600 == floor` proceeds past R2 — here to R6, since it is below the threshold."""
    prediction = _prediction(confidence="0.600")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "uncertain",
    )


# --- R3: inconsistent, both directions (operator item 4) -----------------------------------------


def test_r3_chitchat_marked_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="CHITCHAT", needs_moderation=True, severity="high", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


def test_r3_question_marked_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="QUESTION_COURSE", needs_moderation=True, severity="medium", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


def test_r3_complaint_marked_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="COMPLAINT", needs_moderation=True, severity="low", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


def test_r3_severity_none_marked_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="SPAM_OR_AD", needs_moderation=True, severity="none", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


def test_r3_spam_marked_not_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="SPAM_OR_AD", needs_moderation=False, severity="none", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


def test_r3_abuse_marked_not_needing_moderation_is_inconsistent() -> None:
    prediction = _prediction(
        category="ABUSE", needs_moderation=False, severity="none", confidence="0.900"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "inconsistent",
    )


# --- R4: needs no moderation, consistent --------------------------------------------------------


def test_r4_consistent_no_moderation_needed_routes_none_at_any_confidence() -> None:
    prediction = _prediction(
        category="CHITCHAT", needs_moderation=False, severity="none", confidence="1.000"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "none",
        None,
    )


def test_r4_other_marked_not_needing_moderation_routes_none() -> None:
    prediction = _prediction(
        category="OTHER", needs_moderation=False, severity="none", confidence="0.999"
    )
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "none",
        None,
    )


# --- R5 / R9: at or above the threshold opens an incident ---------------------------------------


def test_r5_exactly_at_the_threshold_opens() -> None:
    prediction = _prediction(confidence="0.850")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "incident",
        None,
    )


def test_r5_raw_confidence_that_quantises_to_the_threshold_opens() -> None:
    quantised = quantise(0.8495)
    assert quantised == Decimal("0.850")
    prediction = _prediction(confidence=str(quantised))
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "incident",
        None,
    )


def test_r5_above_the_threshold_opens() -> None:
    prediction = _prediction(confidence="1.000")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "incident",
        None,
    )


# --- R6: consistent, needs moderation, below the threshold ---------------------------------------


def test_r6_below_threshold_consistent_violation_is_a_possible_violation() -> None:
    prediction = _prediction(confidence="0.720")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "uncertain",
    )


def test_r6_just_below_the_threshold_is_a_possible_violation() -> None:
    prediction = _prediction(confidence="0.849")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "possible_violation",
        "uncertain",
    )


# --- SC-009: the thresholds passed in are what decide, not a stored default ----------------------


def test_the_same_prediction_routes_differently_under_different_thresholds() -> None:
    prediction = _prediction(confidence="0.850")
    assert route_prediction(prediction, floor=_FLOOR, threshold=_THRESHOLD, path="live") == (
        "incident",
        None,
    )
    assert route_prediction(
        prediction, floor=Decimal("0.600"), threshold=Decimal("1.000"), path="live"
    ) == ("possible_violation", "uncertain")
