"""TG-M5.1's gate, pure (`specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md` G1-G6).
Calls `proposes_attention()` and `within_attention_window()` directly with fixed, named cases —
never a computed expectation (pipeline N7): each case states the outcome the contract names for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.domain.moderation.classification import (
    CATEGORIES,
    NO_RESPONSE_CATEGORIES,
    proposes_attention,
    within_attention_window,
)

_ENABLED_FROM = datetime(2026, 10, 3, 9, 0, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)
_MAX_AGE_S = 86400


def _proposes(
    *,
    path: str = "live",
    route: str = "none",
    needs_response: bool = True,
    category: str = "QUESTION_COURSE",
) -> bool:
    return proposes_attention(
        path=path, route=route, needs_response=needs_response, category=category
    )


# --- G1-G4: the prediction's own side ------------------------------------------------------------


def test_g1_a_live_coherent_needs_response_prediction_proposes() -> None:
    assert _proposes() is True


@pytest.mark.parametrize("category", ["QUESTION_COURSE", "QUESTION_ACCESS", "COMPLAINT", "OTHER"])
def test_g1_every_category_the_instruction_lets_need_a_response_proposes(category: str) -> None:
    assert _proposes(category=category) is True


def test_g1_needs_response_false_never_proposes() -> None:
    assert _proposes(needs_response=False) is False


def test_g2_a_catch_up_prediction_never_proposes() -> None:
    # Catch-up is measurement only (pipeline C2): its route is always `measurement_only`.
    assert _proposes(path="catch_up", route="measurement_only") is False


def test_g3_a_below_floor_prediction_never_proposes() -> None:
    # FR-030: below the floor nothing opens — the stored route says so, never recomputed.
    assert _proposes(route="review") is False


@pytest.mark.parametrize("route", ["none", "incident", "possible_violation"])
def test_g3_every_at_or_above_floor_live_route_proposes(route: str) -> None:
    # Decision 1 (dual-purpose, 2026-10-03): the violation side never blocks the question side.
    assert _proposes(route=route) is True


@pytest.mark.parametrize("category", ["SPAM_OR_AD", "ABUSE", "CHITCHAT"])
def test_g4_needs_response_on_a_category_the_instruction_says_never_needs_one_is_ignored(
    category: str,
) -> None:
    assert _proposes(category=category) is False


def test_g4_no_response_categories_are_exactly_the_instructions_three() -> None:
    assert NO_RESPONSE_CATEGORIES == frozenset({"SPAM_OR_AD", "ABUSE", "CHITCHAT"})
    assert NO_RESPONSE_CATEGORIES <= frozenset(CATEGORIES)


# --- G5-G6: when the prediction was recorded ----------------------------------------------------


def _within(*, recorded_at: datetime, opened_at: datetime = _OPENED_AT) -> bool:
    return within_attention_window(
        recorded_at=recorded_at,
        opened_at=opened_at,
        enabled_from=_ENABLED_FROM,
        max_age_s=_MAX_AGE_S,
    )


def test_g5_a_prediction_recorded_before_the_switch_never_counts() -> None:
    assert _within(recorded_at=_ENABLED_FROM - timedelta(seconds=1)) is False


def test_g5_a_prediction_recorded_exactly_at_the_switch_counts() -> None:
    assert _within(recorded_at=_ENABLED_FROM, opened_at=_ENABLED_FROM) is True


def test_g6_a_prediction_one_second_after_the_question_counts() -> None:
    assert _within(recorded_at=_OPENED_AT + timedelta(seconds=1)) is True


def test_g6_a_prediction_recorded_before_an_edit_anchored_opened_at_counts() -> None:
    # E3: an edited burst opens at `edited_at`, which can follow the prediction of its first words.
    assert _within(recorded_at=_OPENED_AT - timedelta(seconds=30)) is True


def test_g6_a_prediction_just_under_max_age_late_counts() -> None:
    assert _within(recorded_at=_OPENED_AT + timedelta(seconds=_MAX_AGE_S - 1)) is True


def test_g6_a_prediction_exactly_max_age_late_never_counts() -> None:
    # Decision 2: the item would be born expired (`opened_at < now() - max_age` at the next tick).
    assert _within(recorded_at=_OPENED_AT + timedelta(seconds=_MAX_AGE_S)) is False
