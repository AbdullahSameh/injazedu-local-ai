"""`python -m app.scripts.qualify_moderation` — TG-M5.2's model qualification
(`specs/010-tg-m5-2-classify-v3/contracts/qualification.md`).

Judges one model profile and instruction pair over every benchmark set and prints whether it may run
AI-assisted Attention in production: `QUALIFIED`, `NOT QUALIFIED` or `INCOMPLETE`. A composition
root, like the smokes it reuses. It writes nothing and never prints a fixture's text.

`--profile NAME` names a `role = 'moderation'` profile, active or not (D-TG-161); `--prompt` an
allowlisted instruction (default: `MODERATION_PROMPT_VERSION`); `--fixtures-dir` the operator's
directory outside the repository; `--repeat` how many times every set is judged (default 2, and at
least 2 for `QUALIFIED`). Each fixture is judged through the smokes' own per-fixture functions
(D-TG-178) on a bare `Gateway`, which records no accounting. Exit code: 0 qualified, 1 not
qualified, 2 incomplete or a usage error (C5).

A benchmark fixture line is JSONL (data-model §1). Two optional keys ride on it, and every existing
key keeps its meaning (D-TG-177):
- `label_class`, attention sets only: `clear` (the default) or `ambiguous` — reported, never gated;
- `tracked`, any set: `no-link-rule` or `label-review` — a tracked boundary case (D-TG-176).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.errors import GatewayError
from app.application.gateway.gateway import Gateway
from app.application.moderation.classification import PROMPT_VERSIONS
from app.domain.moderation.classification import quantise
from app.infrastructure.config import load_settings
from app.scripts.smoke_attention import AttentionRow, judge_attention_fixture
from app.scripts.smoke_attention import format_row as format_attention_row
from app.scripts.smoke_attention import format_summary as format_attention_summary
from app.scripts.smoke_attention import summarise as summarise_attention
from app.scripts.smoke_moderation import (
    SmokeRow,
    SmokeSummary,
    _fail_if_unreachable,
    _PinnedRegistry,
    judge_moderation_fixture,
)
from app.scripts.smoke_moderation import format_row as format_moderation_row
from app.scripts.smoke_moderation import format_summary as format_moderation_summary
from app.scripts.smoke_moderation import summarise as summarise_moderation

LABEL_CLASSES: tuple[str, ...] = ("clear", "ambiguous")
TRACKED_DISPOSITIONS: tuple[str, ...] = ("no-link-rule", "label-review")
# The closed list (FR-212, Q12): more tracked lines than this in one run fails qualification.
TRACKED_LIMIT = 2

_KINDS: tuple[str, ...] = ("attention", "moderation")
_LABEL_KEYS: dict[str, tuple[str, ...]] = {
    "attention": ("text", "needs_response"),
    "moderation": ("text", "category", "needs_moderation"),
}


class FixtureError(Exception):
    """A fixture line the qualification refuses. Its message names the set and the line, never
    the text."""


def load_fixture_lines(path: Path, kind: str) -> list[tuple[int, dict[str, Any]]]:
    """Every non-blank line of `path` as `(#N, fixture)`, numbered from 1 exactly as the smokes
    number them. An attention fixture always comes back with its `label_class`, `clear` when the
    line carries none. Raises `FixtureError` on a line that is not JSON, lacks a label key, or
    carries a key value outside the closed vocabularies."""
    if kind not in _KINDS:
        raise ValueError(f"unknown fixture kind {kind!r}")
    raw_lines = [raw for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]
    loaded: list[tuple[int, dict[str, Any]]] = []
    for line, raw in enumerate(raw_lines, start=1):
        where = f"{path.name} #{line}"
        try:
            fixture = json.loads(raw)
        except json.JSONDecodeError:
            raise FixtureError(f"{where}: not a JSON object") from None
        if not isinstance(fixture, dict):
            raise FixtureError(f"{where}: not a JSON object")
        missing = [name for name in _LABEL_KEYS[kind] if name not in fixture]
        if missing:
            raise FixtureError(f"{where}: missing {', '.join(missing)}")
        if kind == "moderation" and "label_class" in fixture:
            raise FixtureError(f"{where}: label_class is for attention sets only")
        if kind == "attention":
            label_class = fixture.setdefault("label_class", "clear")
            if label_class not in LABEL_CLASSES:
                raise FixtureError(
                    f"{where}: label_class must be one of {', '.join(LABEL_CLASSES)}"
                )
        if "tracked" in fixture and fixture["tracked"] not in TRACKED_DISPOSITIONS:
            raise FixtureError(f"{where}: tracked must be one of {', '.join(TRACKED_DISPOSITIONS)}")
        loaded.append((line, fixture))
    return loaded


# --- the sets, their results, and scoring S1-S6 (contracts/qualification.md §2-§3) --------------

Row = AttentionRow | SmokeRow

ROLE_TUNING = "tuning"
ROLE_HELDOUT = "heldout"
ROLE_FRESH = "fresh"
ROLE_MODERATION_REAL = "moderation-real"
ROLE_MODERATION_SHIPPED = "moderation-shipped"
ROLE_MODERATION_POLICY = "moderation-policy"

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"
QUALIFIED = "QUALIFIED"
NOT_QUALIFIED = "NOT QUALIFIED"
INCOMPLETE = "INCOMPLETE"
_EXIT_CODES: dict[str, int] = {QUALIFIED: 0, NOT_QUALIFIED: 1, INCOMPLETE: 2}

# Q10 (D-TG-179): a p95 single call at or under this lands a queue of about 8 within the settle.
LATENCY_P95_LIMIT_MS = 10_000
# Q4's "out of 10 or more": a thinner held-out set cannot show a miss rate.
HELDOUT_MIN_RULE_DECLINED = 10
# S1: a clear positive nobody opens.
_MISSED_OPENERS: tuple[str, ...] = ("none", "excluded")


@dataclass(frozen=True)
class SetSpec:
    """One benchmark set the qualification reads (data-model §2). `path` is `None` when the set is
    missing, and its gates are then `NOT RUN`."""

    name: str
    role: str
    kind: str
    path: Path | None = None


@dataclass(frozen=True)
class SetResult:
    """One set's judged rows, once per run, every model call's latency across all runs, and the
    fixtures' annotations by line number. It holds no text."""

    spec: SetSpec
    runs: tuple[tuple[Row, ...], ...] = ()
    latencies_ms: tuple[int, ...] = ()
    label_classes: Mapping[int, str] = field(default_factory=dict)
    tracked: Mapping[int, str] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return bool(self.runs)

    @property
    def first(self) -> tuple[Row, ...]:
        return self.runs[0] if self.runs else ()


