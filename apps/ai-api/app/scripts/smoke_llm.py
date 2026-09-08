"""One real round-trip against the local model runtime: a structured generation and an
embedding, printing shape, token counts and latency (§22, FR-028, SC-015).

Reports an unreachable runtime immediately — a short reachability probe runs before the real
call, so `make smoke-llm` says "Ollama is not running" in a couple of seconds rather than
waiting out the full `GATEWAY_CALL_TIMEOUT_S` deadline.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.errors import GatewayError
from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.infrastructure.config import load_settings
from app.providers.llm.base import Message, StructuredRequest

_PROBE_TIMEOUT_S = 2.0


class _SmokeAnswer(BaseModel):
    greeting: str
    confidence: float


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Override the profile's num_predict — e.g. a small value to force D-26's "
        "truncation path and confirm it raises ModelTruncatedError, not a JSON parse error.",
    )
    return parser.parse_args(argv)


async def _fail_if_unreachable(base_url: str) -> None:
    root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            response = await client.get(f"{root}/api/version")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"smoke-llm: model runtime unreachable at {base_url}: {exc}", file=sys.stderr)
        sys.exit(1)


async def _run(argv: list[str]) -> None:
    args = _parse_args(argv)
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = ProfileRegistry(session_factory)

    try:
        llm_profile = await registry.resolve("llm")
        embedding_profile = await registry.resolve("embedding")
    except GatewayError as exc:
        print(f"smoke-llm: {exc}", file=sys.stderr)
        await engine.dispose()
        sys.exit(1)

    if llm_profile.base_url:
        await _fail_if_unreachable(llm_profile.base_url)

    gateway = Gateway(registry)

    try:
        print("== structured generation ==")
        started = time.monotonic()
        structured = await gateway.generate_structured(
            StructuredRequest(
                messages=[
                    Message(
                        role="user",
                        content="Say hello and rate your confidence from 0 to 1.",
                    )
                ],
                schema_model=_SmokeAnswer,
                max_output_tokens=args.max_output_tokens,
            )
        )
        print(f"profile:            {structured.profile_name}")
        print(f"value:              {structured.value.model_dump()}")
        print(f"prompt_tokens:      {structured.usage.prompt_tokens}")
        print(f"completion_tokens:  {structured.usage.completion_tokens}")
        print(f"latency_ms:         {structured.latency_ms}")

        print()
        print("== embedding ==")
        embedding = await gateway.embed("This is a smoke-test sentence.", "document")
        print(f"profile:            {embedding.profile_name}")
        print(f"dim:                {len(embedding.vector)}")
        assert embedding_profile.dim is None or len(embedding.vector) == embedding_profile.dim

        print()
        print(f"total wall time:    {int((time.monotonic() - started) * 1000)}ms")
    except GatewayError as exc:
        print(f"smoke-llm: {type(exc).__name__}: {exc}", file=sys.stderr)
        await engine.dispose()
        sys.exit(1)

    await engine.dispose()


def main() -> None:
    asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    main()
