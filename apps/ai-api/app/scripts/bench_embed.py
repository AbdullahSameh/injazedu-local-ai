"""Measures SC-007: routing embedding work through the gateway must cost no more than 10%
throughput against a direct call, at the documented batch size (`plan.md`'s Performance Goals,
session baseline **15.32 chunks/s** — research §0 probe 6, D-28).

M1 stores no corpus yet (`quickstart.md` §5 — ingestion is M4's), so there are no real textbook
passages on this machine to measure against. This benchmark instead generates synthetic passages
sized like the ones probe 6 measured (~1,944 characters) — same size class, not real book text.

Both paths call the same `OpenAICompatibleEmbeddingProvider`, so this isolates exactly the
overhead T072 is asking about: the gateway's breaker check, lane acquisition/release and retry
wrapper around one otherwise-identical call — not a different HTTP path.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.gateway.gateway import Gateway
from app.application.gateway.registry import ProfileRegistry
from app.domain.model_profile import ModelProfile
from app.infrastructure.config import load_settings
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

_PASSAGE_LEN = 1944  # research §0 probe 6's measured passage size
_BATCH_SIZE = 32  # the documented default (data-model.md §1, D-28)
_OVERHEAD_BUDGET_PCT = 10.0  # SC-007


def _synthetic_passages(count: int, length: int) -> list[str]:
    """`count` distinct passages of `length` characters — same size class as probe 6's real
    1,944-char Arabic chunks, not real textbook content (none exists in M1 — see module docstring).
    """
    unit = "the quick brown fox jumps over the lazy dog. "
    body = (unit * (length // len(unit) + 1))[:length]
    return [f"{i:04d} {body}"[:length] for i in range(count)]


async def _time_direct(profile: ModelProfile, texts: list[str]) -> float:
    provider = OpenAICompatibleEmbeddingProvider(profile)
    started = time.monotonic()
    await provider.embed_many(texts, "document", batch_size=_BATCH_SIZE)
    return time.monotonic() - started


async def _time_through_gateway(registry: ProfileRegistry, texts: list[str]) -> float:
    gateway = Gateway(registry)
    started = time.monotonic()
    await gateway.embed_many(texts, "document", batch_size=_BATCH_SIZE)
    return time.monotonic() - started


async def _run() -> int:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = ProfileRegistry(session_factory)

    profile = await registry.resolve("embedding")
    texts = _synthetic_passages(_BATCH_SIZE, _PASSAGE_LEN)

    # Untimed warm-up: Ollama loads the model into memory on its first request, and whichever
    # path runs first would otherwise absorb that one-time cost — turning "gateway adds 10%" into
    # "gateway ran second." One throwaway call puts both timed calls on equal footing.
    await _time_direct(profile, texts)

    direct_s = await _time_direct(profile, texts)
    gateway_s = await _time_through_gateway(registry, texts)
    await engine.dispose()

    direct_rate = _BATCH_SIZE / direct_s
    gateway_rate = _BATCH_SIZE / gateway_s
    overhead_pct = (gateway_s - direct_s) / direct_s * 100

    print(f"profile:            {profile.name}")
    print(f"batch size:         {_BATCH_SIZE}")
    print(f"direct:             {direct_s:.3f}s ({direct_rate:.2f} chunks/s)")
    print(f"through gateway:    {gateway_s:.3f}s ({gateway_rate:.2f} chunks/s)")
    print(
        f"overhead:           {overhead_pct:+.1f}% "
        f"(budget: <= {_OVERHEAD_BUDGET_PCT:.0f}%, SC-007)"
    )

    if overhead_pct > _OVERHEAD_BUDGET_PCT:
        print("bench-embed: FAILED — gateway overhead exceeds the SC-007 budget", file=sys.stderr)
        return 1
    print("bench-embed: OK — gateway overhead within the SC-007 budget")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
