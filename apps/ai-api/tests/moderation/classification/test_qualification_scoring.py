"""TG-M5.2's qualification: scoring S1-S6, the gate Q1-Q12 and the verdict
(`specs/010-tg-m5-2-classify-v3/contracts/qualification.md` §3-§5). Pure — scripted rows, no model,
no database.

- An attention line is scored by its label class: a clear negative is model-opened when the model is
  its opener; a clear positive is missed when nobody opens it (`none` or `excluded`); an ambiguous
  line is reported, never gated.
- A moderation line is scored exactly as the smoke scores it, with tracked lines taken out of the
  gated counts and reported on their own line.
- A gate is `FAIL` on the evidence that ran, `NOT RUN` when a set it needs is missing, `PASS`
  otherwise. Any `FAIL` makes the pair `NOT QUALIFIED`; otherwise any `NOT RUN` makes it
  `INCOMPLETE`. `--repeat 1` is never `QUALIFIED`.
- The printed report carries counts, set names and line numbers — never a fixture's text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.scripts.qualify_moderation import (
    ClassSplit,
    GateLine,
    SetResult,
    SetSpec,
    TrackedLine,
    compare_runs,
    evaluate_gate,
    exit_code_for,
    fixture_annotations,
    format_report,
    latency_percentiles,
    moderation_gated,
    split_by_label_class,
    tracked_lines,
    verdict,
)
from app.scripts.smoke_attention import AttentionRow
from app.scripts.smoke_moderation import SmokeRow

_SENTINEL = "SENTINEL-fixture-text-never-printed"


# --- row builders ------------------------------------------------------------------------------


def _att(
    line: int,
    expected: bool,
    *,
    rule: bool = False,
    proposes: bool = False,
    predicted: bool | None = None,
    excluded: str | None = None,
    error: str | None = None,
    category: str = "QUESTION_COURSE",
    route: str = "none",
) -> AttentionRow:
    scored = excluded is None and error is None
    return AttentionRow(
        line=line,
        expected_needs_response=expected,
        expected_category=None,
        rule_opens=rule,
        excluded=excluded,
        error=error,
        predicted_needs_response=(proposes if predicted is None else predicted) if scored else None,
        predicted_category=category if scored else None,
        predicted_needs_moderation=False if scored else None,
        confidence=0.95 if scored else None,
        route=route if scored else None,
        model_proposes=proposes if scored else None,
    )


def _mod(
    line: int,
    expected: bool,
    predicted: bool | None,
    *,
    category: str = "SPAM_OR_AD",
    route: str | None = None,
    error: str | None = None,
) -> SmokeRow:
    if error is not None:
        return SmokeRow(
            line=line, expected_category=category, expected_needs_moderation=expected, error=error
        )
    return SmokeRow(
        line=line,
        expected_category=category,
        expected_needs_moderation=expected,
        predicted_category=category,
        predicted_needs_moderation=predicted,
        predicted_needs_response=False,
        confidence=0.95,
        route=route or ("incident" if predicted else "none"),
    )


_ROLES_KINDS = {
    "tuning": "attention",
    "heldout": "attention",
    "fresh": "attention",
    "moderation-real": "moderation",
    "moderation-shipped": "moderation",
    "moderation-policy": "moderation",
}


def _spec(name: str, role: str, *, present: bool = True) -> SetSpec:
    return SetSpec(
        name=name, role=role, kind=_ROLES_KINDS[role], path=Path(name) if present else None
    )


def _result(
    name: str,
    role: str,
    rows: list[Any],
    *,
    runs: int = 2,
    run_two: list[Any] | None = None,
    latencies: tuple[int, ...] | None = None,
    label_classes: dict[int, str] | None = None,
    tracked: dict[int, str] | None = None,
) -> SetResult:
    second = run_two if run_two is not None else rows
    all_runs = (tuple(rows), tuple(second))[:runs]
    return SetResult(
        spec=_spec(name, role),
        runs=all_runs,
        latencies_ms=latencies if latencies is not None else tuple(1000 for _ in rows) * runs,
        label_classes=label_classes or {},
        tracked=tracked or {},
    )


def _missing(name: str, role: str) -> SetResult:
    return SetResult(spec=_spec(name, role, present=False))


def _heldout_rows(*, missed: int = 0, opened_negatives: int = 0, declined: int = 10) -> list[Any]:
    rows: list[Any] = [
        _att(n, True, proposes=n > missed) for n in range(1, declined + 1)
    ]  # rule-declined clear positives, the first `missed` of them missed
    rows += [_att(declined + 1, True, rule=True)]  # one the rules catch
    rows += [
        _att(declined + 1 + n, False, proposes=n <= opened_negatives) for n in range(1, 5)
    ]  # clear negatives, the first `opened_negatives` of them model-opened
    return rows


def _passing(**replace: SetResult) -> list[SetResult]:
    """A full, qualifying set of results, in the order the command reads them (§2). Any role
    can be replaced by name."""
    results = {
        "real": _result(
            "real-attention.jsonl",
            "tuning",
            [_att(1, True, proposes=True), _att(2, False), _att(3, True, proposes=False)],
            label_classes={1: "clear", 2: "clear", 3: "ambiguous"},
        ),
        "shipped": _result(
            "attention_smoke_fixtures.jsonl",
            "tuning",
            [_att(1, True, rule=True), _att(2, False, excluded="acknowledgement")],
            label_classes={1: "clear", 2: "clear"},
        ),
        "heldout": _result("attention_smoke_heldout_fixtures.jsonl", "heldout", _heldout_rows()),
        "fresh": _result(
            "fresh-attention.jsonl", "fresh", [_att(1, True, proposes=True), _att(2, False)]
        ),
        "mod_real": _result(
            "real-moderation.jsonl",
            "moderation-real",
            [_mod(1, True, False), _mod(2, False, False, category="QUESTION_COURSE")],
            tracked={1: "no-link-rule"},
        ),
        "mod_shipped": _result(
            "moderation_smoke_fixtures.jsonl",
            "moderation-shipped",
            [_mod(1, True, True), _mod(11, True, False, category="ABUSE")],
            tracked={11: "label-review"},
        ),
        "mod_policy": _result(
            "moderation_smoke_policy_fixtures.jsonl",
            "moderation-policy",
            [_mod(1, True, True), _mod(2, False, False, category="QUESTION_COURSE")],
        ),
    }
    results.update(replace)
    return list(results.values())


def _gate(gates: tuple[GateLine, ...], name: str) -> GateLine:
    [line] = [gate for gate in gates if gate.gate == name]
    return line


# --- S1: attention lines by label class ---------------------------------------------------------


def test_a_clear_positive_nobody_opens_is_missed_including_an_excluded_one() -> None:
    rows = [
        _att(1, True, proposes=True),  # model opens
        _att(2, True, rule=True),  # rules open
        _att(3, True, proposes=False),  # nobody — missed
        _att(4, True, excluded="acknowledgement"),  # never classified — missed
        _att(5, True, error="ModelTimeoutError"),  # an error, never scored as a miss (S4)
    ]

    split = split_by_label_class(rows, label_classes={}, tracked={})

    assert split.clear_positives == 5
    assert split.clear_positives_missed == (3, 4)


def test_a_clear_negative_is_counted_only_when_the_model_opens_it() -> None:
    rows = [
        _att(1, False, proposes=True),  # model opens — new moderator work
        _att(2, False, rule=True, proposes=True),  # the rules opened it first: not the model's
        _att(3, False),
        _att(4, False, excluded="acknowledgement"),
    ]

    split = split_by_label_class(rows, label_classes={}, tracked={})

    assert split.clear_negatives == 4
    assert split.clear_negatives_model_opened == (1,)


def test_rule_declined_clear_positives_are_counted_and_their_misses_named() -> None:
    rows = [
        _att(1, True, rule=True),
        _att(2, True, proposes=True),
        _att(3, True, proposes=False),
        _att(4, True, proposes=True),
    ]

    split = split_by_label_class(rows, label_classes={}, tracked={})

    assert split.rule_declined_positives == 3
    assert split.rule_declined_positives_missed == (3,)


def test_ambiguous_lines_are_reported_and_never_in_a_gated_count() -> None:
    rows = [
        _att(1, True, proposes=True),  # ambiguous, answered true, agrees
        _att(2, True, proposes=False),  # ambiguous, answered false — not a miss
        _att(3, True, excluded="acknowledgement"),  # ambiguous, never classified — not a miss
        _att(4, False, proposes=True),  # clear negative, model-opened
    ]
    classes = {1: "ambiguous", 2: "ambiguous", 3: "ambiguous", 4: "clear"}

    split = split_by_label_class(rows, label_classes=classes, tracked={})

    assert split == ClassSplit(
        clear_positives=0,
        clear_positives_missed=(),
        clear_negatives=1,
        clear_negatives_model_opened=(4,),
        rule_declined_positives=0,
        rule_declined_positives_missed=(),
        ambiguous=3,
        ambiguous_answered_true=(1,),
        ambiguous_agreed=1,
    )


def test_a_tracked_attention_line_is_out_of_every_split_count() -> None:
    rows = [_att(1, False, proposes=True), _att(2, True, proposes=False)]

    split = split_by_label_class(
        rows, label_classes={}, tracked={1: "label-review", 2: "label-review"}
    )

    assert (split.clear_negatives, split.clear_positives) == (0, 0)


# --- S2, S3: moderation lines and tracked lines -------------------------------------------------


def test_tracked_moderation_lines_leave_the_gated_counts() -> None:
    rows = [
        _mod(1, True, False),  # tracked miss
        _mod(2, True, False),  # untracked miss
        _mod(3, False, True, category="QUESTION_COURSE"),  # untracked false alarm, an incident
        _mod(4, False, True, category="QUESTION_COURSE"),  # tracked false alarm, an incident
    ]

    summary = moderation_gated(rows, tracked={1: "no-link-rule", 4: "label-review"})

    assert summary.false_negatives == (2,)
    assert summary.false_positives == (3,)
    assert summary.total == 2
    assert summary.legitimate_routes["incident"] == 1
    assert summary.violation_routes["none"] == 1


def test_tracked_lines_are_reported_with_pass_or_fail() -> None:
    moderation = _result(
        "real-moderation.jsonl",
        "moderation-real",
        [_mod(1, True, False), _mod(2, True, True)],
        tracked={1: "no-link-rule", 2: "label-review"},
    )
    attention = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, False, proposes=True), _att(2, True, rule=True)],
        tracked={1: "label-review", 2: "label-review"},
    )

    assert tracked_lines(moderation) == (
        TrackedLine("real-moderation.jsonl", 1, "no-link-rule", passed=False),
        TrackedLine("real-moderation.jsonl", 2, "label-review", passed=True),
    )
    assert tracked_lines(attention) == (
        TrackedLine("real-attention.jsonl", 1, "label-review", passed=False),
        TrackedLine("real-attention.jsonl", 2, "label-review", passed=True),
    )


def test_annotations_are_read_from_fixtures_by_line_number_without_their_text() -> None:
    fixtures = [
        (1, {"text": _SENTINEL, "needs_response": True, "label_class": "ambiguous"}),
        (2, {"text": _SENTINEL, "needs_response": False, "label_class": "clear"}),
        (3, {"text": _SENTINEL, "category": "ABUSE", "tracked": "label-review"}),
    ]

    label_classes, tracked = fixture_annotations(fixtures)

    assert label_classes == {1: "ambiguous", 2: "clear"}
    assert tracked == {3: "label-review"}


# --- S5: repeat ---------------------------------------------------------------------------------


def test_identical_runs_differ_on_no_line() -> None:
    rows = [_att(1, True, proposes=True), _att(2, False, excluded="acknowledgement")]

    assert compare_runs([rows, list(rows)]) == ()


@pytest.mark.parametrize(
    "changed",
    [
        _att(1, True, proposes=False),  # needs-response
        _att(1, True, proposes=True, category="QUESTION_ACCESS"),  # category
        _att(1, True, proposes=True, route="possible_violation/inconsistent"),  # route
        _att(1, True, error="ModelTimeoutError"),  # no answer at all
    ],
)
def test_a_line_differs_on_needs_response_category_route_or_a_failure(
    changed: AttentionRow,
) -> None:
    first = [_att(1, True, proposes=True), _att(2, False)]

    assert compare_runs([first, [changed, _att(2, False)]]) == (1,)


def test_a_line_differs_on_needs_moderation() -> None:
    assert compare_runs([[_mod(1, True, True)], [_mod(1, True, False)]]) == (1,)


def test_a_change_of_confidence_alone_is_not_a_difference() -> None:
    first = _mod(1, True, True)
    second = SmokeRow(**{**first.__dict__, "confidence": 0.7})

    assert compare_runs([[first], [second]]) == ()


def test_every_later_run_is_compared_with_the_first() -> None:
    same = [_att(1, True, proposes=True), _att(2, False)]
    third = [_att(1, True, proposes=True), _att(2, False, proposes=True)]

    assert compare_runs([same, same, third]) == (2,)


# --- S6: latency --------------------------------------------------------------------------------


def test_latency_median_and_p95() -> None:
    assert latency_percentiles([400, 100, 300, 200, 500]) == (300, 500)
    assert latency_percentiles(list(range(1, 101))) == (50, 95)
    assert latency_percentiles([1000, 2000]) == (1500, 2000)


def test_no_latency_without_a_call() -> None:
    assert latency_percentiles([]) is None


# --- the gate, Q1-Q12 ---------------------------------------------------------------------------


def test_a_full_clean_run_passes_every_gate_and_qualifies() -> None:
    gates = evaluate_gate(_passing(), repeat=2)

    assert [gate.gate for gate in gates] == [f"Q{n}" for n in range(1, 13)]
    assert {gate.status for gate in gates} == {"PASS"}
    assert verdict(gates) == "QUALIFIED"
    assert exit_code_for(verdict(gates)) == 0


def test_q1_fails_on_one_tuning_clear_negative_the_model_opened() -> None:
    real = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, True, proposes=True), _att(2, False, proposes=True)],
    )

    gate = _gate(evaluate_gate(_passing(real=real), repeat=2), "Q1")

    assert gate.status == "FAIL"
    assert "real-attention.jsonl #2" in gate.detail


def test_q1_ignores_an_ambiguous_line_the_model_opened() -> None:
    real = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, False, proposes=True)],
        label_classes={1: "ambiguous"},
    )

    assert _gate(evaluate_gate(_passing(real=real), repeat=2), "Q1").status == "PASS"


@pytest.mark.parametrize(("opened", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q2_allows_one_held_out_clear_negative_the_model_opened(opened: int, status: str) -> None:
    heldout = _result(
        "attention_smoke_heldout_fixtures.jsonl", "heldout", _heldout_rows(opened_negatives=opened)
    )

    assert _gate(evaluate_gate(_passing(heldout=heldout), repeat=2), "Q2").status == status


@pytest.mark.parametrize(
    "missed", [_att(2, True, proposes=False), _att(2, True, excluded="acknowledgement")]
)
def test_q3_fails_on_one_missed_tuning_clear_positive(missed: AttentionRow) -> None:
    shipped = _result(
        "attention_smoke_fixtures.jsonl", "tuning", [_att(1, True, rule=True), missed]
    )

    gate = _gate(evaluate_gate(_passing(shipped=shipped), repeat=2), "Q3")

    assert gate.status == "FAIL"
    assert "attention_smoke_fixtures.jsonl #2" in gate.detail


@pytest.mark.parametrize(("missed", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q4_allows_one_missed_rule_declined_held_out_positive(missed: int, status: str) -> None:
    heldout = _result(
        "attention_smoke_heldout_fixtures.jsonl", "heldout", _heldout_rows(missed=missed)
    )

    assert _gate(evaluate_gate(_passing(heldout=heldout), repeat=2), "Q4").status == status


def test_q4_fails_when_the_held_out_set_has_fewer_than_ten_rule_declined_positives() -> None:
    heldout = _result(
        "attention_smoke_heldout_fixtures.jsonl", "heldout", _heldout_rows(declined=9)
    )

    assert _gate(evaluate_gate(_passing(heldout=heldout), repeat=2), "Q4").status == "FAIL"


def test_q5_fails_on_an_untracked_real_miss_and_passes_on_a_tracked_one() -> None:
    untracked = _result("real-moderation.jsonl", "moderation-real", [_mod(1, True, False)])
    tracked = _result(
        "real-moderation.jsonl",
        "moderation-real",
        [_mod(1, True, False)],
        tracked={1: "no-link-rule"},
    )

    failed = _gate(evaluate_gate(_passing(mod_real=untracked), repeat=2), "Q5")
    passed = _gate(evaluate_gate(_passing(mod_real=tracked), repeat=2), "Q5")

    assert (failed.status, passed.status) == ("FAIL", "PASS")
    assert "real-moderation.jsonl #1" in failed.detail


def test_q6_fails_on_one_shipped_false_positive() -> None:
    shipped = _result(
        "moderation_smoke_fixtures.jsonl",
        "moderation-shipped",
        [_mod(1, False, True, category="QUESTION_COURSE")],
    )

    gate = _gate(evaluate_gate(_passing(mod_shipped=shipped), repeat=2), "Q6")

    assert gate.status == "FAIL"
    assert "moderation_smoke_fixtures.jsonl #1" in gate.detail


@pytest.mark.parametrize(("misses", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q7_allows_one_missed_policy_violation(misses: int, status: str) -> None:
    rows = [_mod(n, True, n > misses) for n in range(1, 5)]
    policy = _result("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", rows)

    assert _gate(evaluate_gate(_passing(mod_policy=policy), repeat=2), "Q7").status == status


def test_q7_fails_on_a_legitimate_policy_line_flagged_or_routed_to_an_incident() -> None:
    flagged = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        [_mod(1, False, True, category="QUESTION_COURSE", route="possible_violation/uncertain")],
    )
    incident = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        [_mod(1, False, True, category="QUESTION_COURSE", route="incident")],
    )

    for policy in (flagged, incident):
        assert _gate(evaluate_gate(_passing(mod_policy=policy), repeat=2), "Q7").status == "FAIL"


def test_q8_fails_when_the_second_run_differs() -> None:
    fresh = _result(
        "fresh-attention.jsonl",
        "fresh",
        [_att(1, True, proposes=True), _att(2, False)],
        run_two=[_att(1, True, proposes=False), _att(2, False)],
    )

    gate = _gate(evaluate_gate(_passing(fresh=fresh), repeat=2), "Q8")

    assert gate.status == "FAIL"
    assert "fresh-attention.jsonl #1" in gate.detail


def test_repeat_one_is_never_qualified() -> None:
    once = [
        SetResult(
            spec=result.spec,
            runs=result.runs[:1],
            latencies_ms=result.latencies_ms,
            label_classes=result.label_classes,
            tracked=result.tracked,
        )
        for result in _passing()
    ]

    gates = evaluate_gate(once, repeat=1)

    assert _gate(gates, "Q8").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"
    assert exit_code_for(verdict(gates)) == 2


@pytest.mark.parametrize(("opened", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q9_allows_one_fresh_clear_negative_the_model_opened(opened: int, status: str) -> None:
    rows = [_att(1, True, proposes=True)] + [
        _att(1 + n, False, proposes=n <= opened) for n in range(1, 4)
    ]
    fresh = _result("fresh-attention.jsonl", "fresh", rows)

    assert _gate(evaluate_gate(_passing(fresh=fresh), repeat=2), "Q9").status == status


@pytest.mark.parametrize(("missed", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q9_allows_one_missed_fresh_rule_declined_positive(missed: int, status: str) -> None:
    rows = [_att(n, True, proposes=n > missed) for n in range(1, 5)]
    fresh = _result("fresh-attention.jsonl", "fresh", rows)

    assert _gate(evaluate_gate(_passing(fresh=fresh), repeat=2), "Q9").status == status


def test_q9_is_not_run_without_the_fresh_sample() -> None:
    gates = evaluate_gate(_passing(fresh=_missing("fresh-attention.jsonl", "fresh")), repeat=2)

    assert _gate(gates, "Q9").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"
    assert exit_code_for(verdict(gates)) == 2


@pytest.mark.parametrize(("latency_ms", "status"), [(10_000, "PASS"), (10_001, "FAIL")])
def test_q10_p95_latency_at_ten_seconds(latency_ms: int, status: str) -> None:
    real = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, True, proposes=True)],
        latencies=(latency_ms,) * 60,  # enough calls to set the p95 over every set's
    )

    assert _gate(evaluate_gate(_passing(real=real), repeat=2), "Q10").status == status


def test_q11_fails_on_an_error_in_any_run() -> None:
    policy = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        [_mod(1, True, True)],
        run_two=[_mod(1, True, None, error="ModelTimeoutError")],
    )

    gate = _gate(evaluate_gate(_passing(mod_policy=policy), repeat=2), "Q11")

    assert gate.status == "FAIL"
    assert "moderation_smoke_policy_fixtures.jsonl #1" in gate.detail


@pytest.mark.parametrize(("count", "status"), [(2, "PASS"), (3, "FAIL")])
def test_q12_the_closed_list_holds_at_most_two_tracked_lines(count: int, status: str) -> None:
    rows = [_mod(n, True, True) for n in range(1, count + 1)]
    policy = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        rows,
        tracked={n: "label-review" for n in range(1, count + 1)},
    )
    # Only this set's tracked lines count here: drop the two the passing results already carry.
    mod_real = _result("real-moderation.jsonl", "moderation-real", [_mod(1, True, True)])
    mod_shipped = _result(
        "moderation_smoke_fixtures.jsonl", "moderation-shipped", [_mod(1, True, True)]
    )

    gates = evaluate_gate(
        _passing(mod_policy=policy, mod_real=mod_real, mod_shipped=mod_shipped), repeat=2
    )

    assert _gate(gates, "Q12").status == status


def test_q12_counts_the_two_known_tracked_lines() -> None:
    gate = _gate(evaluate_gate(_passing(), repeat=2), "Q12")

    assert gate.status == "PASS"
    assert "2" in gate.detail


# --- NOT RUN and the verdict --------------------------------------------------------------------


def test_a_missing_held_out_set_leaves_q2_and_q4_not_run() -> None:
    gates = evaluate_gate(
        _passing(heldout=_missing("attention_smoke_heldout_fixtures.jsonl", "heldout")), repeat=2
    )

    assert (_gate(gates, "Q2").status, _gate(gates, "Q4").status) == ("NOT RUN", "NOT RUN")
    assert verdict(gates) == "INCOMPLETE"


def test_without_a_real_attention_set_q1_and_q3_are_not_run() -> None:
    gates = evaluate_gate(_passing(real=_missing("real-attention*.jsonl", "tuning")), repeat=2)

    assert (_gate(gates, "Q1").status, _gate(gates, "Q3").status) == ("NOT RUN", "NOT RUN")


def test_evidence_of_failure_fails_a_gate_even_with_a_set_missing() -> None:
    shipped = _result("attention_smoke_fixtures.jsonl", "tuning", [_att(1, False, proposes=True)])

    gates = evaluate_gate(
        _passing(real=_missing("real-attention*.jsonl", "tuning"), shipped=shipped), repeat=2
    )

    assert _gate(gates, "Q1").status == "FAIL"


def test_fail_takes_precedence_over_not_run() -> None:
    real = _result("real-attention.jsonl", "tuning", [_att(1, False, proposes=True)])

    gates = evaluate_gate(
        _passing(real=real, fresh=_missing("fresh-attention.jsonl", "fresh")), repeat=2
    )

    assert verdict(gates) == "NOT QUALIFIED"
    assert exit_code_for(verdict(gates)) == 1


def test_the_verdict_names() -> None:
    def gates(*statuses: str) -> tuple[GateLine, ...]:
        return tuple(GateLine(f"Q{n}", "", status, "") for n, status in enumerate(statuses, 1))

    assert verdict(gates("PASS", "PASS")) == "QUALIFIED"
    assert verdict(gates("PASS", "NOT RUN")) == "INCOMPLETE"
    assert verdict(gates("FAIL", "NOT RUN")) == "NOT QUALIFIED"
    assert [exit_code_for(name) for name in ("QUALIFIED", "NOT QUALIFIED", "INCOMPLETE")] == [
        0,
        1,
        2,
    ]


# --- the report (§5): counts and line numbers, never text ----------------------------------------


def _report(results: list[SetResult], *, repeat: int = 2) -> list[str]:
    return format_report(
        results,
        evaluate_gate(results, repeat=repeat),
        profile="ollama-gemma4-e4b-moderation",
        model="gemma4:e4b-it-qat",
        prompt="classify_v2",
        floor="0.600",
        threshold="0.850",
        repeat=repeat,
    )


def test_the_report_prints_the_header_every_gate_and_the_verdict() -> None:
    lines = _report(_passing())

    assert lines[0] == (
        "qualify-moderation: profile=ollama-gemma4-e4b-moderation model=gemma4:e4b-it-qat "
        "prompt=classify_v2 floor=0.600 threshold=0.850 repeat=2"
    )
    for n in range(1, 13):
        assert any(line.startswith(f"Q{n} ") for line in lines), f"Q{n} missing"
    assert lines[-1] == "result: QUALIFIED"
    assert any(line.startswith("latency: median=1000 ms p95=1000 ms") for line in lines)
    assert "repeat: 2 runs, 0 differing lines" in lines


def test_the_report_names_a_missing_set_and_its_tracked_lines() -> None:
    lines = _report(_passing(fresh=_missing("fresh-attention.jsonl", "fresh")))

    assert "== fresh-attention.jsonl (fresh) — NOT RUN: missing ==" in lines
    assert "tracked: real-moderation.jsonl #1 no-link-rule FAIL" in lines
    assert "tracked: moderation_smoke_fixtures.jsonl #11 label-review FAIL" in lines
    assert lines[-1] == "result: INCOMPLETE"


def test_the_report_never_carries_a_fixtures_text() -> None:
    fixtures = [
        (1, {"text": _SENTINEL, "needs_response": True, "label_class": "ambiguous"}),
        (2, {"text": _SENTINEL, "needs_response": False, "label_class": "clear"}),
    ]
    label_classes, tracked = fixture_annotations(fixtures)
    real = SetResult(
        spec=_spec("real-attention.jsonl", "tuning"),
        runs=(
            (_att(1, True, proposes=True), _att(2, False, error="StructuredOutputInvalidError")),
        ),
        latencies_ms=(900,),
        label_classes=label_classes,
        tracked=tracked,
    )

    lines = _report(_passing(real=real), repeat=1)

    assert lines
    assert not [line for line in lines if _SENTINEL in line]
    assert any("label class:" in line and "ambiguous 1" in line for line in lines)