@dataclass(frozen=True)
class ClassSplit:
    """S1 over one attention set's first run, tracked lines left out. Ambiguous lines are
    reported, never gated."""

    clear_positives: int
    clear_positives_missed: tuple[int, ...]
    clear_negatives: int
    clear_negatives_model_opened: tuple[int, ...]
    rule_declined_positives: int
    rule_declined_positives_missed: tuple[int, ...]
    ambiguous: int
    ambiguous_answered_true: tuple[int, ...]
    ambiguous_agreed: int


@dataclass(frozen=True)
class TrackedLine:
    """S3: a tracked boundary case on the first run, and whether the model got it right."""

    set_name: str
    line: int
    disposition: str
    passed: bool


@dataclass(frozen=True)
class GateLine:
    gate: str
    name: str
    status: str
    detail: str


def fixture_annotations(
    fixtures: Sequence[tuple[int, Mapping[str, Any]]],
) -> tuple[dict[int, str], dict[int, str]]:
    """`(label classes, tracked dispositions)`, each by line number — all a result keeps of its
    fixtures besides the labels its rows already carry."""
    label_classes = {line: f["label_class"] for line, f in fixtures if "label_class" in f}
    tracked = {line: f["tracked"] for line, f in fixtures if "tracked" in f}
    return label_classes, tracked


_SHIPPED_DIR = Path(__file__).resolve().parent
_REAL_ATTENTION_GLOB = "real-attention*.jsonl"


