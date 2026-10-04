"""TG-M5.1's benchmark scoring (`smoke_attention.py`, attention-opening contract B1-B4): the model's
needs-response judgement against a human label — agreement, misses (false negatives) and false
alarms (false positives), each with fixture line numbers — and, separately, who would open an item
for each fixture once the rule set has had its first word: the rules, the model, nobody, or nobody
because the message is never classified. A model-opened item on an expected-false fixture is the
new moderator work this milestone risks, and is tallied on its own. Pure — no model, no database.
"""

from __future__ import annotations

from app.scripts.smoke_attention import AttentionRow, format_summary, summarise


def _row(
    line: int,
    expected: bool,
    *,
    predicted: bool | None = None,
    rule_opens: bool = False,
    model_proposes: bool | None = None,
    excluded: str | None = None,
    error: str | None = None,
    expected_category: str | None = None,
    predicted_category: str | None = None,
) -> AttentionRow:
    return AttentionRow(
        line=line,
        expected_needs_response=expected,
        expected_category=expected_category,
        rule_opens=rule_opens,
        excluded=excluded,
        predicted_needs_response=predicted,
        predicted_category=predicted_category,
        route="none" if predicted is not None else None,
        model_proposes=model_proposes,
        error=error,
    )


_ROWS = [
    # an implicit question the rules miss and the model catches
    _row(
        1,
        True,
        predicted=True,
        model_proposes=True,
        expected_category="QUESTION_COURSE",
        predicted_category="QUESTION_COURSE",
    ),
    # an explicit question the rules open whatever the model says
    _row(
        2,
        True,
        predicted=False,
        rule_opens=True,
        model_proposes=False,
        expected_category="QUESTION_COURSE",
        predicted_category="CHITCHAT",
    ),
    # an implicit question the model misses — nobody opens
    _row(3, True, predicted=False, model_proposes=False),
    # a near-miss statement the model wrongly flags — new moderator work
    _row(4, False, predicted=True, model_proposes=True),
    # a near-miss the model leaves alone
    _row(5, False, predicted=False, model_proposes=False),
    # an acknowledgement, never classified — correct for an expected-false label
    _row(6, False, excluded="acknowledgement"),
    # a failed call — an error, never a prediction
    _row(7, True, error="ModelTimeoutError"),
    # needs_response true on a category the gate refuses — the model never opens it
    _row(8, False, predicted=True, model_proposes=False, predicted_category="SPAM_OR_AD"),
]


def test_opener_is_the_rule_set_first_then_the_model_then_nobody() -> None:
    assert [row.opener for row in _ROWS] == [
        "model",
        "rule",
        "none",
        "model",
        "none",
        "excluded",
        "error",
        "none",
    ]


def test_summary_separates_agreement_misses_and_false_alarms() -> None:
    summary = summarise(_ROWS)

    assert summary.total == 8
    assert summary.scored == 6
    assert summary.needs_response_agreed == 2
    assert summary.false_negatives == (2, 3)
    assert summary.false_positives == (4, 8)
    assert summary.errors == (7,)
    assert summary.excluded == (6,)
    assert summary.category_exact == (1, 2)  # one of the two fixtures carrying a category
    assert summary.matched == 3  # 1 and 5 agree; 6 is correctly never classified


def test_opener_tallies_split_by_label_and_the_new_work_is_named() -> None:
    summary = summarise(_ROWS)

    assert summary.openers_expected_true == {
        "rule": 1,
        "model": 1,
        "none": 1,
        "excluded": 0,
        "error": 1,
    }
    assert summary.openers_expected_false == {
        "rule": 0,
        "model": 1,
        "none": 2,
        "excluded": 1,
        "error": 0,
    }
    assert summary.model_opened_on_expected_false == (4,)


def test_format_summary_prints_counts_and_line_numbers_never_text() -> None:
    lines = format_summary(summarise(_ROWS))

    assert lines[0] == "3/8 matched"
    assert "needs_response agreed: 2/6" in lines
    assert "false negatives (expected true, predicted false): 2 (#2, #3)" in lines
    assert "false positives (expected false, predicted true): 2 (#4, #8)" in lines
    assert "model-opened on expected-false (new moderator work): 1 (#4)" in lines
    assert "opener, expected true: rule=1 model=1 none=1 excluded=0 error=1" in lines
    assert "opener, expected false: rule=0 model=1 none=2 excluded=1 error=0" in lines
