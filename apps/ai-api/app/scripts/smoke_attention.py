"""`python -m app.scripts.smoke_attention` — TG-M5.1's benchmark, run before AI-assisted Attention
Opening is switched on (`specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md` B1-B4,
`quickstart.md` §2).

Classifies each fixture through the **real** gateway and the **real** model runtime, `role=
"moderation"` — never scripted, and it writes nothing. Reads JSONL from standard input, one
`{"text", "needs_response", "category"?}` object per line; falls back to the shipped synthetic set
(`attention_smoke_fixtures.jsonl`, no real student text) when standard input is a TTY or empty.
`--profile NAME` pins a named profile, active or not; `--prompt VERSION` sends a named instruction
instead of the configured `MODERATION_PROMPT_VERSION` — both exactly as `smoke_moderation` does.

Each fixture is judged the way live traffic is, as a one-message burst: the rule set first
(`evaluate`), then eligibility (an acknowledgement is never sent to the model), then the model,
routed at the configured thresholds (`route_prediction`) and gated by `proposes_attention` — every
one the real function, never re-derived here (N7). The summary separates the model's raw judgement
(agreement, false negatives, false positives, with line numbers) from **who would open an item**
(rule / model / nobody), split by label — so a model-opened item on an expected-false fixture, the
new moderator work this milestone risks, is counted on its own. Never prints a fixture's text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.errors import GatewayError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import (
    PROMPT_VERSIONS,
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.domain.moderation.attention import evaluate
from app.domain.moderation.classification import (
    MessageFacts,
    Prediction,
    eligibility,
    proposes_attention,
    quantise,
    route_prediction,
)
from app.infrastructure.config import load_settings
from app.providers.llm.base import StructuredRequest
from app.scripts.smoke_moderation import _fail_if_unreachable, _PinnedRegistry, _report_error

_SHIPPED_FIXTURES = Path(__file__).resolve().parent / "attention_smoke_fixtures.jsonl"
_OPENERS: tuple[str, ...] = ("rule", "model", "none", "excluded", "error")


@dataclass(frozen=True)
class AttentionRow:
    """One fixture's outcome. `excluded` names the eligibility reason when the message would never
    reach the model; `error` names the gateway error when the call failed — neither is a
    prediction, and neither is scored as one."""

    line: int
    expected_needs_response: bool
    expected_category: str | None
    rule_opens: bool
    excluded: str | None = None
    predicted_needs_response: bool | None = None
    predicted_category: str | None = None
    predicted_needs_moderation: bool | None = None
    confidence: float | None = None
    route: str | None = None
    model_proposes: bool | None = None
    error: str | None = None

    @property
    def scored(self) -> bool:
        return self.error is None and self.excluded is None

    @property
    def opener(self) -> str:
        """Who would open an item for this one-message burst: the rule set has the first word
        (contract O1); an acknowledgement never reaches the model; then the model's proposal."""
        if self.rule_opens:
            return "rule"
        if self.excluded is not None:
            return "excluded"
        if self.error is not None:
            return "error"
        return "model" if self.model_proposes else "none"

    @property
    def matched(self) -> bool:
        if self.error is not None:
            return False
        if self.excluded is not None:
            return not self.expected_needs_response
        return self.predicted_needs_response == self.expected_needs_response


@dataclass(frozen=True)
class AttentionSummary:
    total: int
    matched: int
    scored: int
    needs_response_agreed: int
    false_negatives: tuple[int, ...]
    false_positives: tuple[int, ...]
    category_exact: tuple[int, int]
    errors: tuple[int, ...]
    excluded: tuple[int, ...]
    openers_expected_true: dict[str, int]
    openers_expected_false: dict[str, int]
    model_opened_on_expected_false: tuple[int, ...]


