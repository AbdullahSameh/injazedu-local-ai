"""`python -m app.scripts.smoke_attention` — the quick single-file check of an attention pair
(TG-M5.3, `specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` C4, D-TG-195).

Judges each fixture through the **real** gateway and the **real** model runtime, `role=
"attention"` — never scripted, and it writes nothing. Reads JSONL from standard input, one
`{"text", "needs_response", "intent"?, "peer"?}` object per line; falls back to the shipped
synthetic set (`attention_smoke_fixtures.jsonl`, no real student text) when standard input is a
TTY or empty. `--profile NAME` pins a named attention profile, active or not; `--prompt VERSION`
sends a frozen attention instruction instead of the configured
`MODERATION_ATTENTION_PROMPT_VERSION`, or `--candidate-file PATH` an unpinned wording, printed as
`CANDIDATE` with its SHA-256.

Each fixture is judged by the attention suite's own `judge_attention_line`
(`app.scripts.qualification.attention`), the live path for a one-message burst: the rule set first
(no call when it opens, AE2), then eligibility, then the model, then `needs_response_for` and
`judgement_proposes` — so there is one benchmark path, not two (N2). Until TG-M5.3 this smoke
judged the classification's needs-response through `proposes_attention`; that path is removed
(D-TG-191). The summary separates the judgement's own agreement (needs-response, intent) from
**who would open an item** (rule / model / nobody), split by label. Never prints a fixture's text.
Exits non-zero on any mismatch.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway import Gateway, GatewayError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.attention_judgement import attention_instruction
from app.infrastructure.config import ATTENTION_PROMPT_VERSIONS, load_settings
from app.scripts.qualification.attention import (
    AttentionRow,
    format_row,
    format_summary,
    judge_attention_line,
    summarise,
)
from app.scripts.smoke_moderation import _fail_if_unreachable, _PinnedRegistry, _report_error

_SHIPPED_FIXTURES = Path(__file__).resolve().parent / "attention_smoke_fixtures.jsonl"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default=None,
        help="Pin a named attention profile, active or not (D-TG-161).",
    )
    instruction = parser.add_mutually_exclusive_group()
    instruction.add_argument(
        "--prompt",
        default=None,
        choices=ATTENTION_PROMPT_VERSIONS,
        help="Send this frozen instruction instead of MODERATION_ATTENTION_PROMPT_VERSION.",
    )
    instruction.add_argument(
        "--candidate-file",
        default=None,
        help="Send this unpinned wording instead (D-TG-196); printed with its SHA-256.",
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


async def _run(argv: list[str]) -> None:
    args = _parse_args(argv)
    fixtures = _load_fixtures()

    settings = load_settings()
    if args.candidate_file is not None:
        raw = Path(args.candidate_file).read_bytes()
        instruction = raw.decode("utf-8")
        prompt = f"CANDIDATE {hashlib.sha256(raw).hexdigest()}"
    else:
        version = args.prompt or settings.moderation_attention_prompt_version
        if version is None:
            print(
                "smoke-attention: no attention instruction: MODERATION_ATTENTION_PROMPT_VERSION "
                "is blank; pass --prompt or --candidate-file",
                file=sys.stderr,
            )
            sys.exit(1)
        instruction = attention_instruction(version)
        prompt = version

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry: Any = (
        _PinnedRegistry(session_factory, profile_name=args.profile)
        if args.profile
        else ProfileRegistry(session_factory)
    )

    try:
        profile = await registry.resolve("attention")
    except GatewayError as exc:
        print(f"smoke-attention: {exc}", file=sys.stderr)
        await engine.dispose()
        sys.exit(1)
    if profile.role != "attention":
        print(
            f"smoke-attention: profile {profile.name!r} has role {profile.role!r}, "
            "not 'attention'",
            file=sys.stderr,
        )
        await engine.dispose()
        sys.exit(1)

    if profile.base_url:
        await _fail_if_unreachable(profile.base_url)

    print(f"smoke-attention: profile={profile.name} prompt={prompt}")

    gateway = Gateway(registry)
    rows: list[AttentionRow] = []

    for line, fixture in enumerate(fixtures, start=1):
        row, latency_ms = await judge_attention_line(
            gateway,
            fixture,
            line=line,
            instruction=instruction,
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
