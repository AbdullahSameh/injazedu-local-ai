"""The qualification's task-agnostic core (`specs/011-tg-m5-3-attention-judgement/contracts/
qualification.md` version 2, D-TG-194): fixture lines and their keys, the sets, the judging loop,
repeat, latency, gate statuses, the verdict, the exit code, and the no-text formatting every suite
shares.

Moved from `qualify_moderation.py` (version 1) with no behaviour change, plus version 2's fixture
keys (§3: `intent`, `peer`, `burst`, `expected_opener`), the `CANDIDATE` verdict (C6) and its exit
code 3. It knows no task: each suite brings its own sets, per-fixture judgement, scoring and gates,
so neither suite is a second definition of sets, repeat, latency or verdicts.

A benchmark fixture line is JSONL. Version 1's keys keep their meaning (010 data-model §1):
- `label_class`, attention sets only: `clear` (the default) or `ambiguous` — reported, never gated;
- `tracked`, any set: `no-link-rule` or `label-review` — a tracked boundary case (D-TG-176).

Version 2 adds (data-model §8, D-TG-193):
- `intent`, attention sets only: one of the six, and `asking` exactly when `needs_response` (V1);
- `peer`, attention sets only: `true`, a flag (V2);
- `burst` (2-5 texts, replacing `text`) and `expected_opener` (`rule` | `model` | `none`): the
  burst set only, and both required there (V3).

Any violation is a `FixtureError` naming the set and the line, never the text (V4).
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections.abc import Awaitable, Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain.moderation.attention_judgement import INTENTS, needs_response_for

# The in-repository benchmark sets live beside the smokes, in `app/scripts/`.
SHIPPED_DIR = Path(__file__).resolve().parent.parent

LABEL_CLASSES: tuple[str, ...] = ("clear", "ambiguous")
TRACKED_DISPOSITIONS: tuple[str, ...] = ("no-link-rule", "label-review")
# The closed list (010 FR-212, Q12): more tracked lines than this in one run fails qualification.
TRACKED_LIMIT = 2
# V3: what the live path is expected to do with a burst line.
EXPECTED_OPENERS: tuple[str, ...] = ("rule", "model", "none")
BURST_MIN_MEMBERS = 2
BURST_MAX_MEMBERS = 5

KIND_ATTENTION = "attention"
KIND_BURST = "burst"
KIND_MODERATION = "moderation"
_KINDS: tuple[str, ...] = (KIND_ATTENTION, KIND_BURST, KIND_MODERATION)
_LABEL_KEYS: dict[str, tuple[str, ...]] = {
    KIND_ATTENTION: ("text", "needs_response"),
    KIND_BURST: ("burst", "needs_response", "expected_opener"),
    KIND_MODERATION: ("text", "category", "needs_moderation"),
}
# Keys an attention line (one message or a burst) may carry and a moderation line may not.
_ATTENTION_ONLY_KEYS: tuple[str, ...] = ("label_class", "intent", "peer")
# V3: keys the burst set carries and no other set may.
_BURST_ONLY_KEYS: tuple[str, ...] = ("burst", "expected_opener")

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"
QUALIFIED = "QUALIFIED"
NOT_QUALIFIED = "NOT QUALIFIED"
INCOMPLETE = "INCOMPLETE"
CANDIDATE = "CANDIDATE"
# C5.
_EXIT_CODES: dict[str, int] = {QUALIFIED: 0, NOT_QUALIFIED: 1, INCOMPLETE: 2, CANDIDATE: 3}

# A8 (010's Q10, D-TG-179): a p95 single call at or under this lands a queue of about 8 within the
# settle.
LATENCY_P95_LIMIT_MS = 10_000


class FixtureError(Exception):
    """A fixture line the qualification refuses. Its message names the set and the line, never
    the text."""


def load_fixture_lines(path: Path, kind: str) -> list[tuple[int, dict[str, Any]]]:
    """Every non-blank line of `path` as `(#N, fixture)`, numbered from 1 exactly as the smokes
    number them. An attention or burst fixture always comes back with its `label_class`, `clear`
    when the line carries none. Raises `FixtureError` on a line that is not JSON, lacks a label
    key, carries a key its set may not, or carries a value outside the closed vocabularies."""
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
        _check_keys(fixture, kind, where)
        loaded.append((line, fixture))
    return loaded


def _check_keys(fixture: dict[str, Any], kind: str, where: str) -> None:
    """§3's V1-V4 and version 1's keys. No message names a refused value: a value is the
    fixture's, and only the key and the line are safe to print."""
    if kind == KIND_BURST:
        if "text" in fixture:
            raise FixtureError(f"{where}: a burst line carries burst, not text")
    else:
        for name in _BURST_ONLY_KEYS:
            if name in fixture:
                raise FixtureError(f"{where}: {name} is for the burst set only")
    missing = [name for name in _LABEL_KEYS[kind] if name not in fixture]
    if missing:
        raise FixtureError(f"{where}: missing {', '.join(missing)}")

    if kind == KIND_MODERATION:
        for name in _ATTENTION_ONLY_KEYS:
            if name in fixture:
                raise FixtureError(f"{where}: {name} is for attention sets only")
    else:
        label_class = fixture.setdefault("label_class", "clear")
        if label_class not in LABEL_CLASSES:
            raise FixtureError(f"{where}: label_class must be one of {', '.join(LABEL_CLASSES)}")
        if "intent" in fixture:
            intent = fixture["intent"]
            if not isinstance(intent, str) or intent not in INTENTS:
                raise FixtureError(f"{where}: intent must be one of {', '.join(INTENTS)}")
            # V1: the domain's single derivation, never restated here.
            if needs_response_for(intent) != fixture["needs_response"]:
                raise FixtureError(f"{where}: intent {intent} disagrees with needs_response")
        if "peer" in fixture and fixture["peer"] is not True:
            raise FixtureError(f"{where}: peer may only be true")
        if kind == KIND_BURST:
            members = fixture["burst"]
            if not (
                isinstance(members, list)
                and BURST_MIN_MEMBERS <= len(members) <= BURST_MAX_MEMBERS
                and all(isinstance(member, str) for member in members)
            ):
                raise FixtureError(
                    f"{where}: burst must be a list of {BURST_MIN_MEMBERS} to "
                    f"{BURST_MAX_MEMBERS} texts"
                )
            if fixture["expected_opener"] not in EXPECTED_OPENERS:
                raise FixtureError(
                    f"{where}: expected_opener must be one of {', '.join(EXPECTED_OPENERS)}"
                )

    if "tracked" in fixture and fixture["tracked"] not in TRACKED_DISPOSITIONS:
        raise FixtureError(f"{where}: tracked must be one of {', '.join(TRACKED_DISPOSITIONS)}")


