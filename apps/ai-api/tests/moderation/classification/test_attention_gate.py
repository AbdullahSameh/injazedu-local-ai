"""The attention gate, pure (TG-M5.3, `specs/011-tg-m5-3-attention-judgement/contracts/
attention-judgement.md` §6 A1-A2, V, G5-G6; `tasks.md` T040).

Calls `judgement_proposes()`, `vetoed()` and `within_attention_window()` directly with fixed, named
cases — never a computed expectation (N2): each case states the outcome the contract names for it.
The judgement's own side (A1-A2) and the veto (V) replace TG-M5.1's G1-G4, whose
`proposes_attention` read the classification and is removed (D-TG-191). The timing side, G5-G6,
is TG-M5.1's and unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.domain.moderation.attention_judgement import judgement_proposes, vetoed
from app.domain.moderation.classification import within_attention_window

_ENABLED_FROM = datetime(2026, 10, 3, 9, 0, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)
_MAX_AGE_S = 86400


# --- A1-A2: the judgement's own side -------------------------------------------------------------


def test_a1_a2_a_live_judgement_needing_a_response_proposes() -> None:
    assert judgement_proposes(path="live", needs_response=True) is True


def test_a2_a_live_judgement_needing_no_response_never_proposes() -> None:
    assert judgement_proposes(path="live", needs_response=False) is False


@pytest.mark.parametrize("needs_response", [True, False])
def test_a1_a_catch_up_judgement_never_proposes(needs_response: bool) -> None:
    # Catch-up is measurement only (§9 L1, N3).
    assert judgement_proposes(path="catch_up", needs_response=needs_response) is False


# --- V: the member's current classification ------------------------------------------------------


@pytest.mark.parametrize("category", ["SPAM_OR_AD", "ABUSE"])
def test_v_an_advert_or_abuse_classification_vetoes(category: str) -> None:
    assert vetoed(category) is True


@pytest.mark.parametrize(
    "category", ["QUESTION_COURSE", "QUESTION_ACCESS", "COMPLAINT", "CHITCHAT", "OTHER"]
)
def test_v_every_other_category_never_vetoes(category: str) -> None:
    # CHITCHAT included: TG-M5.1's G4 is gone, and the judgement alone decides needs-response.
    assert vetoed(category) is False


def test_v_a_missing_classification_never_vetoes() -> None:
    # The two judgements are independent; a missing classification is not evidence of an advert.
    assert vetoed(None) is False


# --- G5-G6: when the judgement was recorded ------------------------------------------------------


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
    # E3: an edited burst opens at `edited_at`, which can follow the judgement of its first words.
    assert _within(recorded_at=_OPENED_AT - timedelta(seconds=30)) is True


def test_g6_a_prediction_just_under_max_age_late_counts() -> None:
    assert _within(recorded_at=_OPENED_AT + timedelta(seconds=_MAX_AGE_S - 1)) is True


def test_g6_a_prediction_exactly_max_age_late_never_counts() -> None:
    # Decision 2: the item would be born expired (`opened_at < now() - max_age` at the next tick).
    assert _within(recorded_at=_OPENED_AT + timedelta(seconds=_MAX_AGE_S)) is False
