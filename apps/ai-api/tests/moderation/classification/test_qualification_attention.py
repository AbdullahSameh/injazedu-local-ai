"""The qualification's attention suite (`specs/011-tg-m5-3-attention-judgement/contracts/
qualification.md` version 2 §4-§7; D-TG-194, D-TG-195): scoring S1, S1b, S2 and S5, the gates
A1-A9 at every boundary, the reported lines, the per-message estimate, the `CANDIDATE` verdict and
the no-text report. Pure — scripted rows and a stub gateway, no model, no database.

- **S1.** A one-message line the rules open makes no call and has opener `rule`; an excluded one
  has `excluded`; otherwise the model's intent gives `model` (asking) or `none`.
- **S1b.** A burst the rules open over all members is `rule`; otherwise the first `asking` member
  opens, and its index is reported; otherwise `none`.
- **S2.** An A6 line has no rule step and no veto: it counts when the intent is `asking`.
- **S5.** Two runs differ when a line's opener or intent does (every member's, for a burst).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application.gateway import ModelTimeoutError
from app.application.moderation.attention_judgement import AttentionJudgementResult
from app.scripts.qualification.attention import (
    AttentionRow,
    BurstRow,
    MemberResult,
    ViolationRow,
    attention_signature,
    discussion_line,
    evaluate_attention_gates,
    format_attention_report,
    intent_agreement,
    judge_attention_burst,
    judge_attention_line,
    judge_violation_line,
    per_message_estimate,
    rule_opened_negatives,
    split_by_label_class,
)
from app.scripts.qualification.core import (
    GateLine,
    SetResult,
    SetSpec,
    compare_runs,
    exit_code_for,
    verdict,
)

_SENTINEL = "SENTINEL-fixture-text-never-printed"
_INSTRUCTION = "TEST ATTENTION INSTRUCTION"
_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


# --- the stub gateway ---------------------------------------------------------------------------


class _ByText:
    """Answers each call with the intent its user message is mapped to; `None` times out."""

    def __init__(self, answers: dict[str, str | None], default: str = "other") -> None:
        self.answers = answers
        self.default = default
        self.calls: list[tuple[str, str]] = []

    async def generate_structured(self, request: Any, *, role: str) -> Any:
        content = request.messages[-1].content
        self.calls.append((content, role))
        intent = self.answers.get(content, self.default)
        if intent is None:
            raise ModelTimeoutError(f"raw model output {_SENTINEL}", profile_name="stub")
        return SimpleNamespace(value=AttentionJudgementResult.model_validate({"intent": intent}))


# --- S1: one line, on the live path -------------------------------------------------------------


async def test_s1_a_rule_opening_line_makes_no_call_and_its_opener_is_rule() -> None:
    gateway = _ByText({})

    row, latency_ms = await judge_attention_line(
        gateway,  # type: ignore[arg-type]
        {"text": "متى الاختبار؟", "needs_response": True},
        line=1,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == []
    assert (row.opener, row.intent, latency_ms) == ("rule", None, None)


async def test_s1_an_excluded_line_makes_no_call() -> None:
    gateway = _ByText({})

    row, _ = await judge_attention_line(
        gateway,  # type: ignore[arg-type]
        {"text": "تمام", "needs_response": False},
        line=1,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == []
    assert (row.opener, row.excluded) == ("excluded", "acknowledgement")


@pytest.mark.parametrize(
    ("intent", "opener"),
    [("asking", "model"), ("discussion", "none"), ("informing", "none"), ("other", "none")],
)
async def test_s1_the_intent_gives_model_or_none(intent: str, opener: str) -> None:
    gateway = _ByText({"حد خلص الواجب": intent})

    row, _ = await judge_attention_line(
        gateway,  # type: ignore[arg-type]
        {"text": "حد خلص الواجب", "needs_response": False},
        line=1,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == [("حد خلص الواجب", "attention")]
    assert (row.opener, row.intent) == (opener, intent)


# --- S1b: one burst -----------------------------------------------------------------------------


async def test_s1b_a_burst_the_rules_open_over_all_members_is_rule_with_no_call() -> None:
    gateway = _ByText({})

    row, calls = await judge_attention_burst(
        gateway,  # type: ignore[arg-type]
        {
            "burst": ["السلام عليكم", "متى الاختبار؟"],
            "needs_response": True,
            "expected_opener": "rule",
        },
        line=1,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == []
    assert (row.opener, row.opening_member, row.members, calls) == ("rule", None, (), ())
    assert row.matched


async def test_s1b_the_first_asking_member_opens_and_its_index_is_recorded() -> None:
    gateway = _ByText(
        {
            "السلام عليكم": "social",
            "كنت بحاول ادخل الاختبار": "informing",
            "بس الرابط بايظ": "asking",
        }
    )

    row, calls = await judge_attention_burst(
        gateway,  # type: ignore[arg-type]
        {
            "burst": ["السلام عليكم", "كنت بحاول ادخل الاختبار", "بس الرابط بايظ"],
            "needs_response": True,
            "expected_opener": "model",
        },
        line=4,
        instruction=_INSTRUCTION,
    )

    # Each member on its own, in posting order — never the burst as one input (FR-339).
    assert [content for content, _ in gateway.calls] == [
        "السلام عليكم",
        "كنت بحاول ادخل الاختبار",
        "بس الرابط بايظ",
    ]
    assert (row.opener, row.opening_member) == ("model", 3)
    assert [m.intent for m in row.members] == ["social", "informing", "asking"]
    assert len(calls) == 3
    assert row.matched and not row.l_b1


async def test_s1b_no_asking_member_is_none_and_an_l_b1_line_is_named() -> None:
    gateway = _ByText({}, default="informing")

    row, _ = await judge_attention_burst(
        gateway,  # type: ignore[arg-type]
        {
            "burst": ["كنت بحاول ادخل الاختبار", "امبارح وبرضه النهارده", "😢"],
            "needs_response": True,
            "expected_opener": "none",
        },
        line=5,
        instruction=_INSTRUCTION,
    )

    assert len(gateway.calls) == 2  # the bare emoji is an acknowledgement, never sent
    assert row.members[2] == MemberResult(excluded="acknowledgement")
    assert (row.opener, row.opening_member) == ("none", None)
    assert row.matched and row.l_b1


def test_s1b_an_error_is_the_opener_only_when_no_member_proposes() -> None:
    failed = MemberResult(error="ModelTimeoutError")
    asking = MemberResult(intent="asking")

    def burst(*members: MemberResult) -> BurstRow:
        return BurstRow(
            line=1,
            expected_needs_response=True,
            expected_opener="model",
            rule_opens=False,
            members=members,
        )

    assert burst(failed, asking).opener == "model"
    assert burst(failed, asking).opening_member == 2
    assert burst(failed, MemberResult(intent="social")).opener == "error"
    assert burst(failed).error == "ModelTimeoutError"


# --- S2: A6 lines -------------------------------------------------------------------------------


async def test_s2_a_violation_line_has_no_rule_step_and_no_veto() -> None:
    # The rules would open this text; an A6 line is judged anyway, and asking counts.
    gateway = _ByText({"ممكن تواصل خاص": "asking"})

    row, latency_ms = await judge_violation_line(
        gateway,  # type: ignore[arg-type]
        {"text": "ممكن تواصل خاص", "category": "SPAM_OR_AD", "needs_moderation": True},
        line=7,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == [("ممكن تواصل خاص", "attention")]
    assert row.answered_asking
    assert isinstance(latency_ms, int)


async def test_s2_a_line_not_needing_moderation_is_not_judged() -> None:
    gateway = _ByText({})

    row, latency_ms = await judge_violation_line(
        gateway,  # type: ignore[arg-type]
        {"text": "صباح الخير", "category": "CHITCHAT", "needs_moderation": False},
        line=2,
        instruction=_INSTRUCTION,
    )

    assert gateway.calls == []
    assert (row.violation, row.answered_asking, latency_ms) == (False, False, None)


@pytest.mark.parametrize("intent", ["offering", "discussion", "social"])
def test_s2_only_asking_counts(intent: str) -> None:
    assert not ViolationRow(line=1, violation=True, intent=intent).answered_asking
    assert ViolationRow(line=1, violation=True, intent="asking").answered_asking


# --- S5: the signature is the opener and the intent ---------------------------------------------


def _att(
    line: int,
    expected: bool,
    *,
    intent: str | None = None,
    rule: bool = False,
    excluded: str | None = None,
    error: str | None = None,
    label: str | None = None,
    peer: bool = False,
) -> AttentionRow:
    return AttentionRow(
        line=line,
        expected_needs_response=expected,
        rule_opens=rule,
        expected_intent=label,
        peer=peer,
        excluded=excluded,
        intent=intent,
        error=error,
    )


def _differing(*runs: list[Any]) -> tuple[int, ...]:
    return compare_runs(runs, signature=attention_signature)


def test_s5_identical_runs_differ_on_no_line() -> None:
    rows = [_att(1, True, intent="asking"), _att(2, False, excluded="acknowledgement")]

    assert _differing(rows, list(rows)) == ()


@pytest.mark.parametrize(
    "changed",
    [
        _att(1, False, intent="informing"),  # opener model -> none
        _att(1, False, intent="asking", label="discussion"),  # labels are not the signature
        _att(1, False, error="ModelTimeoutError"),  # no answer at all
    ],
)
def test_s5_a_line_differs_on_its_opener_or_intent(changed: AttentionRow) -> None:
    first = [_att(1, False, intent="asking"), _att(2, False, intent="social")]

    expected = () if changed.intent == "asking" and changed.error is None else (1,)
    assert _differing(first, [changed, _att(2, False, intent="social")]) == expected


def test_s5_an_intent_change_with_the_same_opener_is_a_difference() -> None:
    assert _differing([_att(1, False, intent="social")], [_att(1, False, intent="other")]) == (1,)


def test_s5_a_burst_differs_on_any_members_intent() -> None:
    def burst(*intents: str) -> BurstRow:
        return BurstRow(
            line=3,
            expected_needs_response=True,
            expected_opener="none",
            rule_opens=False,
            members=tuple(MemberResult(intent=i) for i in intents),
        )

    assert _differing([burst("social", "informing")], [burst("social", "informing")]) == ()
    assert _differing([burst("social", "informing")], [burst("social", "other")]) == (3,)


# --- the class split (S1 class rules) -----------------------------------------------------------


def test_a_clear_positive_nobody_opens_is_missed_including_an_excluded_one() -> None:
    rows = [
        _att(1, True, intent="asking"),  # model opens
        _att(2, True, rule=True),  # rules open
        _att(3, True, intent="discussion"),  # nobody — missed
        _att(4, True, excluded="acknowledgement"),  # never judged — missed
        _att(5, True, error="ModelTimeoutError"),  # an error, never scored as a miss (S4)
    ]

    split = split_by_label_class(rows, label_classes={}, tracked={})

    assert split.clear_positives == 5
    assert split.clear_positives_missed == (3, 4)
    assert split.rule_declined_positives == 4
    assert split.rule_declined_positives_missed == (3, 4)


def test_a_clear_negative_is_counted_only_when_the_model_opens_it() -> None:
    rows = [
        _att(1, False, intent="asking"),  # model opens — new moderator work
        _att(2, False, rule=True),  # the rules opened it: not the model's
        _att(3, False, intent="social"),
        _att(4, False, excluded="acknowledgement"),
    ]

    split = split_by_label_class(rows, label_classes={}, tracked={})

    assert split.clear_negatives == 4
    assert split.clear_negatives_model_opened == (1,)


def test_ambiguous_and_tracked_lines_are_never_in_a_gated_count() -> None:
    rows = [
        _att(1, True, intent="asking"),  # ambiguous, answered true, agrees
        _att(2, True, intent="discussion"),  # ambiguous, answered false — not a miss
        _att(3, False, intent="asking"),  # tracked
    ]

    split = split_by_label_class(
        rows, label_classes={1: "ambiguous", 2: "ambiguous"}, tracked={3: "label-review"}
    )

    assert (split.clear_positives, split.clear_negatives) == (0, 0)
    assert (split.ambiguous, split.ambiguous_answered_true, split.ambiguous_agreed) == (2, (1,), 1)


# --- the reported lines (§6) --------------------------------------------------------------------


def test_r_intent_counts_agreement_on_answered_lines_carrying_an_intent() -> None:
    rows = [
        _att(1, True, intent="asking", label="asking"),
        _att(2, False, intent="asking", label="discussion"),
        _att(3, False, intent="informing", label="social"),
        _att(4, False, intent="social"),  # no label intent
        _att(5, True, rule=True, label="asking"),  # no answer
    ]

    agreement = intent_agreement(rows)

    assert (agreement.agreed, agreement.out_of) == (1, 3)
    assert agreement.disagreeing == ((2, "discussion", "asking"), (3, "social", "informing"))


def test_r_discussion_four_counts_with_their_lines() -> None:
    rows = [
        _att(1, True, intent="discussion", label="asking", peer=True),  # asking -> discussion
        _att(2, False, intent="asking", label="discussion", peer=True),  # discussion -> asking
        _att(3, False, intent="discussion", label="discussion", peer=True),  # correct
        _att(4, True, intent="asking", label="asking", peer=True),  # correct
        _att(5, False, rule=True, label="discussion", peer=True),  # not judged
        _att(6, True, intent="discussion"),  # asking -> discussion, not peer
    ]

    line = discussion_line(rows)

    assert line.asking_answered_discussion == (1, 6)
    assert line.discussion_answered_asking == (2,)
    assert line.peer_correct == (3, 4)
    assert line.peer_judged == (1, 2, 3, 4)


def test_r_rule_counts_rule_opened_clear_negatives_with_peer_lines_apart() -> None:
    rows = [
        _att(1, False, rule=True),
        _att(2, False, rule=True, peer=True, label="discussion"),
        _att(3, True, rule=True),  # a positive
        _att(4, False, rule=True),  # tracked
        _att(5, False, rule=True),  # ambiguous
        _att(6, False, intent="asking"),  # model, not rule
    ]

    lines, peer = rule_opened_negatives(
        rows, label_classes={5: "ambiguous"}, tracked={4: "label-review"}
    )

    assert (lines, peer) == ((1,), (2,))


def test_per_message_estimate_sum_max_and_not_computed() -> None:
    single = per_message_estimate(900, moderation_p95_ms=1200, serving="single")
    concurrent = per_message_estimate(900, moderation_p95_ms=1200, serving="concurrent")

    assert single.startswith("per-message estimate (single-occupancy lane): 2100 ms")
    assert concurrent.startswith("per-message estimate (concurrent lane): 1200 ms")
    assert per_message_estimate(900, moderation_p95_ms=None, serving="single") == (
        "per-message estimate: not computed (pass --moderation-p95-ms)"
    )
    assert "not computed" in per_message_estimate(None, moderation_p95_ms=1200, serving="single")


# --- the gates A1-A9 ----------------------------------------------------------------------------

_KINDS = {
    "tuning": "attention",
    "validation": "attention",
    "heldout": "attention",
    "fresh": "attention",
    "burst": "burst",
    "a6-source": "moderation",
}


def _spec(name: str, role: str, *, present: bool = True) -> SetSpec:
    return SetSpec(name=name, role=role, kind=_KINDS[role], path=Path(name) if present else None)


def _result(
    name: str,
    role: str,
    rows: list[Any],
    *,
    run_two: list[Any] | None = None,
    latencies: tuple[int, ...] | None = None,
    label_classes: dict[int, str] | None = None,
    tracked: dict[int, str] | None = None,
) -> SetResult:
    return SetResult(
        spec=_spec(name, role),
        runs=(tuple(rows), tuple(run_two if run_two is not None else rows)),
        latencies_ms=latencies if latencies is not None else (1000,) * len(rows) * 2,
        label_classes=label_classes or {},
        tracked=tracked or {},
    )


def _missing(name: str, role: str) -> SetResult:
    return SetResult(spec=_spec(name, role, present=False))


def _sample(*, opened: int = 0, missed: int = 0, declined: int = 10) -> list[AttentionRow]:
    """`declined` rule-declined clear positives, the first `missed` missed; one the rules catch;
    four clear negatives, the first `opened` model-opened."""
    rows = [
        _att(n, True, intent="discussion" if n <= missed else "asking")
        for n in range(1, declined + 1)
    ]
    rows.append(_att(declined + 1, True, rule=True))
    rows += [
        _att(declined + 1 + n, False, intent="asking" if n <= opened else "informing")
        for n in range(1, 5)
    ]
    return rows


def _burst_row(line: int, opener: str) -> BurstRow:
    return BurstRow(
        line=line,
        expected_needs_response=opener != "none",
        expected_opener=opener,
        rule_opens=opener == "rule",
        members=() if opener == "rule" else (MemberResult(intent="social"),),
    )


def _passing(**replace: SetResult) -> list[SetResult]:
    results = {
        "real": _result(
            "real-attention.jsonl",
            "tuning",
            [_att(1, True, intent="asking"), _att(2, False, intent="informing"), _att(3, True)],
            label_classes={1: "clear", 2: "clear", 3: "ambiguous"},
        ),
        "shipped": _result(
            "attention_smoke_fixtures.jsonl",
            "tuning",
            [_att(1, True, rule=True), _att(2, False, excluded="acknowledgement")],
        ),
        "validation": _result("attention_validation_fixtures.jsonl", "validation", _sample()),
        "heldout": _result("attention_heldout_fixtures.jsonl", "heldout", _sample()),
        "fresh": _result(
            "fresh-attention.jsonl",
            "fresh",
            [_att(1, True, intent="asking"), _att(2, False, intent="social")],
        ),
        # A burst mismatch is reported, never gated.
        "burst": _result(
            "attention_burst_fixtures.jsonl",
            "burst",
            [_burst_row(1, "rule"), _burst_row(2, "model")],
        ),
        "a6_real": _result(
            "real-moderation.jsonl",
            "a6-source",
            [ViolationRow(1, True, intent="offering"), ViolationRow(2, False)],
        ),
        "a6_shipped": _result(
            "moderation_smoke_fixtures.jsonl",
            "a6-source",
            [ViolationRow(1, True, intent="asking")],  # one is allowed
        ),
        "a6_policy": _result(
            "moderation_smoke_policy_fixtures.jsonl",
            "a6-source",
            [ViolationRow(1, True, excluded="acknowledgement")],
        ),
    }
    results.update(replace)
    return list(results.values())


def _gate(gates: tuple[GateLine, ...], name: str) -> GateLine:
    [line] = [gate for gate in gates if gate.gate == name]
    return line


def test_a_full_clean_run_passes_every_gate_and_qualifies() -> None:
    gates = evaluate_attention_gates(_passing(), repeat=2)

    assert [gate.gate for gate in gates] == [f"A{n}" for n in range(1, 10)]
    assert {gate.status for gate in gates} == {"PASS"}
    assert verdict(gates) == "QUALIFIED"
    assert exit_code_for(verdict(gates)) == 0


def test_a1_fails_on_one_tuning_clear_negative_the_model_opened() -> None:
    real = _result("real-attention.jsonl", "tuning", [_att(1, False, intent="asking")])

    gate = _gate(evaluate_attention_gates(_passing(real=real), repeat=2), "A1")

    assert gate.status == "FAIL"
    assert "real-attention.jsonl #1" in gate.detail


def test_a1_ignores_an_ambiguous_line_the_model_opened() -> None:
    real = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, False, intent="asking")],
        label_classes={1: "ambiguous"},
    )

    assert _gate(evaluate_attention_gates(_passing(real=real), repeat=2), "A1").status == "PASS"


@pytest.mark.parametrize(
    "missed", [_att(2, True, intent="discussion"), _att(2, True, excluded="acknowledgement")]
)
def test_a2_fails_on_one_missed_tuning_clear_positive(missed: AttentionRow) -> None:
    shipped = _result(
        "attention_smoke_fixtures.jsonl", "tuning", [_att(1, True, rule=True), missed]
    )

    gate = _gate(evaluate_attention_gates(_passing(shipped=shipped), repeat=2), "A2")

    assert gate.status == "FAIL"
    assert "attention_smoke_fixtures.jsonl #2" in gate.detail


@pytest.mark.parametrize(
    ("gate", "role", "name"),
    [
        ("A3", "validation", "attention_validation_fixtures.jsonl"),
        ("A4", "heldout", "attention_heldout_fixtures.jsonl"),
        ("A5", "fresh", "fresh-attention.jsonl"),
    ],
)
@pytest.mark.parametrize(
    ("sample", "status"),
    [
        ({"opened": 1}, "PASS"),
        ({"opened": 2}, "FAIL"),
        ({"missed": 1}, "PASS"),
        ({"missed": 2}, "FAIL"),
        ({"opened": 1, "missed": 1}, "PASS"),
    ],
)
def test_a3_to_a5_allow_one_of_each(
    gate: str, role: str, name: str, sample: dict[str, int], status: str
) -> None:
    key = {"validation": "validation", "heldout": "heldout", "fresh": "fresh"}[role]
    results = _passing(**{key: _result(name, role, _sample(**sample))})

    assert _gate(evaluate_attention_gates(results, repeat=2), gate).status == status


@pytest.mark.parametrize(("declined", "status"), [(10, "PASS"), (9, "FAIL")])
def test_a4_needs_at_least_ten_rule_declined_positives(declined: int, status: str) -> None:
    heldout = _result("attention_heldout_fixtures.jsonl", "heldout", _sample(declined=declined))

    gate = _gate(evaluate_attention_gates(_passing(heldout=heldout), repeat=2), "A4")

    assert gate.status == status
    assert gate.detail.endswith(f"of {declined}")


def test_a3_and_a5_need_no_minimum() -> None:
    thin = _sample(declined=2)
    results = _passing(
        validation=_result("attention_validation_fixtures.jsonl", "validation", thin),
        fresh=_result("fresh-attention.jsonl", "fresh", thin),
    )

    gates = evaluate_attention_gates(results, repeat=2)

    assert (_gate(gates, "A3").status, _gate(gates, "A5").status) == ("PASS", "PASS")


# --- A3, per validation set (T086; contract §5, 2026-10-09) -------------------------------------

_VALIDATION_SETS = (
    "attention_validation_fixtures.jsonl",
    "attention_validation_scope_fixtures.jsonl",
    "attention_heldout_v1_fixtures.jsonl",
)


def _with_validation(*validation: SetResult) -> list[SetResult]:
    """`_passing()` with its one validation set replaced by `validation`."""
    return [r for r in _passing() if r.spec.role != "validation"] + list(validation)


def _validation(samples: dict[str, dict[str, int]] | None = None) -> list[SetResult]:
    samples = samples or {}
    return [
        _result(name, "validation", _sample(**samples.get(name, {}))) for name in _VALIDATION_SETS
    ]


def test_a3_judges_each_validation_set_on_its_own() -> None:
    """One opened and one missed in every set: each passes, so A3 passes — pooled, the three sets
    would hold 3 / 3 and fail."""
    each = {name: {"opened": 1, "missed": 1} for name in _VALIDATION_SETS}

    gate = _gate(evaluate_attention_gates(_with_validation(*_validation(each)), repeat=2), "A3")

    assert gate.status == "PASS"


@pytest.mark.parametrize("failing", _VALIDATION_SETS)
@pytest.mark.parametrize("sample", [{"opened": 2}, {"missed": 2}])
def test_a3_fails_when_any_one_validation_set_fails(failing: str, sample: dict[str, int]) -> None:
    results = _with_validation(*_validation({failing: sample}))

    assert _gate(evaluate_attention_gates(results, repeat=2), "A3").status == "FAIL"


def test_a3_lists_each_validation_sets_counts_in_reading_order() -> None:
    samples = {
        "attention_validation_fixtures.jsonl": {"missed": 1},
        "attention_validation_scope_fixtures.jsonl": {"opened": 2},
    }

    gate = _gate(
        evaluate_attention_gates(_with_validation(*_validation(samples)), repeat=2), "A3"
    )

    assert gate.detail == (
        "attention_validation_fixtures.jsonl: model-opened 0; missed 1 (#1) of 10"
        " | attention_validation_scope_fixtures.jsonl: model-opened 2 (#12, #13); missed 0 of 10"
        " | attention_heldout_v1_fixtures.jsonl: model-opened 0; missed 0 of 10"
    )


def test_a3_is_not_run_while_a_validation_set_is_missing_and_fails_on_the_evidence() -> None:
    base, _, v1 = _validation()
    scope_missing = _missing("attention_validation_scope_fixtures.jsonl", "validation")

    gate = _gate(
        evaluate_attention_gates(_with_validation(base, scope_missing, v1), repeat=2), "A3"
    )
    assert gate.status == "NOT RUN"
    assert "attention_validation_scope_fixtures.jsonl: NOT RUN (missing)" in gate.detail

    failing = _result(_VALIDATION_SETS[0], "validation", _sample(opened=2))
    gate = _gate(
        evaluate_attention_gates(_with_validation(failing, scope_missing, v1), repeat=2), "A3"
    )
    assert gate.status == "FAIL"


def test_a4_and_a5_still_pool_their_sets() -> None:
    """Only A3 is per set: the held-out and fresh roles each hold one set."""
    gates = evaluate_attention_gates(_passing(), repeat=2)

    assert _gate(gates, "A4").detail == "model-opened 0; missed 0 of 10"


@pytest.mark.parametrize(("asking", "status"), [(1, "PASS"), (2, "FAIL")])
def test_a6_allows_one_violation_answered_asking_and_lists_them(asking: int, status: str) -> None:
    policy = _result(
        "moderation_smoke_policy_fixtures.jsonl",
        "a6-source",
        [ViolationRow(n, True, intent="asking" if n <= asking else "offering") for n in (1, 2, 3)],
    )
    shipped = _result(
        "moderation_smoke_fixtures.jsonl", "a6-source", [ViolationRow(1, True, intent="offering")]
    )

    gate = _gate(
        evaluate_attention_gates(_passing(a6_policy=policy, a6_shipped=shipped), repeat=2), "A6"
    )

    assert gate.status == status
    assert "moderation_smoke_policy_fixtures.jsonl #1" in gate.detail


def test_a6_is_not_run_without_the_real_moderation_set() -> None:
    gates = evaluate_attention_gates(
        _passing(a6_real=_missing("real-moderation.jsonl", "a6-source")), repeat=2
    )

    assert _gate(gates, "A6").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"


def test_a7_fails_when_the_second_run_differs_on_any_set_including_the_burst_set() -> None:
    burst = _result(
        "attention_burst_fixtures.jsonl",
        "burst",
        [_burst_row(1, "model")],
        run_two=[
            BurstRow(
                line=1,
                expected_needs_response=True,
                expected_opener="model",
                rule_opens=False,
                members=(MemberResult(intent="other"),),
            )
        ],
    )

    gate = _gate(evaluate_attention_gates(_passing(burst=burst), repeat=2), "A7")

    assert gate.status == "FAIL"
    assert "attention_burst_fixtures.jsonl #1" in gate.detail


def test_a7_needs_repeat_two() -> None:
    gates = evaluate_attention_gates(_passing(), repeat=1)

    assert _gate(gates, "A7").status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"
    assert exit_code_for(verdict(gates)) == 2


@pytest.mark.parametrize(("latency_ms", "status"), [(10_000, "PASS"), (10_001, "FAIL")])
def test_a8_p95_latency_at_ten_seconds(latency_ms: int, status: str) -> None:
    real = _result(
        "real-attention.jsonl",
        "tuning",
        [_att(1, True, intent="asking")],
        latencies=(latency_ms,) * 200,  # enough calls to set the p95 over every set's
    )

    assert _gate(evaluate_attention_gates(_passing(real=real), repeat=2), "A8").status == status


def test_a8_is_not_run_without_a_call() -> None:
    results = [
        SetResult(spec=r.spec, runs=r.runs, label_classes=r.label_classes) for r in _passing()
    ]

    assert _gate(evaluate_attention_gates(results, repeat=2), "A8").status == "NOT RUN"


@pytest.mark.parametrize(
    "row",
    [
        _att(1, True, error="ModelTimeoutError"),
        ViolationRow(1, True, error="ModelTimeoutError"),
        BurstRow(
            line=1,
            expected_needs_response=True,
            expected_opener="model",
            rule_opens=False,
            members=(MemberResult(intent="asking"), MemberResult(error="ModelTimeoutError")),
        ),
    ],
)
def test_a9_fails_on_an_error_in_any_set_including_the_burst_and_a6_sets(row: Any) -> None:
    role = (
        "burst"
        if isinstance(row, BurstRow)
        else "a6-source"
        if isinstance(row, ViolationRow)
        else "fresh"
    )
    name = {
        "burst": "attention_burst_fixtures.jsonl",
        "a6-source": "moderation_smoke_policy_fixtures.jsonl",
        "fresh": "fresh-attention.jsonl",
    }[role]
    key = {"burst": "burst", "a6-source": "a6_policy", "fresh": "fresh"}[role]

    gate = _gate(
        evaluate_attention_gates(_passing(**{key: _result(name, role, [row])}), repeat=2), "A9"
    )

    assert gate.status == "FAIL"
    assert f"{name} #1" in gate.detail


@pytest.mark.parametrize(
    ("key", "name", "role", "gate"),
    [
        ("real", "real-attention*.jsonl", "tuning", "A1"),
        ("validation", "attention_validation_fixtures.jsonl", "validation", "A3"),
        ("heldout", "attention_heldout_fixtures.jsonl", "heldout", "A4"),
        ("fresh", "fresh-attention.jsonl", "fresh", "A5"),
    ],
)
def test_a_missing_required_set_is_not_run_and_incomplete(
    key: str, name: str, role: str, gate: str
) -> None:
    gates = evaluate_attention_gates(_passing(**{key: _missing(name, role)}), repeat=2)

    assert _gate(gates, gate).status == "NOT RUN"
    assert verdict(gates) == "INCOMPLETE"


def test_a_missing_burst_set_is_not_required() -> None:
    gates = evaluate_attention_gates(
        _passing(burst=_missing("attention_burst_fixtures.jsonl", "burst")), repeat=2
    )

    assert verdict(gates) == "QUALIFIED"


def test_evidence_of_failure_fails_a_gate_even_with_a_set_missing() -> None:
    shipped = _result("attention_smoke_fixtures.jsonl", "tuning", [_att(1, False, intent="asking")])

    gates = evaluate_attention_gates(
        _passing(real=_missing("real-attention*.jsonl", "tuning"), shipped=shipped), repeat=2
    )

    assert _gate(gates, "A1").status == "FAIL"
    assert verdict(gates) == "NOT QUALIFIED"
    assert exit_code_for(verdict(gates)) == 1


def test_a_candidate_is_candidate_with_every_gate_computed() -> None:
    gates = evaluate_attention_gates(_passing(), repeat=2)

    assert {gate.status for gate in gates} == {"PASS"}
    assert verdict(gates, candidate=True) == "CANDIDATE"
    assert exit_code_for(verdict(gates, candidate=True)) == 3


# --- the report (§7): counts and line numbers, never text ---------------------------------------


def _report(results: list[SetResult], **kwargs: Any) -> list[str]:
    return format_attention_report(
        results,
        evaluate_attention_gates(results, repeat=2),
        profile="ollama-gemma4-e2b-attention",
        model="gemma4:e2b-it-qat",
        prompt=kwargs.pop("prompt", "attention_v1"),
        repeat=2,
        **kwargs,
    )


def test_the_report_prints_the_header_every_gate_reported_line_and_the_verdict() -> None:
    lines = _report(_passing(), moderation_p95_ms=1200)

    assert lines[0] == (
        "qualify-attention: profile=ollama-gemma4-e2b-attention model=gemma4:e2b-it-qat "
        "prompt=attention_v1 repeat=2"
    )
    for n in range(1, 10):
        assert any(line.startswith(f"A{n} ") for line in lines), f"A{n} missing"
    for prefix in ("R-ambiguous:", "R-intent:", "R-discussion:", "R-rule:", "R-burst #1:"):
        assert any(line.startswith(prefix) for line in lines), f"{prefix} missing"
    assert "R-burst #2: opener=none member=- expected=model MISMATCH" in lines
    assert any(
        line.startswith("A6 source: violation lines 1; answered asking 1 (#1)") for line in lines
    )
    assert any(
        line.startswith("per-message estimate (single-occupancy lane): 2200 ms") for line in lines
    )
    assert lines[-1] == "result: QUALIFIED"


def test_a_candidate_report_names_its_hash_and_withheld_sets() -> None:
    heldout = SetResult(
        spec=SetSpec("attention_heldout_fixtures.jsonl", "heldout", "attention", withheld=True)
    )

    lines = _report(_passing(heldout=heldout), prompt=f"CANDIDATE {'a' * 64}", candidate=True)

    assert lines[0].endswith(f"prompt=CANDIDATE {'a' * 64} repeat=2")
    assert (
        "== attention_heldout_fixtures.jsonl (heldout) — NOT RUN: withheld in candidate mode =="
        in lines
    )
    assert lines[-1] == "result: CANDIDATE"


def test_the_report_carries_no_arabic_character_and_no_fixture_text() -> None:
    lines = _report(_passing(), moderation_p95_ms=1200, serving="concurrent")

    assert lines
    assert not [line for line in lines if _ARABIC.search(line) or _SENTINEL in line]