def discover_sets(fixtures_dir: Path, *, shipped_dir: Path = _SHIPPED_DIR) -> list[SetSpec]:
    """Every set the qualification reads, in reading order (data-model §2, contract §2): the
    operator's real attention sets (sorted) and the shipped one as tuning; the held-out set; the
    fresh sample; then the real, shipped and policy moderation sets. A set that is not there comes
    back without a path; with no real attention set at all, one placeholder stands for them."""

    def at(directory: Path, name: str, role: str, kind: str) -> SetSpec:
        path = directory / name
        return SetSpec(name=name, role=role, kind=kind, path=path if path.is_file() else None)

    real_attention = [
        SetSpec(name=path.name, role=ROLE_TUNING, kind="attention", path=path)
        for path in sorted(fixtures_dir.glob(_REAL_ATTENTION_GLOB))
        if path.is_file()
    ] or [SetSpec(name=_REAL_ATTENTION_GLOB, role=ROLE_TUNING, kind="attention")]
    return [
        *real_attention,
        at(shipped_dir, "attention_smoke_fixtures.jsonl", ROLE_TUNING, "attention"),
        at(shipped_dir, "attention_smoke_heldout_fixtures.jsonl", ROLE_HELDOUT, "attention"),
        at(fixtures_dir, "fresh-attention.jsonl", ROLE_FRESH, "attention"),
        at(fixtures_dir, "real-moderation.jsonl", ROLE_MODERATION_REAL, "moderation"),
        at(shipped_dir, "moderation_smoke_fixtures.jsonl", ROLE_MODERATION_SHIPPED, "moderation"),
        at(
            shipped_dir,
            "moderation_smoke_policy_fixtures.jsonl",
            ROLE_MODERATION_POLICY,
            "moderation",
        ),
    ]


def _attention_rows(rows: Sequence[Row]) -> list[AttentionRow]:
    return [row for row in rows if isinstance(row, AttentionRow)]


def _moderation_rows(rows: Sequence[Row]) -> list[SmokeRow]:
    return [row for row in rows if isinstance(row, SmokeRow)]


def split_by_label_class(
    rows: Sequence[AttentionRow],
    *,
    label_classes: Mapping[int, str],
    tracked: Mapping[int, str],
) -> ClassSplit:
    """S1. A clear positive is missed when nobody opens it (`none` or `excluded`); an error is
    never scored as a miss (S4). A clear negative counts only when the model is its opener. A line
    with no `label_class` is clear."""
    gated = [row for row in rows if row.line not in tracked]
    clear = [row for row in gated if label_classes.get(row.line, "clear") == "clear"]
    ambiguous = [row for row in gated if label_classes.get(row.line, "clear") == "ambiguous"]
    positives = [row for row in clear if row.expected_needs_response]
    negatives = [row for row in clear if not row.expected_needs_response]
    declined = [row for row in positives if not row.rule_opens]
    return ClassSplit(
        clear_positives=len(positives),
        clear_positives_missed=tuple(r.line for r in positives if r.opener in _MISSED_OPENERS),
        clear_negatives=len(negatives),
        clear_negatives_model_opened=tuple(r.line for r in negatives if r.opener == "model"),
        rule_declined_positives=len(declined),
        rule_declined_positives_missed=tuple(
            r.line for r in declined if r.opener in _MISSED_OPENERS
        ),
        ambiguous=len(ambiguous),
        ambiguous_answered_true=tuple(
            r.line for r in ambiguous if r.scored and r.predicted_needs_response
        ),
        ambiguous_agreed=sum(1 for r in ambiguous if r.matched),
    )


def moderation_gated(rows: Sequence[SmokeRow], *, tracked: Mapping[int, str]) -> SmokeSummary:
    """S2: the smoke's own scoring over the lines that are not tracked."""
    return summarise_moderation([row for row in rows if row.line not in tracked])


def _tracked_passed(row: Row) -> bool:
    if row.error is not None:
        return False
    if isinstance(row, SmokeRow):
        return row.predicted_needs_moderation == row.expected_needs_moderation
    if row.expected_needs_response:
        return row.opener not in _MISSED_OPENERS
    return row.opener != "model"


def tracked_lines(result: SetResult) -> tuple[TrackedLine, ...]:
    """S3, on the first run: a moderation line passes when needs-moderation agrees; an attention
    line passes when it is opened as its label says."""
    return tuple(
        TrackedLine(result.spec.name, row.line, result.tracked[row.line], _tracked_passed(row))
        for row in result.first
        if row.line in result.tracked
    )


def _signature(row: Row) -> tuple[bool | None, bool | None, str | None, str | None]:
    return (
        row.predicted_needs_response,
        row.predicted_needs_moderation,
        row.predicted_category,
        row.route,
    )


def compare_runs(runs: Sequence[Sequence[Row]]) -> tuple[int, ...]:
    """S5: the lines on which any later run differs from the first in predicted needs-response,
    needs-moderation, category or route. A line that failed in one run and not another differs."""
    if len(runs) < 2:
        return ()
    first = {row.line: _signature(row) for row in runs[0]}
    return tuple(
        sorted(
            {
                row.line
                for later in runs[1:]
                for row in later
                if first.get(row.line) != _signature(row)
            }
        )
    )


