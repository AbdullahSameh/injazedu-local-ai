"""The attention suite (`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` version 2
§2-§7; D-TG-194, D-TG-195): the attention sets, the live path for one line (S1), one burst (S1b)
and one violation line (S2), the gates A1-A9, and the reported lines.

Every step is the live path's own function, never re-derived here (N2): `normalize`, rule set v1's
`evaluate`, the judgement's `attention_exclusion` (AE1-AE2) — or the classification's
`eligibility` alone for an A6 line, which has no rule step — the judge's `build_attention_input`
(redaction included) and `AttentionJudgementResult` on `role="attention"`, then
`needs_response_for` and `judgement_proposes`. `smoke_attention.py` calls the same
`judge_attention_line`, so there is one benchmark path (D-TG-195). Nothing here writes, and nothing
prints a fixture's text: rows carry line numbers, labels and intents only.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.application.gateway import Gateway, GatewayError, StructuredRequest
from app.application.moderation.attention_judgement import (
    AttentionJudgementResult,
    build_attention_input,
)
from app.application.moderation.text import normalize
from app.domain.moderation.attention import evaluate
from app.domain.moderation.attention_judgement import (
    INTENTS,
    attention_exclusion,
    judgement_proposes,
    needs_response_for,
)
from app.domain.moderation.classification import MessageFacts, eligibility
from app.scripts.qualification.core import (
    FAIL,
    KIND_ATTENTION,
    KIND_BURST,
    KIND_MODERATION,
    LATENCY_P95_LIMIT_MS,
    NOT_RUN,
    PASS,
    SHIPPED_DIR,
    ClassSplit,
    GateLine,
    Judge,
    SetResult,
    SetSpec,
    TrackedLine,
    calls_of,
    errors_gate,
    format_refs,
    format_report,
    gate_status,
    latency_percentiles,
    numbered,
    repeat_gate,
    set_at,
    tracked_lines,
)

ROLE_TUNING = "tuning"
ROLE_VALIDATION = "validation"
ROLE_HELDOUT = "heldout"
ROLE_FRESH = "fresh"
ROLE_BURST = "burst"
ROLE_A6 = "a6-source"

# A4's "of at least 10": a thinner held-out set cannot show a miss rate.
HELDOUT_MIN_RULE_DECLINED = 10
# A3-A6: at most one line each.
OUT_OF_SAMPLE_LIMIT = 1
A6_LIMIT = 1
# S6: the per-message estimate's serving modes.
SERVING_MODES: tuple[str, ...] = ("single", "concurrent")

OPENERS: tuple[str, ...] = ("rule", "model", "none", "excluded", "error")
# S1: a clear positive nobody opens.
_MISSED_OPENERS: tuple[str, ...] = ("none", "excluded")
_OPENED: tuple[str, ...] = ("rule", "model")
_REAL_ATTENTION_GLOB = "real-attention*.jsonl"
# The validation sets, in reading order (§2, 2026-10-09; D-TG-200): the first cycle's own; the
# second cycle's outside-institution lines (T087); and the first cycle's held-out set, which
# `attention_v1`'s one run has seen, kept byte-identical. A3 judges each on its own.
VALIDATION_SETS: tuple[str, ...] = (
    "attention_validation_fixtures.jsonl",
    "attention_validation_scope_fixtures.jsonl",
    "attention_heldout_v1_fixtures.jsonl",
)


def discover_attention_sets(
    fixtures_dir: Path, *, shipped_dir: Path = SHIPPED_DIR, candidate: bool = False
) -> list[SetSpec]:
    """Every set the suite reads, in contract §2's order: the operator's real attention sets
    (sorted) and the shipped one as tuning; the validation sets; held-out; the fresh sample; the
    burst set; then the real, shipped and policy moderation sets as the A6 source. A set that is
    not there comes back without a path; with no real attention set at all, one placeholder stands
    for them. In candidate mode the held-out and fresh sets are withheld, never read (W-2, N5);
    every validation set is read, the first cycle's held-out set included (W-2′)."""
    real_attention = [
        SetSpec(name=path.name, role=ROLE_TUNING, kind=KIND_ATTENTION, path=path)
        for path in sorted(fixtures_dir.glob(_REAL_ATTENTION_GLOB))
        if path.is_file()
    ] or [SetSpec(name=_REAL_ATTENTION_GLOB, role=ROLE_TUNING, kind=KIND_ATTENTION)]
    return [
        *real_attention,
        set_at(shipped_dir, "attention_smoke_fixtures.jsonl", ROLE_TUNING, KIND_ATTENTION),
        *(set_at(shipped_dir, name, ROLE_VALIDATION, KIND_ATTENTION) for name in VALIDATION_SETS),
        set_at(
            shipped_dir,
            "attention_heldout_fixtures.jsonl",
            ROLE_HELDOUT,
            KIND_ATTENTION,
            withheld=candidate,
        ),
        set_at(
            fixtures_dir, "fresh-attention.jsonl", ROLE_FRESH, KIND_ATTENTION, withheld=candidate
        ),
        set_at(shipped_dir, "attention_burst_fixtures.jsonl", ROLE_BURST, KIND_BURST),
        set_at(fixtures_dir, "real-moderation.jsonl", ROLE_A6, KIND_MODERATION),
        set_at(shipped_dir, "moderation_smoke_fixtures.jsonl", ROLE_A6, KIND_MODERATION),
        set_at(shipped_dir, "moderation_smoke_policy_fixtures.jsonl", ROLE_A6, KIND_MODERATION),
    ]


