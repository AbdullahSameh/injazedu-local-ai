"""`python -m app.scripts.smoke_moderation` — the operator's live-model smoke test
(`contracts/classification-pipeline.md` §10 C4, tasks.md T041, quickstart.md §4).

Classifies each fixture through the **real** gateway and the **real** model runtime, `role=
"moderation"` — never scripted, and it writes no prediction. Reads JSONL from standard input, one
`{"text", "category", "needs_moderation"}` object per line; falls back to the shipped synthetic
set (`moderation_smoke_fixtures.jsonl`) when standard input is a TTY or empty, so `make
smoke-moderation` with no `FIXTURES` still runs. `--profile NAME` pins a named profile, active or
not (D-TG-161) — the operator smokes an inactive profile before switching it on (runbook §C's
TG-M5 row). `--prompt VERSION` sends a named instruction instead of the configured
`MODERATION_PROMPT_VERSION` (D-TG-163), so two instructions can be compared on one fixture file
before either is switched on.

Each line prints the route the live path would take — from `route_prediction` itself, at the
configured thresholds, never re-derived here (N7) — and the summary separates category agreement
from needs-moderation agreement, missed violations from false alarms (D-TG-162): a plain
"n/total matched" cannot tell an adjacent category from a violation the model let through. Never
prints a fixture's text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.errors import GatewayError, NoActiveProfileError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry, _row_to_profile
from app.application.moderation.classification import (
    PROMPT_VERSIONS,
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.domain.model_profile import ModelProfile
from app.domain.moderation.classification import Prediction, quantise, route_prediction
from app.infrastructure.config import load_settings
from app.infrastructure.models import model_profiles
from app.providers.llm.base import StructuredRequest

_PROBE_TIMEOUT_S = 2.0
_SHIPPED_FIXTURES = Path(__file__).resolve().parent / "moderation_smoke_fixtures.jsonl"
# The live path's routes (R2-R6) — `measurement_only` is catch-up only and never printed here.
_ROUTES: tuple[str, ...] = ("incident", "possible_violation", "review", "none")


class _PinnedRegistry:
    """Resolves one named profile regardless of `is_active` (D-TG-161) — a bare duck-typed
    stand-in for `ProfileRegistry`, since `Gateway` only ever calls `.resolve(role)`."""

    def __init__(self, session_factory: Any, *, profile_name: str) -> None:
        self._session_factory = session_factory
        self._profile_name = profile_name

    async def resolve(self, role: str) -> ModelProfile:
        async with self._session_factory() as session:
            result = await session.execute(
                select(model_profiles).where(model_profiles.c.name == self._profile_name)
            )
            row = result.first()
        if row is None:
            raise NoActiveProfileError(
                f"no profile named {self._profile_name!r}", profile_name=self._profile_name
            )
        return _row_to_profile(row)


@dataclass(frozen=True)
class SmokeRow:
    """One fixture's outcome. `predicted_*` and `route` are `None` when the call failed
    (`error` names the gateway error) — a failure is never scored as a prediction."""

    line: int
    expected_category: str
    expected_needs_moderation: bool
    predicted_category: str | None = None
    predicted_needs_moderation: bool | None = None
    route: str | None = None
    error: str | None = None

    @property
    def matched(self) -> bool:
        return (
            self.error is None
            and self.predicted_category == self.expected_category
            and self.predicted_needs_moderation == self.expected_needs_moderation
        )


@dataclass(frozen=True)
class SmokeSummary:
    total: int
    matched: int
    category_exact: int
    needs_moderation_agreed: int
    false_negatives: tuple[int, ...]
    false_positives: tuple[int, ...]
    errors: tuple[int, ...]
    violation_routes: dict[str, int] = field(default_factory=dict)
    legitimate_routes: dict[str, int] = field(default_factory=dict)


def summarise(rows: list[SmokeRow]) -> SmokeSummary:
    """Pure scoring over the fixture outcomes. A false negative is a fixture labelled
    needs-moderation that the model said needs none; a false positive is the reverse. Routes are
    tallied separately for fixtures labelled as violations and as legitimate (the bare route name;
    the reason is shown per line)."""
    scored = [row for row in rows if row.error is None]
    violation_routes: Counter[str] = Counter()
    legitimate_routes: Counter[str] = Counter()
    for row in scored:
        assert row.route is not None
        tally = violation_routes if row.expected_needs_moderation else legitimate_routes
        tally[row.route.split("/", 1)[0]] += 1
    return SmokeSummary(
        total=len(rows),
        matched=sum(1 for row in rows if row.matched),
        category_exact=sum(1 for row in scored if row.predicted_category == row.expected_category),
        needs_moderation_agreed=sum(
            1 for row in scored if row.predicted_needs_moderation == row.expected_needs_moderation
        ),
        false_negatives=tuple(
            row.line
            for row in scored
            if row.expected_needs_moderation and not row.predicted_needs_moderation
        ),
        false_positives=tuple(
            row.line
            for row in scored
            if not row.expected_needs_moderation and row.predicted_needs_moderation
        ),
        errors=tuple(row.line for row in rows if row.error is not None),
        violation_routes={route: violation_routes[route] for route in _ROUTES},
        legitimate_routes={route: legitimate_routes[route] for route in _ROUTES},
    )


def _lines(lines: tuple[int, ...]) -> str:
    return f"{len(lines)}" + (f" ({', '.join(f'#{n}' for n in lines)})" if lines else "")


def format_summary(summary: SmokeSummary) -> list[str]:
    """The summary block. Its first line is the one the smoke test has always printed."""

    def routes(tally: dict[str, int]) -> str:
        return " ".join(f"{route}={count}" for route, count in tally.items())

    return [
        f"{summary.matched}/{summary.total} matched",
        f"category exact: {summary.category_exact}/{summary.total}",
        f"needs_moderation agreed: {summary.needs_moderation_agreed}/{summary.total}",
        f"false negatives (expected true, predicted false): {_lines(summary.false_negatives)}",
        f"false positives (expected false, predicted true): {_lines(summary.false_positives)}",
        f"errors: {_lines(summary.errors)}",
        f"routes, violations: {routes(summary.violation_routes)}",
        f"routes, legitimate: {routes(summary.legitimate_routes)}",
    ]


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
    if sys.stdin.isatty():
        raw = ""
    else:
        raw = sys.stdin.read()
    lines = (
        raw.splitlines()
        if raw.strip()
        else _SHIPPED_FIXTURES.read_text(encoding="utf-8").splitlines()
    )
    return [json.loads(line) for line in lines if line.strip()]


async def _fail_if_unreachable(base_url: str) -> None:
    root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            response = await client.get(f"{root}/api/version")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"smoke-moderation: model runtime unreachable at {base_url}: {exc}", file=sys.stderr)
        sys.exit(1)


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
        print(f"smoke-moderation: {exc}", file=sys.stderr)
        await engine.dispose()
        sys.exit(1)

    if profile.base_url:
        await _fail_if_unreachable(profile.base_url)

    print(
        f"smoke-moderation: profile={profile.name} prompt={prompt_version} "
        f"floor={floor} threshold={threshold}"
    )

    gateway = Gateway(registry)
    rows: list[SmokeRow] = []

    for line, fixture in enumerate(fixtures, start=1):
        expected = f"{fixture['category']}/{fixture['needs_moderation']}"
        text = normalize(fixture["text"])
        model_input = build_model_input(text, prompt_version=prompt_version)
        started = time.monotonic()
        try:
            response = await gateway.generate_structured(
                StructuredRequest(messages=model_input, schema_model=MessageClassificationResult),
                role="moderation",
            )
        except GatewayError as exc:
            print(f"  ERROR #{line}: {type(exc).__name__}: {exc}", file=sys.stderr)
            rows.append(
                SmokeRow(
                    line=line,
                    expected_category=fixture["category"],
                    expected_needs_moderation=fixture["needs_moderation"],
                    error=type(exc).__name__,
                )
            )
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        answer = response.value
        if not 0 <= answer.confidence <= 1:
            # O3: an out-of-range answer is a failure, never a prediction.
            print(f"  ERROR #{line}: confidence_out_of_range", file=sys.stderr)
            rows.append(
                SmokeRow(
                    line=line,
                    expected_category=fixture["category"],
                    expected_needs_moderation=fixture["needs_moderation"],
                    error="confidence_out_of_range",
                )
            )
            continue
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
        row = SmokeRow(
            line=line,
            expected_category=fixture["category"],
            expected_needs_moderation=fixture["needs_moderation"],
            predicted_category=answer.category,
            predicted_needs_moderation=answer.needs_moderation,
            route=f"{route}/{route_reason}" if route_reason else route,
        )
        rows.append(row)
        status = "OK" if row.matched else "MISMATCH"
        print(
            f"[{status}] #{line} expected={expected} "
            f"predicted={answer.category}/{answer.needs_moderation} "
            f"confidence={answer.confidence} route={row.route} latency_ms={latency_ms}"
        )

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