def latency_percentiles(latencies_ms: Sequence[int]) -> tuple[int, int] | None:
    """S6: `(median, p95)` in milliseconds — the p95 by nearest rank, so always a measured call —
    or `None` when no call was made."""
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return round(statistics.median(ordered)), p95


# --- the gate Q1-Q12 and the verdict (§4) -------------------------------------------------------


def _split(result: SetResult) -> ClassSplit:
    return split_by_label_class(
        _attention_rows(result.first), label_classes=result.label_classes, tracked=result.tracked
    )


def _refs(refs: Sequence[tuple[str, int]]) -> str:
    """`N` or `N (set #a, #b; other #c)` — set names and line numbers only."""
    if not refs:
        return "0"
    grouped: dict[str, list[int]] = {}
    for name, line in refs:
        grouped.setdefault(name, []).append(line)
    parts = "; ".join(
        f"{name} " + ", ".join(f"#{line}" for line in lines) for name, lines in grouped.items()
    )
    return f"{len(refs)} ({parts})"


def _status(failed: bool, sets: Sequence[SetResult]) -> str:
    """`FAIL` on the evidence that ran, whatever else is missing; then `NOT RUN` when a set the
    gate needs is missing; else `PASS`."""
    if failed:
        return FAIL
    if not sets or not all(result.ran for result in sets):
        return NOT_RUN
    return PASS


def _moderation_gate(gate: str, name: str, sets: Sequence[SetResult]) -> GateLine:
    misses: list[tuple[str, int]] = []
    alarms: list[tuple[str, int]] = []
    for result in sets:
        summary = moderation_gated(_moderation_rows(result.first), tracked=result.tracked)
        misses += [(result.spec.name, line) for line in summary.false_negatives]
        alarms += [(result.spec.name, line) for line in summary.false_positives]
    return GateLine(
        gate,
        name,
        _status(bool(misses or alarms), sets),
        f"false negatives {_refs(misses)}; false positives {_refs(alarms)}",
    )