# --- the rows ------------------------------------------------------------------------------------


def _proposes(intent: str | None) -> bool:
    """A1-A2 on a live answer: the derivation, then the opener's own gate."""
    return intent is not None and judgement_proposes(
        path="live", needs_response=needs_response_for(intent)
    )


@dataclass(frozen=True)
class AttentionRow:
    """One attention line's outcome (S1). `rule_opens` means the rule set opened it and no call
    was made (AE2); `excluded` names the eligibility reason when the message would never reach
    the model; `error` names the gateway error when the call failed. Only `intent` is the model's
    answer; the rest are the fixture's labels."""

    line: int
    expected_needs_response: bool
    rule_opens: bool
    expected_intent: str | None = None
    peer: bool = False
    excluded: str | None = None
    intent: str | None = None
    error: str | None = None

    @property
    def judged(self) -> bool:
        return self.intent is not None

    @property
    def predicted_needs_response(self) -> bool | None:
        return None if self.intent is None else needs_response_for(self.intent)

    @property
    def opener(self) -> str:
        """Who would open an item for this one-message burst: the rule set has the first word
        (no call); an excluded message never reaches the model; then the judgement's proposal."""
        if self.rule_opens:
            return "rule"
        if self.excluded is not None:
            return "excluded"
        if self.error is not None:
            return "error"
        return "model" if _proposes(self.intent) else "none"

    @property
    def matched(self) -> bool:
        """Opened (by either opener) exactly when the label says the team is needed."""
        return self.error is None and (self.opener in _OPENED) == self.expected_needs_response

    @property
    def signature(self) -> Hashable:
        """S5: the opener and the intent."""
        return (self.opener, self.intent)


@dataclass(frozen=True)
class MemberResult:
    """One burst member: excluded before the model, answered, or failed."""

    excluded: str | None = None
    intent: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BurstRow:
    """One burst line's outcome (S1b). Reported, never gated — but its calls count towards A7, A8
    and A9."""

    line: int
    expected_needs_response: bool
    expected_opener: str
    rule_opens: bool
    members: tuple[MemberResult, ...] = ()

    @property
    def opening_member(self) -> int | None:
        """The 1-based index of the first member whose judgement proposes, or `None`."""
        if self.rule_opens:
            return None
        for index, member in enumerate(self.members, start=1):
            if _proposes(member.intent):
                return index
        return None

    @property
    def error(self) -> str | None:
        return next((m.error for m in self.members if m.error is not None), None)

    @property
    def opener(self) -> str:
        """`rule`; else `model` from the first proposing member — as the live opener, which reads
        whichever members were judged; else `error` when a member failed; else `none`."""
        if self.rule_opens:
            return "rule"
        if self.opening_member is not None:
            return "model"
        if self.error is not None:
            return "error"
        return "none"

    @property
    def matched(self) -> bool:
        return self.opener == self.expected_opener

    @property
    def l_b1(self) -> bool:
        """L-B1: the burst needs the team, and no single member asks on its own."""
        return self.expected_needs_response and self.expected_opener == "none"

    @property
    def signature(self) -> Hashable:
        """S5: the opener and every member's intent."""
        return (self.opener, tuple(member.intent for member in self.members))


