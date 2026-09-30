"""`python -m app.scripts.smoke_moderation` — the operator's live-model smoke test
(`contracts/classification-pipeline.md` §10 C4, tasks.md T041, quickstart.md §4).

Classifies each fixture through the **real** gateway and the **real** model runtime, `role=
"moderation"` — never scripted, and it writes no prediction. Reads JSONL from standard input, one
`{"text", "category", "needs_moderation"}` object per line; falls back to the shipped synthetic
set (`moderation_smoke_fixtures.jsonl`) when standard input is a TTY or empty, so `make
smoke-moderation` with no `FIXTURES` still runs. `--profile NAME` pins a named profile, active or
not (D-TG-161) — the operator smokes an inactive profile before switching it on (runbook §C's
TG-M5 row).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.errors import GatewayError, NoActiveProfileError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry, _row_to_profile
from app.application.moderation.classification import (
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.domain.model_profile import ModelProfile
from app.infrastructure.config import load_settings
from app.infrastructure.models import model_profiles
from app.providers.llm.base import StructuredRequest

_PROBE_TIMEOUT_S = 2.0
_SHIPPED_FIXTURES = Path(__file__).resolve().parent / "moderation_smoke_fixtures.jsonl"


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


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", default=None, help="Pin a named model profile, active or not (D-TG-161)."
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

    gateway = Gateway(registry)
    mismatches = 0

    for fixture in fixtures:
        text = normalize(fixture["text"])
        model_input = build_model_input(text)
        started = time.monotonic()
        try:
            response = await gateway.generate_structured(
                StructuredRequest(messages=model_input, schema_model=MessageClassificationResult),
                role="moderation",
            )
        except GatewayError as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            mismatches += 1
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        answer = response.value
        matched = (
            answer.category == fixture["category"]
            and answer.needs_moderation == fixture["needs_moderation"]
        )
        if not matched:
            mismatches += 1
        status = "OK" if matched else "MISMATCH"
        print(
            f"[{status}] expected={fixture['category']}/{fixture['needs_moderation']} "
            f"predicted={answer.category}/{answer.needs_moderation} "
            f"confidence={answer.confidence} latency_ms={latency_ms}"
        )

    await engine.dispose()

    print()
    print(f"{len(fixtures) - mismatches}/{len(fixtures)} matched")
    if mismatches:
        sys.exit(1)


def main() -> None:
    asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    main()