def summarise(rows: list[AttentionRow]) -> AttentionSummary:
    """Pure scoring over the fixture outcomes. A false negative is a fixture labelled as needing
    a response that the model said needs none; a false positive is the reverse. `category_exact`
    is `(exact, out of)` over scored fixtures that carry a category — secondary for this
    milestone."""
    scored = [row for row in rows if row.scored]
    with_category = [row for row in scored if row.expected_category is not None]
    openers_true: Counter[str] = Counter(row.opener for row in rows if row.expected_needs_response)
    openers_false: Counter[str] = Counter(
        row.opener for row in rows if not row.expected_needs_response
    )
    return AttentionSummary(
        total=len(rows),
        matched=sum(1 for row in rows if row.matched),
        scored=len(scored),
        needs_response_agreed=sum(
            1 for row in scored if row.predicted_needs_response == row.expected_needs_response
        ),
        false_negatives=tuple(
            row.line
            for row in scored
            if row.expected_needs_response and not row.predicted_needs_response
        ),
        false_positives=tuple(
            row.line
            for row in scored
            if not row.expected_needs_response and row.predicted_needs_response
        ),
        category_exact=(
            sum(1 for row in with_category if row.predicted_category == row.expected_category),
            len(with_category),
        ),
        errors=tuple(row.line for row in rows if row.error is not None),
        excluded=tuple(row.line for row in rows if row.excluded is not None),
        openers_expected_true={opener: openers_true[opener] for opener in _OPENERS},
        openers_expected_false={opener: openers_false[opener] for opener in _OPENERS},
        model_opened_on_expected_false=tuple(
            row.line for row in rows if not row.expected_needs_response and row.opener == "model"
        ),
    )


def _lines(lines: tuple[int, ...]) -> str:
    return f"{len(lines)}" + (f" ({', '.join(f'#{n}' for n in lines)})" if lines else "")


def format_summary(summary: AttentionSummary) -> list[str]:
    """The summary block — counts and line numbers only, never text."""

    def openers(tally: dict[str, int]) -> str:
        return " ".join(f"{opener}={count}" for opener, count in tally.items())

    exact, out_of = summary.category_exact
    return [
        f"{summary.matched}/{summary.total} matched",
        f"needs_response agreed: {summary.needs_response_agreed}/{summary.scored}",
        f"false negatives (expected true, predicted false): {_lines(summary.false_negatives)}",
        f"false positives (expected false, predicted true): {_lines(summary.false_positives)}",
        "model-opened on expected-false (new moderator work): "
        f"{_lines(summary.model_opened_on_expected_false)}",
        f"category exact (secondary): {exact}/{out_of}",
        f"excluded before the model: {_lines(summary.excluded)}",
        f"errors: {_lines(summary.errors)}",
        f"opener, expected true: {openers(summary.openers_expected_true)}",
        f"opener, expected false: {openers(summary.openers_expected_false)}",
    ]


def format_row(row: AttentionRow, latency_ms: int | None) -> str:
    """One judged fixture's line — line number, labels, the model's answer, route and opener;
    never text. An error row has no line of its own: its error is reported as it happens."""
    rule = "opens" if row.rule_opens else "declines"
    if row.excluded is not None:
        return (
            f"[{'OK' if row.matched else 'MISMATCH'}] #{row.line} "
            f"expected={row.expected_needs_response} excluded={row.excluded} rule={rule} "
            f"opener={row.opener}"
        )
    status = "OK" if row.matched else ("FN" if row.expected_needs_response else "FP")
    return (
        f"[{status}] #{row.line} expected={row.expected_needs_response} "
        f"predicted={row.predicted_needs_response} category={row.predicted_category} "
        f"confidence={row.confidence} route={row.route} rule={rule} opener={row.opener} "
        f"latency_ms={latency_ms}"
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", default=None, help="Pin a named model profile, active or not (D-TG-161)."
    )
    parser.add_argument(
        "--prompt",
        default=None,
        choices=PROMPT_VERSIONS,
        help="Send this instruction instead of MODERATION_PROMPT_VERSION (D-TG-163).",
    )
    return parser.parse_args(argv)


def _load_fixtures() -> list[dict[str, Any]]:
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    lines = (
        raw.splitlines()
        if raw.strip()
        else _SHIPPED_FIXTURES.read_text(encoding="utf-8").splitlines()
    )
    return [json.loads(line) for line in lines if line.strip()]


def _facts(text: str | None) -> MessageFacts:
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