@dataclass(frozen=True)
class ViolationRow:
    """One A6-source line (S2). Only a line labelled needs-moderation is judged."""

    line: int
    violation: bool
    excluded: str | None = None
    intent: str | None = None
    error: str | None = None

    @property
    def answered_asking(self) -> bool:
        return self.violation and self.intent is not None and needs_response_for(self.intent)

    @property
    def signature(self) -> Hashable:
        return (self.excluded, self.intent)


def attention_signature(row: Any) -> Hashable:
    """S5 for every attention-suite row."""
    signature: Hashable = row.signature
    return signature


# --- the per-fixture judgements: the live path (S1, S1b, S2) -------------------------------------


def _facts(text: str) -> MessageFacts:
    """The facts a one-message fixture has: a person's text-only message in a group — so only
    E4 (no text) and E8 (acknowledgement) can ever exclude it."""
    return MessageFacts(
        is_service=False,
        media_kind=None,
        text=text,
        text_removed=False,
        is_from_moderator=False,
        sender_chat_id=None,
        group_chat_id=0,
        is_automatic_forward=False,
    )


async def _ask(
    gateway: Gateway,
    text: str,
    *,
    line: int,
    instruction: str,
    report_error: Callable[[int, str], None] | None,
) -> tuple[str | None, str | None, int | None]:
    """One call on the live request: `(intent, error, latency_ms)`. A failure is an error, never
    an answer; its detail goes only to `report_error`, and only when one is given."""
    started = time.monotonic()
    try:
        response = await gateway.generate_structured(
            StructuredRequest(
                messages=build_attention_input(text, instruction=instruction),
                schema_model=AttentionJudgementResult,
            ),
            role="attention",
        )
    except GatewayError as exc:
        if report_error is not None:
            report_error(line, f"{type(exc).__name__}: {exc}")
        return None, type(exc).__name__, None
    latency_ms = int((time.monotonic() - started) * 1000)
    intent: str = response.value.intent
    return intent, None, latency_ms


async def judge_attention_line(
    gateway: Gateway,
    fixture: Mapping[str, Any],
    *,
    line: int,
    instruction: str,
    report_error: Callable[[int, str], None] | None = None,
) -> tuple[AttentionRow, int | None]:
    """S1, one line as a one-message burst: normalise; the rule set (`evaluate`) — the opener is
    `rule` and no call is made (AE2); eligibility (`attention_exclusion`) — `excluded`; the model
    on `role="attention"`; then `needs_response_for` and `judgement_proposes` — `model` or `none`.
    Returns the row and the call's latency in milliseconds, `None` when no answer came back."""
    text = normalize(fixture["text"])
    base = AttentionRow(
        line=line,
        expected_needs_response=fixture["needs_response"],
        expected_intent=fixture.get("intent"),
        peer=fixture.get("peer") is True,
        rule_opens=evaluate([text]),
    )
    if base.rule_opens:
        return base, None
    reason = attention_exclusion(_facts(text))
    if reason is not None:
        return replace(base, excluded=reason), None
    intent, error, latency_ms = await _ask(
        gateway, text, line=line, instruction=instruction, report_error=report_error
    )
    return replace(base, intent=intent, error=error), latency_ms


async def judge_attention_burst(
    gateway: Gateway,
    fixture: Mapping[str, Any],
    *,
    line: int,
    instruction: str,
    report_error: Callable[[int, str], None] | None = None,
) -> tuple[BurstRow, tuple[int, ...]]:
    """S1b: `evaluate` over every member gives `rule`, with no call. Otherwise each member goes
    through S1's eligibility and the model, in posting order — the model sees one member at a
    time, never the burst (FR-339). Returns the row and every call's latency."""
    texts = [normalize(member) for member in fixture["burst"]]
    base = BurstRow(
        line=line,
        expected_needs_response=fixture["needs_response"],
        expected_opener=fixture["expected_opener"],
        rule_opens=evaluate(texts),
    )
    if base.rule_opens:
        return base, ()
    members: list[MemberResult] = []
    latencies: list[int] = []
    for text in texts:
        reason = attention_exclusion(_facts(text))
        if reason is not None:
            members.append(MemberResult(excluded=reason))
            continue
        intent, error, latency_ms = await _ask(
            gateway, text, line=line, instruction=instruction, report_error=report_error
        )
        members.append(MemberResult(intent=intent, error=error))
        if latency_ms is not None:
            latencies.append(latency_ms)
    return replace(base, members=tuple(members)), tuple(latencies)


