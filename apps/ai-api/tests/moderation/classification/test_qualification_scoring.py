"""The qualification's core and its moderation suite
(`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` version 2 §4-§7; 010's
version 1 gates Q5-Q12, unchanged). Pure — scripted rows, no model, no database.

- A moderation line is scored exactly as the smoke scores it, with tracked lines taken out of the
  gated counts and reported on their own line.
- A gate is `FAIL` on the evidence that ran, `NOT RUN` when a set it needs is missing, `PASS`
  otherwise. Any `FAIL` makes the pair `NOT QUALIFIED`; otherwise any `NOT RUN` makes it
  `INCOMPLETE`. `--repeat 1` is never `QUALIFIED`. A candidate wording is always `CANDIDATE`.
- The printed report carries counts, set names and line numbers — never a fixture's text — and
  its moderation part is version 1's, byte for byte.

The attention suite's scoring and gates (S1, S1b, S2, A1-A9) are in
`test_qualification_attention.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.scripts.qualification.core import (
    CANDIDATE,
    GateLine,
    SetResult,
    SetSpec,
    TrackedLine,
    compare_runs,
    exit_code_for,
    fixture_annotations,
    latency_percentiles,
    verdict,
)
from app.scripts.qualification.moderation import (
    evaluate_moderation_gates,
    format_moderation_report,
    moderation_gated,
    moderation_signature,
    moderation_tracked_lines,
)
from app.scripts.smoke_moderation import SmokeRow

_SENTINEL = "SENTINEL-fixture-text-never-printed"


# --- row builders ------------------------------------------------------------------------------


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


def _spec(name: str, role: str, *, present: bool = True) -> SetSpec:
    return SetSpec(name=name, role=role, kind="moderation", path=Path(name) if present else None)


def _result(
    name: str,
    role: str,
    rows: list[Any],
    *,
    runs: int = 2,
    run_two: list[Any] | None = None,
    latencies: tuple[int, ...] | None = None,
    tracked: dict[int, str] | None = None,
) -> SetResult:
    second = run_two if run_two is not None else rows
    all_runs = (tuple(rows), tuple(second))[:runs]
    return SetResult(
        spec=_spec(name, role),
        runs=all_runs,
        latencies_ms=latencies if latencies is not None else tuple(1000 for _ in rows) * runs,
        tracked=tracked or {},
    )


def _missing(name: str, role: str) -> SetResult:
    return SetResult(spec=_spec(name, role, present=False))


def _passing(**replace: SetResult) -> list[SetResult]:
    """A full, qualifying set of moderation results, in the order the suite reads them (§2). Any
    set can be replaced by name."""
    results = {
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


# --- S3 (version 1's S2, S3): moderation lines and tracked lines --------------------------------


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
        [_mod(1, True, False), _mod(2, True, True), _mod(3, True, None, error="ModelTimeoutError")],
        tracked={1: "no-link-rule", 2: "label-review", 3: "label-review"},
    )

    assert moderation_tracked_lines(moderation) == (
        TrackedLine("real-moderation.jsonl", 1, "no-link-rule", passed=False),
        TrackedLine("real-moderation.jsonl", 2, "label-review", passed=True),
        TrackedLine("real-moderation.jsonl", 3, "label-review", passed=False),
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


# --- S5: repeat, on version 1's moderation signature --------------------------------------------


def _differing(first: list[SmokeRow], *later: list[SmokeRow]) -> tuple[int, ...]:
    return compare_runs([first, *later], signature=moderation_signature)


def test_identical_runs_differ_on_no_line() -> None:
    rows = [_mod(1, True, True), _mod(2, False, False)]

    assert _differing(rows, list(rows)) == ()


@pytest.mark.parametrize(
    "changed",
    [
        _mod(1, True, False),  # needs-moderation
        _mod(1, True, True, category="ABUSE"),  # category
        _mod(1, True, True, route="possible_violation/uncertain"),  # route
        _mod(1, True, None, error="ModelTimeoutError"),  # no answer at all
        SmokeRow(**{**_mod(1, True, True).__dict__, "predicted_needs_response": True}),
    ],
)
def test_a_line_differs_on_needs_response_needs_moderation_category_route_or_a_failure(
    changed: SmokeRow,
) -> None:
    assert _differing(
        [_mod(1, True, True), _mod(2, False, False)], [changed, _mod(2, False, False)]
    ) == (1,)


def test_a_change_of_confidence_alone_is_not_a_difference() -> None:
    first = _mod(1, True, True)
    second = SmokeRow(**{**first.__dict__, "confidence": 0.7})

    assert _differing([first], [second]) == ()


def test_every_later_run_is_compared_with_the_first() -> None:
    same = [_mod(1, True, True), _mod(2, False, False)]
    third = [_mod(1, True, True), _mod(2, False, True)]

    assert _differing(same, same, third) == (2,)


# --- S6: latency --------------------------------------------------------------------------------


def test_latency_median_and_p95() -> None:
    assert latency_percentiles([400, 100, 300, 200, 500]) == (300, 500)
    assert latency_percentiles(list(range(1, 101))) == (50, 95)
    assert latency_percentiles([1000, 2000]) == (1500, 2000)


def test_no_latency_without_a_call() -> None:
    assert latency_percentiles([]) is None


# --- the moderation gates, Q5-Q8, Q11, Q12 ------------------------------------------------------


def test_a_full_clean_run_passes_every_gate_and_qualifies() -> None:
    gates = evaluate_moderation_gates(_passing(), repeat=2)

    assert [gate.gate for gate in gates] == ["Q5", "Q6", "Q7", "Q8", "Q11", "Q12"]
    assert {gate.status for gate in gates} == {"PASS"}
    assert verdict(gates) == "QUALIFIED"
    assert exit_code_for(verdict(gates)) == 0


def test_q5_fails_on_an_untracked_real_miss_and_passes_on_a_tracked_one() -> None:
    untracked = _result("real-moderation.jsonl", "moderation-real", [_mod(1, True, False)])
    tracked = _result(
        "real-moderation.jsonl",
        "moderation-real",
        [_mod(1, True, False)],
        tracked={1: "no-link-rule"},
    )

    failed = _gate(evaluate_moderation_gates(_passing(mod_real=untracked), repeat=2), "Q5")
    passed = _gate(evaluate_moderation_gates(_passing(mod_real=tracked), repeat=2), "Q5")

    assert (failed.status, passed.status) == ("FAIL", "PASS")
    assert "real-moderation.jsonl #1" in failed.detail


def test_q6_fails_on_one_shipped_false_positive() -> None:
    shipped = _result(
        "moderation_smoke_fixtures.jsonl",
        "moderation-shipped",
        [_mod(1, False, True, category="QUESTION_COURSE")],
    )

    gate = _gate(evaluate_moderation_gates(_passing(mod_shipped=shipped), repeat=2), "Q6")

    assert gate.status == "FAIL"
    assert "moderation_smoke_fixtures.jsonl #1" in gate.detail


@pytest.mark.parametrize(("misses", "status"), [(1, "PASS"), (2, "FAIL")])
def test_q7_allows_one_missed_policy_violation(misses: int, status: str) -> None:
    rows = [_mod(n, True, n > misses) for n in range(1, 5)]
    policy = _result("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", rows)

    gates = evaluate_moderation_gates(_passing(mod_policy=policy), repeat=2)

    assert _gate(gates, "Q7").status == status


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
        gates = evaluate_moderation_gates(_passing(mod_policy=policy), repeat=2)
        assert _gate(gates, "Q7").status == "FAIL"


def test_q8_fails_when_the_second_run_differs() -> None:
    policy = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        [_mod(1, True, True), _mod(2, False, False)],
        run_two=[_mod(1, True, False), _mod(2, False, False)],
    )

    gate = _gate(evaluate_moderation_gates(_passing(mod_policy=policy), repeat=2), "Q8")

    assert gate.status == "FAIL"
    assert "moderation_smoke_policy_fixtures.jsonl #1" in gate.detail


def test_repeat_one_is_never_qualified() -> None:
    once = [
        SetResult(
            spec=result.spec,
            runs=result.runs[:1],
            latencies_ms=result.latencies_ms,
            tracked=result.tracked,
        )
        for result in _passing()
    ]

    gates = evaluate_moderation_gates(once, repeat=1)

    assert _gate(gates, "Q8").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"
    assert exit_code_for(verdict(gates)) == 2


def test_q11_fails_on_an_error_in_any_run() -> None:
    policy = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "moderation-policy",
        [_mod(1, True, True)],
        run_two=[_mod(1, True, None, error="ModelTimeoutError")],
    )

    gate = _gate(evaluate_moderation_gates(_passing(mod_policy=policy), repeat=2), "Q11")

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

    gates = evaluate_moderation_gates(
        _passing(mod_policy=policy, mod_real=mod_real, mod_shipped=mod_shipped), repeat=2
    )

    assert _gate(gates, "Q12").status == status


def test_q12_counts_the_two_known_tracked_lines() -> None:
    gate = _gate(evaluate_moderation_gates(_passing(), repeat=2), "Q12")

    assert gate.status == "PASS"
    assert "2" in gate.detail


# --- NOT RUN and the verdict --------------------------------------------------------------------


def test_a_missing_real_moderation_set_leaves_q5_not_run() -> None:
    gates = evaluate_moderation_gates(
        _passing(mod_real=_missing("real-moderation.jsonl", "moderation-real")), repeat=2
    )

    assert _gate(gates, "Q5").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"
    assert exit_code_for(verdict(gates)) == 2


def test_fail_takes_precedence_over_not_run() -> None:
    shipped = _result(
        "moderation_smoke_fixtures.jsonl", "moderation-shipped", [_mod(1, True, False)]
    )

    gates = evaluate_moderation_gates(
        _passing(
            mod_real=_missing("real-moderation.jsonl", "moderation-real"), mod_shipped=shipped
        ),
        repeat=2,
    )

    assert verdict(gates) == "NOT QUALIFIED"
    assert exit_code_for(verdict(gates)) == 1


def test_the_verdict_names_and_exit_codes() -> None:
    def gates(*statuses: str) -> tuple[GateLine, ...]:
        return tuple(GateLine(f"Q{n}", "", status, "") for n, status in enumerate(statuses, 1))

    assert verdict(gates("PASS", "PASS")) == "QUALIFIED"
    assert verdict(gates("PASS", "NOT RUN")) == "INCOMPLETE"
    assert verdict(gates("FAIL", "NOT RUN")) == "NOT QUALIFIED"
    assert [
        exit_code_for(name) for name in ("QUALIFIED", "NOT QUALIFIED", "INCOMPLETE", "CANDIDATE")
    ] == [0, 1, 2, 3]


@pytest.mark.parametrize("statuses", [("PASS", "PASS"), ("FAIL", "PASS"), ("NOT RUN", "PASS")])
def test_a_candidate_is_always_candidate_whatever_the_gates(statuses: tuple[str, ...]) -> None:
    gates = tuple(GateLine(f"A{n}", "", status, "") for n, status in enumerate(statuses, 1))

    assert verdict(gates, candidate=True) == CANDIDATE == "CANDIDATE"
    assert exit_code_for(verdict(gates, candidate=True)) == 3


# --- the report (§7): counts and line numbers, never text; version 1's moderation part ---------


def _report(results: list[SetResult], *, repeat: int = 2) -> list[str]:
    return format_moderation_report(
        results,
        evaluate_moderation_gates(results, repeat=repeat),
        profile="ollama-gemma4-e2b-moderation",
        model="gemma4:e2b-it-qat",
        prompt="classify_v2",
        floor="0.600",
        threshold="0.850",
        repeat=repeat,
    )


def test_the_report_prints_the_header_every_gate_and_the_verdict() -> None:
    lines = _report(_passing())

    assert lines[0] == (
        "qualify-moderation: profile=ollama-gemma4-e2b-moderation model=gemma4:e2b-it-qat "
        "prompt=classify_v2 floor=0.600 threshold=0.850 repeat=2"
    )
    for gate in ("Q5", "Q6", "Q7", "Q8", "Q11", "Q12"):
        assert any(line.startswith(f"{gate} ") for line in lines), f"{gate} missing"
    assert lines[-1] == "result: QUALIFIED"
    assert "latency: median=1000 ms p95=1000 ms over 12 calls" in lines
    assert "repeat: 2 runs, 0 differing lines" in lines


def test_each_sets_block_is_version_1s() -> None:
    lines = _report(_passing())

    start = lines.index("== real-moderation.jsonl (moderation-real) ==")
    assert lines[start + 1 : start + 11] == [
        "1/2 matched",
        "category exact: 2/2",
        "needs_moderation agreed: 1/2",
        "false negatives (expected true, predicted false): 1 (#1)",
        "false positives (expected false, predicted true): 0",
        "errors: 0",
        "routes, violations: incident=0 possible_violation=0 review=0 none=1",
        "routes, legitimate: incident=0 possible_violation=0 review=0 none=1",
        "gated, tracked out: false negatives 0; false positives 0; legitimate -> incident 0",
        "tracked: real-moderation.jsonl #1 no-link-rule FAIL",
    ]
    assert (
        "Q12 PASS — tracked lines <= 2, each no-link-rule or label-review: 2 "
        "(real-moderation.jsonl #1; moderation_smoke_fixtures.jsonl #11)"
    ) in lines


def test_the_report_names_a_missing_set_and_its_tracked_lines() -> None:
    lines = _report(_passing(mod_real=_missing("real-moderation.jsonl", "moderation-real")))

    assert "== real-moderation.jsonl (moderation-real) — NOT RUN: missing ==" in lines
    assert "tracked: moderation_smoke_fixtures.jsonl #11 label-review FAIL" in lines
    assert lines[-1] == "result: INCOMPLETE"


def test_the_report_never_carries_a_fixtures_text() -> None:
    lines = _report(_passing(), repeat=1)

    assert lines
    assert not [line for line in lines if _SENTINEL in line]
    assert "repeat: 1 run, not compared" in lines
