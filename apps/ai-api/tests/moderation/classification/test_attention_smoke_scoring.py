"""The attention benchmark's scoring (`smoke_attention.py` and the attention suite's set block,
`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` §4, D-TG-195), over the rows
`judge_attention_line` returns: the judgement's own agreement with a human label — needs-response
derived from the intent, misses (false negatives) and false alarms (false positives), each with
line numbers, and the intent in place of TG-M5.1's category, confidence and route — and,
separately, who would open an item once the rule set has had its first word: the rules (no call),
the model, nobody, or nobody because the message is never judged. A model-opened item on an
expected-false line is the new moderator work, and is tallied on its own. Pure — no model, no
database.
"""

from __future__ import annotations

from app.scripts.qualification.attention import AttentionRow, format_summary, summarise


def _row(
    line: int,
    expected: bool,
    *,
    intent: str | None = None,
    rule_opens: bool = False,
    excluded: str | None = None,
    error: str | None = None,
    expected_intent: str | None = None,
) -> AttentionRow:
    return AttentionRow(
        line=line,
        expected_needs_response=expected,
        rule_opens=rule_opens,
        expected_intent=expected_intent,
        excluded=excluded,
        intent=intent,
        error=error,
    )


_ROWS = [
    # an implicit question the rules miss and the model catches
    _row(1, True, intent="asking", expected_intent="asking"),
    # an explicit question the rules open — no call is made, so there is no intent
    _row(2, True, rule_opens=True, expected_intent="asking"),
    # an implicit question the model reads as peer discussion — nobody opens
    _row(3, True, intent="discussion"),
    # a near-miss statement the model wrongly calls asking — new moderator work
    _row(4, False, intent="asking", expected_intent="informing"),
    # a near-miss the model leaves alone
    _row(5, False, intent="informing", expected_intent="informing"),
    # an acknowledgement, never judged — correct for an expected-false label
    _row(6, False, excluded="acknowledgement"),
    # a failed call — an error, never an answer
    _row(7, True, error="ModelTimeoutError"),
    # an advert-shaped offer the model reads as an offer — nobody opens
    _row(8, False, intent="offering", expected_intent="offering"),
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
    assert summary.judged == 5  # not the rule-opened, excluded or failed lines
    assert summary.needs_response_agreed == 3  # 1, 5 and 8
    assert summary.false_negatives == (3,)
    assert summary.false_positives == (4,)
    assert summary.errors == (7,)
    assert summary.excluded == (6,)
    assert summary.matched == 5  # 1, 2 (by rule), 5, 6 (never judged) and 8


def test_the_intent_takes_the_place_of_category_confidence_and_route() -> None:
    summary = summarise(_ROWS)

    assert summary.intent_exact == (3, 4)  # 1, 5 and 8 of the four answered lines carrying one
    assert summary.intents == {
        "asking": 2,
        "discussion": 1,
        "informing": 1,
        "social": 0,
        "offering": 1,
        "other": 0,
    }


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


def test_format_summary_prints_counts_intents_and_line_numbers_never_text() -> None:
    lines = format_summary(summarise(_ROWS))

    assert lines[0] == "5/8 matched"
    assert "needs_response agreed: 3/5 answered" in lines
    assert "false negatives (expected true, predicted false): 1 (#3)" in lines
    assert "false positives (expected false, predicted true): 1 (#4)" in lines
    assert "model-opened on expected-false (new moderator work): 1 (#4)" in lines
    assert "intent exact: 3/4" in lines
    assert "intents: asking=2 discussion=1 informing=1 social=0 offering=1 other=0" in lines
    assert "opener, expected true: rule=1 model=1 none=1 excluded=0 error=1" in lines
    assert "opener, expected false: rule=0 model=1 none=2 excluded=1 error=0" in lines
    assert not [line for line in lines if "category" in line or "confidence" in line]