async def judge_violation_line(
    gateway: Gateway,
    fixture: Mapping[str, Any],
    *,
    line: int,
    instruction: str,
    report_error: Callable[[int, str], None] | None = None,
) -> tuple[ViolationRow, int | None]:
    """S2: a moderation line labelled needs-moderation, judged by S1's steps 2-4 — eligibility
    (E1-E8 only: there is no rule step, so no AE2), the model, the derivation — and no veto: the
    classification is not consulted. A line labelled needs-moderation false is not judged."""
    if not fixture["needs_moderation"]:
        return ViolationRow(line=line, violation=False), None
    text = normalize(fixture["text"])
    reason = eligibility(_facts(text))
    if reason is not None:
        return ViolationRow(line=line, violation=True, excluded=reason), None
    intent, error, latency_ms = await _ask(
        gateway, text, line=line, instruction=instruction, report_error=report_error
    )
    return ViolationRow(line=line, violation=True, intent=intent, error=error), latency_ms


def attention_judge(gateway: Gateway, *, instruction: str) -> Judge:
    """The suite's per-fixture judgement, by set: S1b on the burst set, S2 on the A6 source, S1
    on every other set."""

    async def judge(
        spec: SetSpec, line: int, fixture: dict[str, Any]
    ) -> tuple[Any, tuple[int, ...]]:
        if spec.kind == KIND_BURST:
            return await judge_attention_burst(gateway, fixture, line=line, instruction=instruction)
        row: Any
        if spec.role == ROLE_A6:
            row, latency_ms = await judge_violation_line(
                gateway, fixture, line=line, instruction=instruction
            )
        else:
            row, latency_ms = await judge_attention_line(
                gateway, fixture, line=line, instruction=instruction
            )
        return row, (latency_ms,) if latency_ms is not None else ()

    return judge


# --- the per-line detail (§7, run 1 only) --------------------------------------------------------


def format_row(row: AttentionRow, latency_ms: int | None) -> str:
    """One attention line — line number, labels, the answer and the opener; never text. An error
    row has no line of its own: its error is reported as it happens."""
    if row.matched:
        status = "OK"
    else:
        status = "FN" if row.expected_needs_response else "FP"
    label = f" label={row.expected_intent}" if row.expected_intent is not None else ""
    peer = " peer" if row.peer else ""
    head = f"[{status}] #{row.line} expected={row.expected_needs_response}{label}{peer}"
    if row.rule_opens:
        return f"{head} rule=opens opener=rule"
    if row.excluded is not None:
        return f"{head} excluded={row.excluded} rule=declines opener=excluded"
    return f"{head} intent={row.intent} rule=declines opener={row.opener} latency_ms={latency_ms}"


def _member(member: MemberResult) -> str:
    if member.excluded is not None:
        return f"excluded:{member.excluded}"
    if member.error is not None:
        return "error"
    return f"{member.intent}"


def format_burst_row(row: BurstRow, calls_ms: tuple[int, ...]) -> str:
    status = "OK" if row.matched else "MISMATCH"
    member = row.opening_member if row.opening_member is not None else "-"
    members = ",".join(_member(m) for m in row.members) if row.members else "-"
    latency = ",".join(str(ms) for ms in calls_ms) if calls_ms else "-"
    return (
        f"[{status}] #{row.line} expected={row.expected_opener} opener={row.opener} "
        f"member={member} intents={members} latency_ms={latency}"
    )


def format_violation_row(row: ViolationRow, latency_ms: int | None) -> str | None:
    if not row.violation:
        return None
    status = "FP" if row.answered_asking else "OK"
    if row.excluded is not None:
        return f"[{status}] #{row.line} violation excluded={row.excluded}"
    return f"[{status}] #{row.line} violation intent={row.intent} latency_ms={latency_ms}"


def attention_detail(spec: SetSpec, row: Any, calls_ms: tuple[int, ...]) -> str | None:
    latency_ms = calls_ms[0] if calls_ms else None
    if isinstance(row, BurstRow):
        return format_burst_row(row, calls_ms)
    if isinstance(row, ViolationRow):
        return format_violation_row(row, latency_ms)
    return format_row(row, latency_ms)


# --- the smoke's summary, shared with each set's block ------------------------------------------


@dataclass(frozen=True)
class AttentionSummary:
    total: int
    matched: int
    judged: int
    needs_response_agreed: int
    false_negatives: tuple[int, ...]
    false_positives: tuple[int, ...]
    intent_exact: tuple[int, int]
    intents: dict[str, int]
    errors: tuple[int, ...]
    excluded: tuple[int, ...]
    openers_expected_true: dict[str, int]
    openers_expected_false: dict[str, int]
    model_opened_on_expected_false: tuple[int, ...]


