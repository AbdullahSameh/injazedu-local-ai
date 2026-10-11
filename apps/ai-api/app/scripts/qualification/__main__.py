"""`python -m app.scripts.qualification` — qualification, version 2
(`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md`, D-TG-194).

Judges one task's pair, a model profile and an instruction, over that task's benchmark sets and
prints whether it may run in production: `QUALIFIED`, `NOT QUALIFIED` or `INCOMPLETE` — or
`CANDIDATE` for an unpinned wording. A composition root. It writes nothing (C2) and never prints a
fixture's text (C3).

`--task attention|moderation`; `--profile NAME`, a profile whose role is the task's, active or not
(C1); `--prompt VERSION` from the task's allowlist (default: `MODERATION_ATTENTION_PROMPT_VERSION`
or `MODERATION_PROMPT_VERSION`), or, attention only, `--candidate-file PATH` under `--fixtures-dir`
(C6); `--fixtures-dir`, the operator's directory outside the repository; `--repeat` (default 2, at
least 2 for `QUALIFIED`); `--moderation-p95-ms` and `--serving single|concurrent` for the attention
suite's per-message estimate (S6). Each line is judged on a bare `Gateway`, which records no
accounting. Exit code: 0 qualified, 1 not qualified, 2 incomplete or a usage error, 3 candidate
(C5).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway import Gateway, GatewayError
from app.application.moderation.attention_judgement import attention_instruction
from app.application.moderation.classification import PROMPT_VERSIONS
from app.domain.moderation.classification import quantise
from app.infrastructure.config import ATTENTION_PROMPT_VERSIONS, load_settings
from app.scripts.qualification.attention import (
    SERVING_MODES,
    attention_detail,
    attention_judge,
    discover_attention_sets,
    evaluate_attention_gates,
    format_attention_report,
)
from app.scripts.qualification.core import (
    FixtureError,
    exit_code_for,
    judge_sets,
    load_sets,
    verdict,
)
from app.scripts.qualification.moderation import (
    discover_moderation_sets,
    evaluate_moderation_gates,
    format_moderation_report,
    moderation_detail,
    moderation_header,
    moderation_judge,
)
from app.scripts.smoke_moderation import _fail_if_unreachable, _PinnedRegistry

TASKS: tuple[str, ...] = ("attention", "moderation")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """The arguments of contract §1; any usage error exits 2 (C5)."""
    parser = argparse.ArgumentParser(
        prog="qualification", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    parser.add_argument("--task", required=True, choices=TASKS, help="The task to qualify.")
    parser.add_argument(
        "--profile", required=True, help="A profile with the task's role, active or not (C1)."
    )
    instruction = parser.add_mutually_exclusive_group()
    instruction.add_argument(
        "--prompt",
        default=None,
        help="An instruction from the task's allowlist (default: the task's setting).",
    )
    instruction.add_argument(
        "--candidate-file",
        default=None,
        help="Attention only: an unpinned wording under --fixtures-dir; the verdict is CANDIDATE.",
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
    parser.add_argument(
        "--moderation-p95-ms",
        type=_positive_int,
        default=None,
        help="Attention only: the moderation suite's p95, for the per-message estimate.",
    )
    parser.add_argument(
        "--serving",
        choices=SERVING_MODES,
        default="single",
        help="Attention only: the host's lane, for the per-message estimate (default single).",
    )
    args = parser.parse_args(argv)

    allowlist = ATTENTION_PROMPT_VERSIONS if args.task == "attention" else PROMPT_VERSIONS
    if args.prompt is not None and args.prompt not in allowlist:
        allowed = ", ".join(allowlist) or "empty: no attention instruction is frozen"
        parser.error(f"--prompt must be in the {args.task} allowlist ({allowed})")
    if args.candidate_file is not None:
        if args.task != "attention":
            parser.error("--candidate-file is for --task attention only")
        if (
            not Path(args.candidate_file)
            .resolve()
            .is_relative_to(Path(args.fixtures_dir).resolve())
        ):
            parser.error("--candidate-file must be under --fixtures-dir")
    return args


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)
    name = f"qualify-{args.task}"
    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.is_dir():
        print(f"{name}: no fixtures directory at {fixtures_dir}", file=sys.stderr)
        return 2
    candidate = args.candidate_file is not None
    specs = (
        discover_attention_sets(fixtures_dir, candidate=candidate)
        if args.task == "attention"
        else discover_moderation_sets(fixtures_dir)
    )
    try:
        loaded = load_sets(specs)
    except FixtureError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 2

    settings = load_settings()
    if args.task == "attention":
        if candidate:
            candidate_path = Path(args.candidate_file)
            if not candidate_path.is_file():
                print(f"{name}: no candidate file at {candidate_path}", file=sys.stderr)
                return 2
            raw = candidate_path.read_bytes()
            instruction = raw.decode("utf-8")
            prompt = f"CANDIDATE {hashlib.sha256(raw).hexdigest()}"
        else:
            version = args.prompt or settings.moderation_attention_prompt_version
            if version is None:
                print(
                    f"{name}: no attention instruction: MODERATION_ATTENTION_PROMPT_VERSION is "
                    "blank; pass --prompt or --candidate-file",
                    file=sys.stderr,
                )
                return 2
            instruction = attention_instruction(version)
            prompt = version
    else:
        prompt = args.prompt or settings.moderation_prompt_version
        floor = quantise(settings.moderation_confidence_floor)
        threshold = quantise(settings.moderation_incident_confidence)

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = _PinnedRegistry(session_factory, profile_name=args.profile)

    try:
        try:
            profile = await registry.resolve(args.task)
        except GatewayError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            return 2
        if profile.role != args.task:
            print(
                f"{name}: profile {profile.name!r} has role {profile.role!r}, not {args.task!r}",
                file=sys.stderr,
            )
            return 2
        if profile.base_url:
            try:
                await _fail_if_unreachable(profile.base_url)
            except SystemExit:
                return 2  # an unreachable runtime is no verdict on the model

        gateway = Gateway(registry)  # type: ignore[arg-type]
        if args.task == "attention":
            print(
                f"{name}: profile={profile.name} model={profile.model} prompt={prompt} "
                f"repeat={args.repeat}"
            )
            results = await judge_sets(
                specs,
                loaded,
                repeat=args.repeat,
                judge=attention_judge(gateway, instruction=instruction),
                detail=attention_detail,
            )
        else:
            print(
                moderation_header(
                    profile=profile.name,
                    model=profile.model,
                    prompt=prompt,
                    floor=floor,
                    threshold=threshold,
                    repeat=args.repeat,
                )
            )
            results = await judge_sets(
                specs,
                loaded,
                repeat=args.repeat,
                judge=moderation_judge(
                    gateway, prompt_version=prompt, floor=floor, threshold=threshold
                ),
                detail=moderation_detail,
            )
    finally:
        await engine.dispose()

    if args.task == "attention":
        gates = evaluate_attention_gates(results, repeat=args.repeat)
        report = format_attention_report(
            results,
            gates,
            profile=profile.name,
            model=profile.model,
            prompt=prompt,
            repeat=args.repeat,
            moderation_p95_ms=args.moderation_p95_ms,
            serving=args.serving,
            candidate=candidate,
        )
    else:
        gates = evaluate_moderation_gates(results, repeat=args.repeat)
        report = format_moderation_report(
            results,
            gates,
            profile=profile.name,
            model=profile.model,
            prompt=prompt,
            floor=floor,
            threshold=threshold,
            repeat=args.repeat,
        )
    print()
    for report_line in report:
        print(report_line)
    return exit_code_for(verdict(gates, candidate=candidate))


def main(argv: list[str] | None = None) -> None:
    sys.exit(asyncio.run(_run(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    main()
