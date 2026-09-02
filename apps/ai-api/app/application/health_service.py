"""Concurrent component health checks with a uniform per-probe timeout (FR-007, research D-08).

Each probe reports its own status; this module owns timing, the timeout cap, exception handling,
and the aggregation rule that decides the overall verdict.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_serializer

DEFAULT_PROBE_TIMEOUT_S = 1.0


class ComponentState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ComponentState
    required: bool
    latency_ms: int = 0
    detail: str = ""


class HealthReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ComponentState
    checked_at: datetime
    duration_ms: int
    components: dict[str, ComponentReport]

    @field_serializer("checked_at")
    def _serialize_checked_at(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    required: bool
    run: Callable[[], Awaitable[ComponentReport]]


def aggregate(components: dict[str, ComponentReport]) -> ComponentState:
    """Overall verdict: ok only when every required component is ok."""
    required = [c for c in components.values() if c.required]
    if any(c.status == ComponentState.DOWN for c in required):
        return ComponentState.DOWN
    if any(c.status == ComponentState.DEGRADED for c in required):
        return ComponentState.DEGRADED
    return ComponentState.OK


async def _run_one(probe: ProbeSpec, timeout_s: float) -> ComponentReport:
    start = time.monotonic()
    try:
        report = await asyncio.wait_for(probe.run(), timeout=timeout_s)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return report.model_copy(update={"latency_ms": elapsed_ms})
    except TimeoutError:
        return ComponentReport(
            status=ComponentState.DOWN,
            required=probe.required,
            latency_ms=int(timeout_s * 1000),
            detail=f"timed out after {timeout_s:g}s",
        )
    except Exception as exc:  # noqa: BLE001 — any probe failure reports down, never crashes the endpoint
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ComponentReport(
            status=ComponentState.DOWN,
            required=probe.required,
            latency_ms=elapsed_ms,
            detail=str(exc),
        )


async def run_health_check(
    probes: list[ProbeSpec], timeout_s: float = DEFAULT_PROBE_TIMEOUT_S
) -> HealthReport:
    start = time.monotonic()
    results = await asyncio.gather(*(_run_one(probe, timeout_s) for probe in probes))
    components = {probe.name: result for probe, result in zip(probes, results, strict=True)}
    duration_ms = int((time.monotonic() - start) * 1000)
    return HealthReport(
        status=aggregate(components),
        checked_at=datetime.now(UTC),
        duration_ms=duration_ms,
        components=components,
    )