def summarise(rows: Sequence[AttentionRow]) -> AttentionSummary:
    """Pure scoring over one-message outcomes. The judgement's own agreement — over the lines the
    model answered — is kept apart from who would open an item, split by label. A false negative
    is a line labelled as needing the team that the model answered with another intent; a false
    positive is the reverse. `intent_exact` is `(exact, out of)` over answered lines carrying an
    `intent`."""
    judged = [row for row in rows if row.judged]
    with_intent = [row for row in judged if row.expected_intent is not None]
    openers_true: Counter[str] = Counter(row.opener for row in rows if row.expected_needs_response)
    openers_false: Counter[str] = Counter(
        row.opener for row in rows if not row.expected_needs_response
    )
    intents: Counter[str] = Counter(row.intent for row in judged if row.intent is not None)
    return AttentionSummary(
        total=len(rows),
        matched=sum(1 for row in rows if row.matched),
        judged=len(judged),
        needs_response_agreed=sum(
            1 for row in judged if row.predicted_needs_response == row.expected_needs_response
        ),
        false_negatives=tuple(
            row.line
            for row in judged
            if row.expected_needs_response and not row.predicted_needs_response
        ),
        false_positives=tuple(
            row.line
            for row in judged
            if not row.expected_needs_response and row.predicted_needs_response
        ),
        intent_exact=(
            sum(1 for row in with_intent if row.intent == row.expected_intent),
            len(with_intent),
        ),
        intents={intent: intents[intent] for intent in INTENTS},
        errors=tuple(row.line for row in rows if row.error is not None),
        excluded=tuple(row.line for row in rows if row.excluded is not None),
        openers_expected_true={opener: openers_true[opener] for opener in OPENERS},
        openers_expected_false={opener: openers_false[opener] for opener in OPENERS},
        model_opened_on_expected_false=tuple(
            row.line for row in rows if not row.expected_needs_response and row.opener == "model"
        ),
    )


def format_summary(summary: AttentionSummary) -> list[str]:
    """The summary block — counts, intents and line numbers only, never text."""

    def tally(counts: Mapping[str, int]) -> str:
        return " ".join(f"{name}={count}" for name, count in counts.items())

    exact, out_of = summary.intent_exact
    return [
        f"{summary.matched}/{summary.total} matched",
        f"needs_response agreed: {summary.needs_response_agreed}/{summary.judged} answered",
        f"false negatives (expected true, predicted false): {numbered(summary.false_negatives)}",
        f"false positives (expected false, predicted true): {numbered(summary.false_positives)}",
        "model-opened on expected-false (new moderator work): "
        f"{numbered(summary.model_opened_on_expected_false)}",
        f"intent exact: {exact}/{out_of}",
        f"intents: {tally(summary.intents)}",
        f"excluded before the model: {numbered(summary.excluded)}",
        f"errors: {numbered(summary.errors)}",
        f"opener, expected true: {tally(summary.openers_expected_true)}",
        f"opener, expected false: {tally(summary.openers_expected_false)}",
    ]


# --- scoring S1 and the reported lines (§4, §6) --------------------------------------------------


def split_by_label_class(
    rows: Sequence[AttentionRow],
    *,
    label_classes: Mapping[int, str],
    tracked: Mapping[int, str],
) -> ClassSplit:
    """S1. A clear positive is missed when nobody opens it (`none` or `excluded`); an error is
    never scored as a miss (S4). A clear negative counts only when the model is its opener. A line
    with no `label_class` is clear; a tracked line is out of every count."""
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
            r.line for r in ambiguous if r.judged and r.predicted_needs_response
        ),
        ambiguous_agreed=sum(1 for r in ambiguous if r.matched),
    )


def _split(result: SetResult) -> ClassSplit:
    return split_by_label_class(
        list(result.first), label_classes=result.label_classes, tracked=result.tracked
    )


@dataclass(frozen=True)
class IntentAgreement:
    """R-intent over the answered lines that carry an `intent`."""

    agreed: int
    out_of: int
    disagreeing: tuple[tuple[int, str, str], ...]


def intent_agreement(rows: Sequence[AttentionRow]) -> IntentAgreement:
    carrying = [r for r in rows if r.expected_intent is not None and r.intent is not None]
    disagreeing = tuple(
        (r.line, str(r.expected_intent), str(r.intent))
        for r in carrying
        if r.intent != r.expected_intent
    )
    return IntentAgreement(
        agreed=len(carrying) - len(disagreeing), out_of=len(carrying), disagreeing=disagreeing
    )