def evaluate_gate(results: Sequence[SetResult], *, repeat: int) -> tuple[GateLine, ...]:
    """Q1-Q12, every one a hard gate (§4). Ambiguous lines and category agreement are reported
    only and never reach here."""

    def of_role(role: str) -> list[SetResult]:
        return [result for result in results if result.spec.role == role]

    def refs(sets: Sequence[SetResult], field_name: str) -> list[tuple[str, int]]:
        return [
            (result.spec.name, line)
            for result in sets
            if result.ran
            for line in getattr(_split(result), field_name)
        ]

    tuning, heldout, fresh = of_role(ROLE_TUNING), of_role(ROLE_HELDOUT), of_role(ROLE_FRESH)
    policy = of_role(ROLE_MODERATION_POLICY)
    ran = [result for result in results if result.ran]

    q1 = refs(tuning, "clear_negatives_model_opened")
    q2 = refs(heldout, "clear_negatives_model_opened")
    q3 = refs(tuning, "clear_positives_missed")
    q4 = refs(heldout, "rule_declined_positives_missed")
    q4_out_of = sum(_split(result).rule_declined_positives for result in heldout if result.ran)
    q4_thin = (
        bool(heldout) and all(r.ran for r in heldout) and q4_out_of < HELDOUT_MIN_RULE_DECLINED
    )
    q9_opened = refs(fresh, "clear_negatives_model_opened")
    q9_missed = refs(fresh, "rule_declined_positives_missed")

    policy_misses: list[tuple[str, int]] = []
    policy_alarms: list[tuple[str, int]] = []
    policy_incidents: list[tuple[str, int]] = []
    for result in policy:
        rows = [r for r in _moderation_rows(result.first) if r.line not in result.tracked]
        summary = summarise_moderation(rows)
        policy_misses += [(result.spec.name, line) for line in summary.false_negatives]
        policy_alarms += [(result.spec.name, line) for line in summary.false_positives]
        policy_incidents += [
            (result.spec.name, row.line)
            for row in rows
            if not row.expected_needs_moderation
            and row.route is not None
            and row.route.split("/", 1)[0] == "incident"
        ]

    differing = [(result.spec.name, line) for result in ran for line in compare_runs(result.runs)]
    latency = latency_percentiles([ms for result in ran for ms in result.latencies_ms])
    errors = sorted(
        {
            (result.spec.name, row.line)
            for result in ran
            for run in result.runs
            for row in run
            if row.error is not None
        },
        key=lambda ref: ([r.spec.name for r in ran].index(ref[0]), ref[1]),
    )
    tracked = [line for result in ran for line in tracked_lines(result)]
    tracked_refused = [t for t in tracked if t.disposition not in TRACKED_DISPOSITIONS]

    if repeat < 2:
        q8 = GateLine("Q8", "repeat: 0 differing lines", NOT_RUN, f"--repeat {repeat}: needs 2")
    else:
        q8 = GateLine(
            "Q8", "repeat: 0 differing lines", _status(bool(differing), ran), _refs(differing)
        )
    if latency is None:
        q10 = GateLine("Q10", f"latency p95 <= {LATENCY_P95_LIMIT_MS} ms", NOT_RUN, "no call")
    else:
        median, p95 = latency
        q10 = GateLine(
            "Q10",
            f"latency p95 <= {LATENCY_P95_LIMIT_MS} ms",
            FAIL if p95 > LATENCY_P95_LIMIT_MS else PASS,
            f"p95 {p95} ms, median {median} ms",
        )

    return (
        GateLine(
            "Q1", "tuning clear negatives model-opened = 0", _status(bool(q1), tuning), _refs(q1)
        ),
        GateLine(
            "Q2",
            "held-out clear negatives model-opened <= 1",
            _status(len(q2) > 1, heldout),
            _refs(q2),
        ),
        GateLine("Q3", "tuning clear positives missed = 0", _status(bool(q3), tuning), _refs(q3)),
        GateLine(
            "Q4",
            f"held-out rule-declined clear positives missed <= 1 of >= {HELDOUT_MIN_RULE_DECLINED}",
            _status(len(q4) > 1 or q4_thin, heldout),
            f"{_refs(q4)} of {q4_out_of}",
        ),
        _moderation_gate(
            "Q5",
            "real moderation, tracked out: false negatives = 0, false positives = 0",
            of_role(ROLE_MODERATION_REAL),
        ),
        _moderation_gate(
            "Q6",
            "shipped moderation, tracked out: false negatives = 0, false positives = 0",
            of_role(ROLE_MODERATION_SHIPPED),
        ),
        GateLine(
            "Q7",
            "policy moderation: false negatives <= 1, false positives = 0, "
            "legitimate -> incident = 0",
            _status(len(policy_misses) > 1 or bool(policy_alarms or policy_incidents), policy),
            f"false negatives {_refs(policy_misses)}; false positives {_refs(policy_alarms)}; "
            f"legitimate -> incident {_refs(policy_incidents)}",
        ),
        q8,
        GateLine(
            "Q9",
            "fresh sample: clear negatives model-opened <= 1, rule-declined positives missed <= 1",
            _status(len(q9_opened) > 1 or len(q9_missed) > 1, fresh),
            f"model-opened {_refs(q9_opened)}; missed {_refs(q9_missed)}",
        ),
        q10,
        GateLine("Q11", "errors = 0", FAIL if errors else PASS, _refs(errors)),
        GateLine(
            "Q12",
            f"tracked lines <= {TRACKED_LIMIT}, each {' or '.join(TRACKED_DISPOSITIONS)}",
            FAIL if len(tracked) > TRACKED_LIMIT or tracked_refused else PASS,
            _refs([(t.set_name, t.line) for t in tracked]),
        ),
    )


def verdict(gates: Sequence[GateLine]) -> str:
    """Any `FAIL` is `NOT QUALIFIED`; otherwise any `NOT RUN` is `INCOMPLETE`; else `QUALIFIED`."""
    statuses = {gate.status for gate in gates}
    if FAIL in statuses:
        return NOT_QUALIFIED
    if NOT_RUN in statuses:
        return INCOMPLETE
    return QUALIFIED


def exit_code_for(result: str) -> int:
    """C5: 0 qualified, 1 not qualified, 2 incomplete."""
    return _EXIT_CODES[result]


# --- the printed report (§5): counts, set names and line numbers — never text ------------------


def _numbered(lines: Sequence[int]) -> str:
    return f"{len(lines)}" + (f" ({', '.join(f'#{n}' for n in lines)})" if lines else "")


