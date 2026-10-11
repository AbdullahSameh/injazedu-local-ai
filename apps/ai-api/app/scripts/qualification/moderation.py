"""The moderation suite (`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md`
version 2 §2, §5; D-TG-194, FR-328): 010's advert gates Q5-Q7, with repeat (Q8), errors (Q11) and
tracked lines (Q12), over the real, shipped and policy moderation sets. The 010 identifiers are
kept so the history reads straight through.

Each line is judged by `smoke_moderation.judge_moderation_fixture`, the smoke's own path:
normalise, the model, then `route_prediction` (live) at the configured thresholds (C4, N2). The
per-line detail, each set's block, the gates and the verdict are what version 1 printed for its
moderation part (SC-305). Version 1's attention gates moved to the attention suite.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.application.gateway import Gateway
from app.scripts.qualification.core import (
    FAIL,
    KIND_MODERATION,
    PASS,
    SHIPPED_DIR,
    TRACKED_DISPOSITIONS,
    TRACKED_LIMIT,
    GateLine,
    Judge,
    SetResult,
    SetSpec,
    TrackedLine,
    errors_gate,
    format_refs,
    format_report,
    gate_status,
    numbered,
    repeat_gate,
    set_at,
    tracked_lines,
)
from app.scripts.smoke_moderation import (
    SmokeRow,
    SmokeSummary,
    format_row,
    format_summary,
    judge_moderation_fixture,
    summarise,
)

ROLE_MODERATION_REAL = "moderation-real"
ROLE_MODERATION_SHIPPED = "moderation-shipped"
ROLE_MODERATION_POLICY = "moderation-policy"


def discover_moderation_sets(
    fixtures_dir: Path, *, shipped_dir: Path = SHIPPED_DIR
) -> list[SetSpec]:
    """The suite's sets, in reading order (contract §2): the operator's real moderation set, then
    the shipped and policy sets. A set that is not there comes back without a path."""
    return [
        set_at(fixtures_dir, "real-moderation.jsonl", ROLE_MODERATION_REAL, KIND_MODERATION),
        set_at(
            shipped_dir, "moderation_smoke_fixtures.jsonl", ROLE_MODERATION_SHIPPED, KIND_MODERATION
        ),
        set_at(
            shipped_dir,
            "moderation_smoke_policy_fixtures.jsonl",
            ROLE_MODERATION_POLICY,
            KIND_MODERATION,
        ),
    ]


def moderation_signature(row: SmokeRow) -> Hashable:
    """S5, version 1's: a line differs when its predicted needs-response, needs-moderation,
    category or route does. Confidence alone never makes a difference."""
    return (
        row.predicted_needs_response,
        row.predicted_needs_moderation,
        row.predicted_category,
        row.route,
    )


def moderation_gated(rows: Sequence[SmokeRow], *, tracked: Mapping[int, str]) -> SmokeSummary:
    """S3 (version 1's S2): the smoke's own scoring over the lines that are not tracked."""
    return summarise([row for row in rows if row.line not in tracked])


def moderation_tracked_passed(row: SmokeRow) -> bool:
    """A tracked moderation line passes when needs-moderation agrees with its label."""
    return row.error is None and row.predicted_needs_moderation == row.expected_needs_moderation


def moderation_tracked_lines(result: SetResult) -> tuple[TrackedLine, ...]:
    return tracked_lines(result, passed=moderation_tracked_passed)


# --- the gates (§5) -----------------------------------------------------------------------------


def _false_alarm_gate(gate: str, name: str, sets: Sequence[SetResult]) -> GateLine:
    misses: list[tuple[str, int]] = []
    alarms: list[tuple[str, int]] = []
    for result in sets:
        summary = moderation_gated(list(result.first), tracked=result.tracked)
        misses += [(result.spec.name, line) for line in summary.false_negatives]
        alarms += [(result.spec.name, line) for line in summary.false_positives]
    return GateLine(
        gate,
        name,
        gate_status(bool(misses or alarms), sets),
        f"false negatives {format_refs(misses)}; false positives {format_refs(alarms)}",
    )


def evaluate_moderation_gates(results: Sequence[SetResult], *, repeat: int) -> tuple[GateLine, ...]:
    """Q5-Q8, Q11 and Q12, every one a hard gate (§5). Category agreement is reported only."""

    def of_role(role: str) -> list[SetResult]:
        return [result for result in results if result.spec.role == role]

    policy_misses: list[tuple[str, int]] = []
    policy_alarms: list[tuple[str, int]] = []
    policy_incidents: list[tuple[str, int]] = []
    policy = of_role(ROLE_MODERATION_POLICY)
    for result in policy:
        rows = [row for row in result.first if row.line not in result.tracked]
        summary = summarise(rows)
        policy_misses += [(result.spec.name, line) for line in summary.false_negatives]
        policy_alarms += [(result.spec.name, line) for line in summary.false_positives]
        policy_incidents += [
            (result.spec.name, row.line)
            for row in rows
            if not row.expected_needs_moderation
            and row.route is not None
            and row.route.split("/", 1)[0] == "incident"
        ]

    tracked = [
        line for result in results if result.ran for line in moderation_tracked_lines(result)
    ]
    tracked_refused = [t for t in tracked if t.disposition not in TRACKED_DISPOSITIONS]

    return (
        _false_alarm_gate(
            "Q5",
            "real moderation, tracked out: false negatives = 0, false positives = 0",
            of_role(ROLE_MODERATION_REAL),
        ),
        _false_alarm_gate(
            "Q6",
            "shipped moderation, tracked out: false negatives = 0, false positives = 0",
            of_role(ROLE_MODERATION_SHIPPED),
        ),
        GateLine(
            "Q7",
            "policy moderation: false negatives <= 1, false positives = 0, "
            "legitimate -> incident = 0",
            gate_status(len(policy_misses) > 1 or bool(policy_alarms or policy_incidents), policy),
            f"false negatives {format_refs(policy_misses)}; false positives "
            f"{format_refs(policy_alarms)}; legitimate -> incident {format_refs(policy_incidents)}",
        ),
        repeat_gate("Q8", results, repeat=repeat, signature=moderation_signature),
        errors_gate("Q11", results),
        GateLine(
            "Q12",
            f"tracked lines <= {TRACKED_LIMIT}, each {' or '.join(TRACKED_DISPOSITIONS)}",
            FAIL if len(tracked) > TRACKED_LIMIT or tracked_refused else PASS,
            format_refs([(t.set_name, t.line) for t in tracked]),
        ),
    )


# --- judging and the report (§7) ----------------------------------------------------------------


def moderation_judge(
    gateway: Gateway, *, prompt_version: str, floor: Decimal, threshold: Decimal
) -> Judge:
    """Every moderation line through the smoke's own judgement (C4)."""

    async def judge(
        spec: SetSpec, line: int, fixture: dict[str, Any]
    ) -> tuple[SmokeRow, tuple[int, ...]]:
        row, latency_ms = await judge_moderation_fixture(
            gateway,
            fixture,
            line=line,
            prompt_version=prompt_version,
            floor=floor,
            threshold=threshold,
        )
        return row, (latency_ms,) if latency_ms is not None else ()

    return judge


def moderation_detail(spec: SetSpec, row: SmokeRow, calls_ms: tuple[int, ...]) -> str:
    """The smoke's own per-line format."""
    return format_row(row, calls_ms[0] if calls_ms else None)


def moderation_set_block(result: SetResult) -> list[str]:
    """The smoke's summary lines, the gated counts with tracked lines out, then the tracked
    lines — version 1's block, byte for byte."""
    rows: list[SmokeRow] = list(result.first)
    gated = moderation_gated(rows, tracked=result.tracked)
    block = format_summary(summarise(rows))
    block.append(
        f"gated, tracked out: false negatives {numbered(gated.false_negatives)}; "
        f"false positives {numbered(gated.false_positives)}; legitimate -> incident "
        f"{gated.legitimate_routes['incident']}"
    )
    block += [
        f"tracked: {t.set_name} #{t.line} {t.disposition} {PASS if t.passed else FAIL}"
        for t in moderation_tracked_lines(result)
    ]
    return block


def format_moderation_report(
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
    """The header, each set's block, latency, repeat, the gate table and the verdict — the
    per-line detail is printed while the first run is judged."""
    return format_report(
        results,
        gates,
        header=moderation_header(
            profile=profile,
            model=model,
            prompt=prompt,
            floor=floor,
            threshold=threshold,
            repeat=repeat,
        ),
        set_block=moderation_set_block,
        signature=moderation_signature,
        repeat=repeat,
    )


def moderation_header(
    *, profile: str, model: str, prompt: str, floor: object, threshold: object, repeat: int
) -> str:
    return (
        f"qualify-moderation: profile={profile} model={model} prompt={prompt} floor={floor} "
        f"threshold={threshold} repeat={repeat}"
    )
