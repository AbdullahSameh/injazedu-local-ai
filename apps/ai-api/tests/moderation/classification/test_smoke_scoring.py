"""D-TG-162 — the smoke test's summary separates what "n/total matched" conflates: category
agreement, needs-moderation agreement, missed violations (false negatives) and false alarms (false
positives), each with its fixture line numbers, plus the live routes taken by fixtures labelled as
violations and as legitimate. A failed call is an error, never a prediction. Pure — no model, no
database (`contracts/classification-pipeline.md` §10 C4).
"""

from __future__ import annotations

from app.scripts.smoke_moderation import SmokeRow, format_summary, summarise


def _row(
    line: int,
    expected: tuple[str, bool],
    predicted: tuple[str, bool] | None,
    route: str | None = None,
    error: str | None = None,
) -> SmokeRow:
    return SmokeRow(
        line=line,
        expected_category=expected[0],
        expected_needs_moderation=expected[1],
        predicted_category=predicted[0] if predicted else None,
        predicted_needs_moderation=predicted[1] if predicted else None,
        route=route,
        error=error,
    )


_ROWS = [
    # an exact match
    _row(1, ("SPAM_OR_AD", True), ("SPAM_OR_AD", True), "incident"),
    # an adjacent category, moderation decision right — a mismatch, but not a miss
    _row(2, ("ABUSE", True), ("COMPLAINT", True), "incident"),
    # a missed violation, as the real benchmark's medical-excuse adverts were
    _row(3, ("SPAM_OR_AD", True), ("CHITCHAT", False), "none"),
    # a missed violation the routing still lists (an advert marked needs-moderation false)
    _row(4, ("SPAM_OR_AD", True), ("SPAM_OR_AD", False), "possible_violation/inconsistent"),
    # a false alarm on a legitimate question
    _row(5, ("QUESTION_COURSE", False), ("SPAM_OR_AD", True), "incident"),
    # legitimate and agreed
    _row(6, ("CHITCHAT", False), ("CHITCHAT", False), "none"),
    # legitimate, adjacent category
    _row(7, ("OTHER", False), ("CHITCHAT", False), "none"),
    # a failed call
    _row(8, ("SPAM_OR_AD", True), None, error="ModelTruncatedError"),
]


def test_summary_counts_each_agreement_separately() -> None:
    summary = summarise(_ROWS)

    assert summary.total == 8
    assert summary.matched == 2
    assert summary.category_exact == 3
    assert summary.needs_moderation_agreed == 4
    assert summary.false_negatives == (3, 4)
    assert summary.false_positives == (5,)
    assert summary.errors == (8,)


def test_routes_are_tallied_by_label_and_the_reason_is_dropped() -> None:
    summary = summarise(_ROWS)

    assert summary.violation_routes == {
        "incident": 2,
        "possible_violation": 1,
        "review": 0,
        "none": 1,
    }
    assert summary.legitimate_routes == {
        "incident": 1,
        "possible_violation": 0,
        "review": 0,
        "none": 2,
    }


def test_the_printed_block_keeps_the_matched_line_first() -> None:
    lines = format_summary(summarise(_ROWS))

    assert lines == [
        "2/8 matched",
        "category exact: 3/8",
        "needs_moderation agreed: 4/8",
        "false negatives (expected true, predicted false): 2 (#3, #4)",
        "false positives (expected false, predicted true): 1 (#5)",
        "errors: 1 (#8)",
        "routes, violations: incident=2 possible_violation=1 review=0 none=1",
        "routes, legitimate: incident=1 possible_violation=0 review=0 none=2",
    ]


def test_an_all_correct_run_reports_no_misses() -> None:
    rows = [
        _row(1, ("SPAM_OR_AD", True), ("SPAM_OR_AD", True), "incident"),
        _row(2, ("CHITCHAT", False), ("CHITCHAT", False), "none"),
    ]

    summary = summarise(rows)

    assert summary.matched == summary.total == 2
    assert format_summary(summary)[3:6] == [
        "false negatives (expected true, predicted false): 0",
        "false positives (expected false, predicted true): 0",
        "errors: 0",
    ]