def _set_block(result: SetResult) -> list[str]:
    if result.spec.kind == "attention":
        rows = _attention_rows(result.first)
        split = _split(result)
        block = format_attention_summary(summarise_attention(rows))
        block.append(
            f"label class: clear positives {split.clear_positives}, missed "
            f"{_numbered(split.clear_positives_missed)}; rule-declined clear positives "
            f"{split.rule_declined_positives}, missed "
            f"{_numbered(split.rule_declined_positives_missed)}; "
            f"clear negatives {split.clear_negatives}, model-opened "
            f"{_numbered(split.clear_negatives_model_opened)}; ambiguous {split.ambiguous}: "
            f"answered true {_numbered(split.ambiguous_answered_true)}, agreed "
            f"{split.ambiguous_agreed}/{split.ambiguous} (reported, never gated)"
        )
    else:
        moderation = _moderation_rows(result.first)
        gated = moderation_gated(moderation, tracked=result.tracked)
        block = format_moderation_summary(summarise_moderation(moderation))
        block.append(
            f"gated, tracked out: false negatives {_numbered(gated.false_negatives)}; "
            f"false positives {_numbered(gated.false_positives)}; legitimate -> incident "
            f"{gated.legitimate_routes['incident']}"
        )
    block += [
        f"tracked: {t.set_name} #{t.line} {t.disposition} {PASS if t.passed else FAIL}"
        for t in tracked_lines(result)
    ]
    return block


def format_report(
    results: Sequence[SetResult],
    gates: Sequence[GateLine],
    *,
    profile: str,
    model: str,
    prompt: str,
    floor: object,
    threshold: object,
    repeat: int,
) -> list[str]:
    """The header, each set's summary (the smoke's own lines, then S1's split and the tracked
    lines), latency, repeat, the gate table and the verdict — the per-line detail is printed while
    the first run is judged."""
    lines = [
        f"qualify-moderation: profile={profile} model={model} prompt={prompt} floor={floor} "
        f"threshold={threshold} repeat={repeat}"
    ]
    for result in results:
        lines.append("")
        if not result.ran:
            lines.append(f"== {result.spec.name} ({result.spec.role}) — NOT RUN: missing ==")
            continue
        lines.append(f"== {result.spec.name} ({result.spec.role}) ==")
        lines += _set_block(result)

    ran = [result for result in results if result.ran]
    calls = [ms for result in ran for ms in result.latencies_ms]
    latency = latency_percentiles(calls)
    lines.append("")
    lines.append(
        f"latency: median={latency[0]} ms p95={latency[1]} ms over {len(calls)} calls"
        if latency is not None
        else "latency: no model call"
    )
    if repeat < 2:
        lines.append(f"repeat: {repeat} run, not compared")
    else:
        differing = [(r.spec.name, line) for r in ran for line in compare_runs(r.runs)]
        count, _, named = _refs(differing).partition(" ")
        lines.append(
            f"repeat: {repeat} runs, {count} differing lines" + (f" {named}" if named else "")
        )

    lines.append("")
    lines += [f"{gate.gate} {gate.status} — {gate.name}: {gate.detail}" for gate in gates]
    lines.append("")
    lines.append(f"result: {verdict(gates)}")
    return lines


# --- the command (§1) ---------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qualify_moderation", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    parser.add_argument(
        "--profile", required=True, help="A moderation model profile, active or not (D-TG-161)."
    )
    parser.add_argument(
        "--prompt",
        default=None,
        choices=PROMPT_VERSIONS,
        help="The instruction to qualify (default: MODERATION_PROMPT_VERSION).",
    )
    parser.add_argument(
        "--fixtures-dir", required=True, help="The operator's fixtures, outside the repository."
    )
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        default=2,
        help="Judge every set this many times (default 2; QUALIFIED needs at least 2).",
    )
    return parser.parse_args(argv)