@dataclass(frozen=True)
class DiscussionLine:
    """R-discussion (Policy D): the two confusions, and the `peer` lines."""

    asking_answered_discussion: tuple[int, ...]
    discussion_answered_asking: tuple[int, ...]
    peer_correct: tuple[int, ...]
    peer_judged: tuple[int, ...]


def discussion_line(rows: Sequence[AttentionRow]) -> DiscussionLine:
    """A label is `asking` exactly when it needs a response (V1). A `peer` line is correct when it
    is opened exactly as its label says."""
    peer_judged = tuple(r.line for r in rows if r.peer and r.judged)
    return DiscussionLine(
        asking_answered_discussion=tuple(
            r.line for r in rows if r.expected_needs_response and r.intent == "discussion"
        ),
        discussion_answered_asking=tuple(
            r.line for r in rows if r.expected_intent == "discussion" and r.intent == "asking"
        ),
        peer_correct=tuple(r.line for r in rows if r.peer and r.judged and r.matched),
        peer_judged=peer_judged,
    )


def rule_opened_negatives(
    rows: Sequence[AttentionRow], *, label_classes: Mapping[int, str], tracked: Mapping[int, str]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """R-rule: the clear negatives the rule set opens — `(not peer, peer)` — the rule baseline on
    the set."""
    negatives = [
        r
        for r in rows
        if r.line not in tracked
        and label_classes.get(r.line, "clear") == "clear"
        and not r.expected_needs_response
        and r.opener == "rule"
    ]
    return (
        tuple(r.line for r in negatives if not r.peer),
        tuple(r.line for r in negatives if r.peer),
    )


def attention_tracked_passed(row: AttentionRow) -> bool:
    """A tracked attention line passes when it is opened as its label says."""
    if row.error is not None:
        return False
    if row.expected_needs_response:
        return row.opener not in _MISSED_OPENERS
    return row.opener != "model"


def attention_tracked_lines(result: SetResult) -> tuple[TrackedLine, ...]:
    return tracked_lines(result, passed=attention_tracked_passed)


def per_message_estimate(
    attention_p95_ms: int | None, *, moderation_p95_ms: int | None, serving: str
) -> str:
    """S6, reported only: what one message costs both judgements on this host's lane — the sum of
    the two p95s on a single-occupancy lane, the larger of them on a concurrent one."""
    if attention_p95_ms is None:
        return "per-message estimate: not computed (no attention call)"
    if moderation_p95_ms is None:
        return "per-message estimate: not computed (pass --moderation-p95-ms)"
    if serving == "concurrent":
        return (
            f"per-message estimate (concurrent lane): {max(attention_p95_ms, moderation_p95_ms)} "
            f"ms, the larger of attention p95 {attention_p95_ms} ms and moderation p95 "
            f"{moderation_p95_ms} ms (reported, never gated)"
        )
    return (
        f"per-message estimate (single-occupancy lane): {attention_p95_ms + moderation_p95_ms} "
        f"ms, attention p95 {attention_p95_ms} ms + moderation p95 {moderation_p95_ms} ms "
        "(reported, never gated)"
    )


# --- the gates A1-A9 (§5) ------------------------------------------------------------------------


def _out_of_sample_gate(
    gate: str, name: str, sets: Sequence[SetResult], *, minimum: int = 0
) -> GateLine:
    """A4-A5 (and A3 until 2026-10-09, now `_per_set_gate`): clear negatives model-opened <= 1
    and rule-declined clear positives missed <= 1, over the role's sets together; A4 also needs
    `minimum` rule-declined clear positives to show a miss rate."""
    opened = [
        (r.spec.name, line)
        for r in sets
        if r.ran
        for line in _split(r).clear_negatives_model_opened
    ]
    missed = [
        (r.spec.name, line)
        for r in sets
        if r.ran
        for line in _split(r).rule_declined_positives_missed
    ]
    out_of = sum(_split(r).rule_declined_positives for r in sets if r.ran)
    thin = minimum > 0 and bool(sets) and all(r.ran for r in sets) and out_of < minimum
    failed = len(opened) > OUT_OF_SAMPLE_LIMIT or len(missed) > OUT_OF_SAMPLE_LIMIT or thin
    return GateLine(
        gate,
        name,
        gate_status(failed, sets),
        f"model-opened {format_refs(opened)}; missed {format_refs(missed)} of {out_of}",
    )


def _per_set_gate(gate: str, name: str, sets: Sequence[SetResult]) -> GateLine:
    """A3 (2026-10-09): each validation set judged on its own, <= 1 / <= 1 in every one — pooling
    them would hold the first cycle's sets to a stricter bar than the one they were written for.
    `FAIL` when any set that ran fails; else `NOT RUN` while one is missing; the detail gives
    every set's counts, in reading order. With one set, the status is `_out_of_sample_gate`'s."""
    parts: list[str] = []
    failed = False
    for result in sets:
        if not result.ran:
            parts.append(f"{result.spec.name}: {NOT_RUN} ({result.spec.missing_reason})")
            continue
        split = _split(result)
        opened = split.clear_negatives_model_opened
        missed = split.rule_declined_positives_missed
        failed = failed or len(opened) > OUT_OF_SAMPLE_LIMIT or len(missed) > OUT_OF_SAMPLE_LIMIT
        parts.append(
            f"{result.spec.name}: model-opened {numbered(opened)}; missed {numbered(missed)} of "
            f"{split.rule_declined_positives}"
        )
    return GateLine(gate, name, gate_status(failed, sets), " | ".join(parts))


def evaluate_attention_gates(results: Sequence[SetResult], *, repeat: int) -> tuple[GateLine, ...]:
    """A1-A9, every one a hard gate (§5). Ambiguous lines, intents, the peer lines, the rule
    baseline and the burst set are reported only and never reach here — except that every call
    counts towards repeat, latency and errors."""

    def of_role(role: str) -> list[SetResult]:
        return [result for result in results if result.spec.role == role]

    tuning = of_role(ROLE_TUNING)
    a1 = [
        (r.spec.name, line)
        for r in tuning
        if r.ran
        for line in _split(r).clear_negatives_model_opened
    ]
    a2 = [(r.spec.name, line) for r in tuning if r.ran for line in _split(r).clear_positives_missed]

    a6_sets = of_role(ROLE_A6)
    a6 = [
        (r.spec.name, row.line) for r in a6_sets if r.ran for row in r.first if row.answered_asking
    ]

    latency = latency_percentiles(calls_of(results))
    if latency is None:
        a8 = GateLine("A8", f"latency p95 <= {LATENCY_P95_LIMIT_MS} ms", NOT_RUN, "no call")
    else:
        median, p95 = latency
        a8 = GateLine(
            "A8",
            f"latency p95 <= {LATENCY_P95_LIMIT_MS} ms",
            FAIL if p95 > LATENCY_P95_LIMIT_MS else PASS,
            f"p95 {p95} ms, median {median} ms",
        )

    return (
        GateLine(
            "A1",
            "tuning clear negatives model-opened = 0",
            gate_status(bool(a1), tuning),
            format_refs(a1),
        ),
        GateLine(
            "A2",
            "tuning clear positives missed = 0",
            gate_status(bool(a2), tuning),
            format_refs(a2),
        ),
        _per_set_gate(
            "A3",
            "validation, each set: clear negatives model-opened <= 1, rule-declined clear "
            "positives missed <= 1",
            of_role(ROLE_VALIDATION),
        ),
        _out_of_sample_gate(
            "A4",
            "held-out: clear negatives model-opened <= 1, rule-declined clear positives missed "
            f"<= 1 of >= {HELDOUT_MIN_RULE_DECLINED}",
            of_role(ROLE_HELDOUT),
            minimum=HELDOUT_MIN_RULE_DECLINED,
        ),
        _out_of_sample_gate(
            "A5",
            "fresh sample: clear negatives model-opened <= 1, rule-declined clear positives "
            "missed <= 1",
            of_role(ROLE_FRESH),
        ),
        GateLine(
            "A6",
            f"violation lines answered asking <= {A6_LIMIT}",
            gate_status(len(a6) > A6_LIMIT, a6_sets),
            format_refs(a6),
        ),
        repeat_gate("A7", results, repeat=repeat, signature=attention_signature),
        a8,
        errors_gate("A9", results),
    )


# --- the report (§7) ----------------------------------------------------------------------------


def _one_message_block(result: SetResult) -> list[str]:
    rows: list[AttentionRow] = list(result.first)
    split = _split(result)
    agreement = intent_agreement(rows)
    discussion = discussion_line(rows)
    rule_lines, rule_peer = rule_opened_negatives(
        rows, label_classes=result.label_classes, tracked=result.tracked
    )
    disagreeing = ", ".join(
        f"#{line} {label}→{answer}" for line, label, answer in agreement.disagreeing
    )
    block = format_summary(summarise(rows))
    block += [
        f"label class: clear positives {split.clear_positives}, missed "
        f"{numbered(split.clear_positives_missed)}; rule-declined clear positives "
        f"{split.rule_declined_positives}, missed "
        f"{numbered(split.rule_declined_positives_missed)}; "
        f"clear negatives {split.clear_negatives}, model-opened "
        f"{numbered(split.clear_negatives_model_opened)}",
        f"R-ambiguous: {split.ambiguous} lines; answered true "
        f"{numbered(split.ambiguous_answered_true)}; agreed {split.ambiguous_agreed}/"
        f"{split.ambiguous} (reported, never gated)",
        f"R-intent: agreed {agreement.agreed}/{agreement.out_of} answered lines carrying an "
        f"intent; disagreeing {len(agreement.disagreeing)}"
        + (f" ({disagreeing})" if disagreeing else ""),
        f"R-discussion: label asking answered discussion "
        f"{numbered(discussion.asking_answered_discussion)}; label discussion answered asking "
        f"{numbered(discussion.discussion_answered_asking)}; peer lines correct "
        f"{numbered(discussion.peer_correct)} of judged {numbered(discussion.peer_judged)}",
        f"R-rule: clear negatives rule-opened {numbered(rule_lines)}; peer "
        f"{numbered(rule_peer)} (the rule baseline on this set)",
    ]
    block += [
        f"tracked: {t.set_name} #{t.line} {t.disposition} {PASS if t.passed else FAIL}"
        for t in attention_tracked_lines(result)
    ]
    return block


def _burst_block(result: SetResult) -> list[str]:
    rows: list[BurstRow] = list(result.first)
    block = [
        f"R-burst #{row.line}: opener={row.opener} member="
        f"{row.opening_member if row.opening_member is not None else '-'} "
        f"expected={row.expected_opener} {'match' if row.matched else 'MISMATCH'}"
        + (" L-B1" if row.l_b1 else "")
        for row in rows
    ]
    block.append(
        f"R-burst: {sum(1 for row in rows if row.matched)}/{len(rows)} match expected_opener; "
        f"L-B1 lines {numbered(tuple(row.line for row in rows if row.l_b1))} (reported, never "
        "gated)"
    )
    return block


def _violation_block(result: SetResult) -> list[str]:
    rows: list[ViolationRow] = [row for row in result.first if row.violation]
    intents: Counter[str] = Counter(row.intent for row in rows if row.intent is not None)
    return [
        f"A6 source: violation lines {len(rows)}; answered asking "
        f"{numbered(tuple(row.line for row in rows if row.answered_asking))}; excluded "
        f"{numbered(tuple(row.line for row in rows if row.excluded is not None))}; errors "
        f"{numbered(tuple(row.line for row in rows if row.error is not None))}",
        "intents: " + " ".join(f"{intent}={intents[intent]}" for intent in INTENTS),
    ]


def attention_set_block(result: SetResult) -> list[str]:
    if result.spec.kind == KIND_BURST:
        return _burst_block(result)
    if result.spec.role == ROLE_A6:
        return _violation_block(result)
    return _one_message_block(result)


def attention_header(*, profile: str, model: str, prompt: str, repeat: int) -> str:
    """`prompt` is the frozen version, or `CANDIDATE <sha256>` for a candidate file."""
    return f"qualify-attention: profile={profile} model={model} prompt={prompt} repeat={repeat}"


def format_attention_report(
    results: Sequence[SetResult],
    gates: Sequence[GateLine],
    *,
    profile: str,
    model: str,
    prompt: str,
    repeat: int,
    moderation_p95_ms: int | None = None,
    serving: str = "single",
    candidate: bool = False,
) -> list[str]:
    """§7: the header, each set's block, latency and the per-message estimate, repeat, the gate
    table and the verdict — `CANDIDATE` for a candidate file, every gate still computed."""
    latency = latency_percentiles(calls_of(results))
    return format_report(
        results,
        gates,
        header=attention_header(profile=profile, model=model, prompt=prompt, repeat=repeat),
        set_block=attention_set_block,
        signature=attention_signature,
        repeat=repeat,
        after_latency=[
            per_message_estimate(
                latency[1] if latency is not None else None,
                moderation_p95_ms=moderation_p95_ms,
                serving=serving,
            )
        ],
        candidate=candidate,
    )