async def judge_attention_fixture(
    gateway: Gateway,
    fixture: dict[str, Any],
    *,
    line: int,
    prompt_version: str,
    floor: Decimal,
    threshold: Decimal,
    report_error: Callable[[int, str], None] | None = None,
) -> tuple[AttentionRow, int | None]:
    """Judges one attention fixture the way live traffic is, as a one-message burst: normalise,
    the rule set (`evaluate`), eligibility, the model, `route_prediction` (live), then
    `proposes_attention` — each the real function (N7), shared by this smoke and the
    qualification (D-TG-178). Returns the row and the call's latency in milliseconds, `None` when
    no answer came back. A failure is an error row, never a prediction; its detail goes only to
    `report_error`, and only when one is given."""
    expected: bool = fixture["needs_response"]
    text = normalize(fixture["text"])
    rule_opens = evaluate([text])
    base = AttentionRow(
        line=line,
        expected_needs_response=expected,
        expected_category=fixture.get("category"),
        rule_opens=rule_opens,
    )

    reason = eligibility(_facts(text))
    if reason is not None:
        return replace(base, excluded=reason), None

    model_input = build_model_input(text, prompt_version=prompt_version)
    started = time.monotonic()
    try:
        response = await gateway.generate_structured(
            StructuredRequest(messages=model_input, schema_model=MessageClassificationResult),
            role="moderation",
        )
    except GatewayError as exc:
        if report_error is not None:
            report_error(line, f"{type(exc).__name__}: {exc}")
        return replace(base, error=type(exc).__name__), None
    latency_ms = int((time.monotonic() - started) * 1000)
    answer = response.value
    if not 0 <= answer.confidence <= 1:
        if report_error is not None:
            report_error(line, "confidence_out_of_range")
        return replace(base, error="confidence_out_of_range"), latency_ms

    prediction = Prediction(
        category=answer.category,
        needs_response=answer.needs_response,
        needs_moderation=answer.needs_moderation,
        severity=answer.severity,
        confidence=quantise(answer.confidence),
    )
    route, route_reason = route_prediction(
        prediction, floor=floor, threshold=threshold, path="live"
    )
    row = replace(
        base,
        predicted_needs_response=answer.needs_response,
        predicted_category=answer.category,
        predicted_needs_moderation=answer.needs_moderation,
        confidence=answer.confidence,
        route=f"{route}/{route_reason}" if route_reason else route,
        model_proposes=proposes_attention(
            path="live",
            route=route,
            needs_response=answer.needs_response,
            category=answer.category,
        ),
    )
    return row, latency_ms


async def _run(argv: list[str]) -> None:
    args = _parse_args(argv)
    fixtures = _load_fixtures()

    settings = load_settings()
    prompt_version: str = args.prompt or settings.moderation_prompt_version
    floor = quantise(settings.moderation_confidence_floor)
    threshold = quantise(settings.moderation_incident_confidence)
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry: Any = (
        _PinnedRegistry(session_factory, profile_name=args.profile)
        if args.profile
        else ProfileRegistry(session_factory)
    )

    try:
        profile = await registry.resolve("moderation")
    except GatewayError as exc:
        print(f"smoke-attention: {exc}", file=sys.stderr)
        await engine.dispose()
        sys.exit(1)

    if profile.base_url:
        await _fail_if_unreachable(profile.base_url)

    print(
        f"smoke-attention: profile={profile.name} prompt={prompt_version} "
        f"floor={floor} threshold={threshold}"
    )

    gateway = Gateway(registry)
    rows: list[AttentionRow] = []

    for line, fixture in enumerate(fixtures, start=1):
        row, latency_ms = await judge_attention_fixture(
            gateway,
            fixture,
            line=line,
            prompt_version=prompt_version,
            floor=floor,
            threshold=threshold,
            report_error=_report_error,
        )
        rows.append(row)
        if row.error is None:
            print(format_row(row, latency_ms))

    await engine.dispose()

    summary = summarise(rows)
    print()
    for summary_line in format_summary(summary):
        print(summary_line)
    if summary.matched < summary.total:
        sys.exit(1)


def main() -> None:
    asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    main()