def load_sets(specs: Sequence[SetSpec]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """Every present set's validated lines, by set name — all of them before any model call, so a
    bad line stops the run before it starts."""
    return {
        spec.name: load_fixture_lines(spec.path, spec.kind)
        for spec in specs
        if spec.path is not None
    }


def _report_error(line: int, error: str) -> None:
    # The error's class name only: a gateway error's message can carry the model's raw output (C3).
    print(f"  ERROR #{line}: {error}", file=sys.stderr)


async def judge_sets(
    gateway: Gateway,
    specs: Sequence[SetSpec],
    loaded: Mapping[str, Sequence[tuple[int, dict[str, Any]]]],
    *,
    prompt_version: str,
    floor: Decimal,
    threshold: Decimal,
    repeat: int,
) -> list[SetResult]:
    """Judges every present set `repeat` times, all sets once per run (S5), through the smokes'
    per-fixture functions. Prints the smokes' per-line detail for the first run only, and every
    error by its class name; a missing set comes back with no run."""
    runs: dict[str, list[tuple[Row, ...]]] = {name: [] for name in loaded}
    latencies: dict[str, list[int]] = {name: [] for name in loaded}

    for run in range(1, repeat + 1):
        for spec in specs:
            if spec.name not in loaded:
                continue
            if run == 1:
                print(f"== {spec.name} ({spec.role}) run 1 of {repeat} ==")
            else:
                print(f"-- {spec.name} ({spec.role}) run {run} of {repeat}")
            rows: list[Row] = []
            for line, fixture in loaded[spec.name]:
                row: Row
                if spec.kind == "attention":
                    row, latency_ms = await judge_attention_fixture(
                        gateway,
                        fixture,
                        line=line,
                        prompt_version=prompt_version,
                        floor=floor,
                        threshold=threshold,
                    )
                    detail = format_attention_row(row, latency_ms) if run == 1 else None
                else:
                    row, latency_ms = await judge_moderation_fixture(
                        gateway,
                        fixture,
                        line=line,
                        prompt_version=prompt_version,
                        floor=floor,
                        threshold=threshold,
                    )
                    detail = format_moderation_row(row, latency_ms) if run == 1 else None
                rows.append(row)
                if latency_ms is not None:
                    latencies[spec.name].append(latency_ms)
                if row.error is not None:
                    _report_error(line, row.error)
                elif detail is not None:
                    print(detail)
            runs[spec.name].append(tuple(rows))

    results: list[SetResult] = []
    for spec in specs:
        if spec.name not in loaded:
            results.append(SetResult(spec=spec))
            continue
        label_classes, tracked = fixture_annotations(loaded[spec.name])
        results.append(
            SetResult(
                spec=spec,
                runs=tuple(runs[spec.name]),
                latencies_ms=tuple(latencies[spec.name]),
                label_classes=label_classes,
                tracked=tracked,
            )
        )
    return results


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)
    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.is_dir():
        print(f"qualify-moderation: no fixtures directory at {fixtures_dir}", file=sys.stderr)
        return 2
    specs = discover_sets(fixtures_dir)
    try:
        loaded = load_sets(specs)
    except FixtureError as exc:
        print(f"qualify-moderation: {exc}", file=sys.stderr)
        return 2

    settings = load_settings()
    prompt_version: str = args.prompt or settings.moderation_prompt_version
    floor = quantise(settings.moderation_confidence_floor)
    threshold = quantise(settings.moderation_incident_confidence)
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = _PinnedRegistry(session_factory, profile_name=args.profile)

    try:
        try:
            profile = await registry.resolve("moderation")
        except GatewayError as exc:
            print(f"qualify-moderation: {exc}", file=sys.stderr)
            return 2
        if profile.role != "moderation":
            print(
                f"qualify-moderation: profile {profile.name!r} has role {profile.role!r}, "
                "not 'moderation'",
                file=sys.stderr,
            )
            return 2
        if profile.base_url:
            try:
                await _fail_if_unreachable(profile.base_url)
            except SystemExit:
                return 2  # an unreachable runtime is no verdict on the model

        print(
            f"qualify-moderation: profile={profile.name} model={profile.model} "
            f"prompt={prompt_version} floor={floor} threshold={threshold} repeat={args.repeat}"
        )
        results = await judge_sets(
            Gateway(registry),  # type: ignore[arg-type]
            specs,
            loaded,
            prompt_version=prompt_version,
            floor=floor,
            threshold=threshold,
            repeat=args.repeat,
        )
    finally:
        await engine.dispose()

    gates = evaluate_gate(results, repeat=args.repeat)
    print()
    for report_line in format_report(
        results,
        gates,
        profile=profile.name,
        model=profile.model,
        prompt=prompt_version,
        floor=floor,
        threshold=threshold,
        repeat=args.repeat,
    ):
        print(report_line)
    return exit_code_for(verdict(gates))


def main() -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:])))


if __name__ == "__main__":
    main()