# --- the sets and their results ----------------------------------------------------------------


@dataclass(frozen=True)
class SetSpec:
    """One benchmark set a suite reads (contract §2). `path` is `None` when the set is not read,
    and its gates are then `NOT RUN`: because it is missing, or because it is `withheld` — the
    held-out and fresh sets are never read in candidate mode (W-2, N5)."""

    name: str
    role: str
    kind: str
    path: Path | None = None
    withheld: bool = False

    @property
    def missing_reason(self) -> str:
        return "withheld in candidate mode" if self.withheld else "missing"


def set_at(directory: Path, name: str, role: str, kind: str, *, withheld: bool = False) -> SetSpec:
    """The set `name` in `directory`, without a path when it is not there or is withheld."""
    if withheld:
        return SetSpec(name=name, role=role, kind=kind, withheld=True)
    path = directory / name
    return SetSpec(name=name, role=role, kind=kind, path=path if path.is_file() else None)


@dataclass(frozen=True)
class SetResult:
    """One set's judged rows, once per run, every model call's latency across all runs, and the
    fixtures' annotations by line number. It holds no text."""

    spec: SetSpec
    runs: tuple[tuple[Any, ...], ...] = ()
    latencies_ms: tuple[int, ...] = ()
    label_classes: Mapping[int, str] = field(default_factory=dict)
    tracked: Mapping[int, str] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return bool(self.runs)

    @property
    def first(self) -> tuple[Any, ...]:
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
    """A tracked boundary case on the first run, and whether the model got it right."""

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
    fixtures besides what its rows already carry."""
    label_classes = {line: f["label_class"] for line, f in fixtures if "label_class" in f}
    tracked = {line: f["tracked"] for line, f in fixtures if "tracked" in f}
    return label_classes, tracked


def tracked_lines(result: SetResult, *, passed: Callable[[Any], bool]) -> tuple[TrackedLine, ...]:
    """The first run's tracked lines, each judged by the suite's own `passed`."""
    return tuple(
        TrackedLine(result.spec.name, row.line, result.tracked[row.line], passed(row))
        for row in result.first
        if row.line in result.tracked
    )


def compare_runs(
    runs: Sequence[Sequence[Any]], *, signature: Callable[[Any], Hashable]
) -> tuple[int, ...]:
    """S5: the lines on which any later run's `signature` differs from the first's. Each suite
    names what a line's result is; a line that failed in one run and not another differs."""
    if len(runs) < 2:
        return ()
    first = {row.line: signature(row) for row in runs[0]}
    return tuple(
        sorted(
            {
                row.line
                for later in runs[1:]
                for row in later
                if first.get(row.line) != signature(row)
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


# --- gate statuses and the verdict (§5) ---------------------------------------------------------


def gate_status(failed: bool, sets: Sequence[SetResult]) -> str:
    """`FAIL` on the evidence that ran, whatever else is missing; then `NOT RUN` when a set the
    gate needs was not read; else `PASS`."""
    if failed:
        return FAIL
    if not sets or not all(result.ran for result in sets):
        return NOT_RUN
    return PASS


def repeat_gate(
    gate: str, results: Sequence[SetResult], *, repeat: int, signature: Callable[[Any], Hashable]
) -> GateLine:
    """A7 / Q8: 0 differing lines over every set that ran; `NOT RUN` below `--repeat 2`."""
    name = "repeat: 0 differing lines"
    if repeat < 2:
        return GateLine(gate, name, NOT_RUN, f"--repeat {repeat}: needs 2")
    ran = [result for result in results if result.ran]
    differing = [
        (result.spec.name, line)
        for result in ran
        for line in compare_runs(result.runs, signature=signature)
    ]
    return GateLine(gate, name, gate_status(bool(differing), ran), format_refs(differing))


def errors_gate(gate: str, results: Sequence[SetResult]) -> GateLine:
    """A9 / Q11: any error line in any run of any set fails (S4)."""
    ran = [result for result in results if result.ran]
    names = [result.spec.name for result in ran]
    errors = sorted(
        {
            (result.spec.name, row.line)
            for result in ran
            for run in result.runs
            for row in run
            if row.error is not None
        },
        key=lambda ref: (names.index(ref[0]), ref[1]),
    )
    return GateLine(gate, "errors = 0", FAIL if errors else PASS, format_refs(errors))


def verdict(gates: Sequence[GateLine], *, candidate: bool = False) -> str:
    """C6: a candidate wording is always `CANDIDATE`, every gate still computed. Otherwise any
    `FAIL` is `NOT QUALIFIED`; then any `NOT RUN` is `INCOMPLETE`; else `QUALIFIED`."""
    if candidate:
        return CANDIDATE
    statuses = {gate.status for gate in gates}
    if FAIL in statuses:
        return NOT_QUALIFIED
    if NOT_RUN in statuses:
        return INCOMPLETE
    return QUALIFIED


def exit_code_for(result: str) -> int:
    """C5: 0 qualified, 1 not qualified, 2 incomplete, 3 candidate."""
    return _EXIT_CODES[result]


# --- loading and judging ------------------------------------------------------------------------

# A suite's per-fixture judgement: `(row, every model call's latency in milliseconds)`. A row
# carries `line` and `error` (`None` unless the call failed).
Judge = Callable[[SetSpec, int, dict[str, Any]], Awaitable[tuple[Any, tuple[int, ...]]]]
# A suite's per-line detail for run 1, or `None` for a line it does not print.
Detail = Callable[[SetSpec, Any, tuple[int, ...]], str | None]


def load_sets(specs: Sequence[SetSpec]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """Every read set's validated lines, by set name — all of them before any model call, so a
    bad line stops the run before it starts."""
    return {
        spec.name: load_fixture_lines(spec.path, spec.kind)
        for spec in specs
        if spec.path is not None
    }


def report_error(line: int, error: str) -> None:
    # The error's class name only: a gateway error's message can carry the model's raw output (C3).
    print(f"  ERROR #{line}: {error}", file=sys.stderr)


async def judge_sets(
    specs: Sequence[SetSpec],
    loaded: Mapping[str, Sequence[tuple[int, dict[str, Any]]]],
    *,
    repeat: int,
    judge: Judge,
    detail: Detail,
) -> list[SetResult]:
    """Judges every read set `repeat` times, all sets once per run (S5), through the suite's
    per-fixture `judge`. Prints the suite's per-line `detail` for the first run only, and every
    error by its class name; a set not read comes back with no run."""
    runs: dict[str, list[tuple[Any, ...]]] = {name: [] for name in loaded}
    latencies: dict[str, list[int]] = {name: [] for name in loaded}

    for run in range(1, repeat + 1):
        for spec in specs:
            if spec.name not in loaded:
                continue
            if run == 1:
                print(f"== {spec.name} ({spec.role}) run 1 of {repeat} ==")
            else:
                print(f"-- {spec.name} ({spec.role}) run {run} of {repeat}")
            rows: list[Any] = []
            for line, fixture in loaded[spec.name]:
                row, calls_ms = await judge(spec, line, fixture)
                rows.append(row)
                latencies[spec.name].extend(calls_ms)
                if row.error is not None:
                    report_error(line, row.error)
                elif run == 1:
                    printed = detail(spec, row, calls_ms)
                    if printed is not None:
                        print(printed)
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


# --- the printed report (§7): counts, set names and line numbers — never text ------------------


def numbered(lines: Sequence[int]) -> str:
    """`N` or `N (#a, #b)`."""
    return f"{len(lines)}" + (f" ({', '.join(f'#{n}' for n in lines)})" if lines else "")


def format_refs(refs: Sequence[tuple[str, int]]) -> str:
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


def calls_of(results: Sequence[SetResult]) -> list[int]:
    """Every model call's latency across every set that ran (S6)."""
    return [ms for result in results if result.ran for ms in result.latencies_ms]


def latency_line(results: Sequence[SetResult]) -> str:
    calls = calls_of(results)
    latency = latency_percentiles(calls)
    if latency is None:
        return "latency: no model call"
    return f"latency: median={latency[0]} ms p95={latency[1]} ms over {len(calls)} calls"


def repeat_line(
    results: Sequence[SetResult], *, repeat: int, signature: Callable[[Any], Hashable]
) -> str:
    if repeat < 2:
        return f"repeat: {repeat} run, not compared"
    differing = [
        (result.spec.name, line)
        for result in results
        if result.ran
        for line in compare_runs(result.runs, signature=signature)
    ]
    count, _, named = format_refs(differing).partition(" ")
    return f"repeat: {repeat} runs, {count} differing lines" + (f" {named}" if named else "")


def format_report(
    results: Sequence[SetResult],
    gates: Sequence[GateLine],
    *,
    header: str,
    set_block: Callable[[SetResult], list[str]],
    signature: Callable[[Any], Hashable],
    repeat: int,
    after_latency: Sequence[str] = (),
    candidate: bool = False,
) -> list[str]:
    """§7: the header, each set's block (or its `NOT RUN` line), the latency line and anything the
    suite adds after it, the repeat line, the gate table and the verdict."""
    lines = [header]
    for result in results:
        lines.append("")
        if not result.ran:
            lines.append(
                f"== {result.spec.name} ({result.spec.role}) — NOT RUN: "
                f"{result.spec.missing_reason} =="
            )
            continue
        lines.append(f"== {result.spec.name} ({result.spec.role}) ==")
        lines += set_block(result)

    lines.append("")
    lines.append(latency_line(results))
    lines += after_latency
    lines.append(repeat_line(results, repeat=repeat, signature=signature))

    lines.append("")
    lines += [f"{gate.gate} {gate.status} — {gate.name}: {gate.detail}" for gate in gates]
    lines.append("")
    lines.append(f"result: {verdict(gates, candidate=candidate)}")
    return lines
