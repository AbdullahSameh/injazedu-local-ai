from __future__ import annotations

import pytest
from app.application.health_service import (
    ComponentReport,
    ComponentState,
    ProbeSpec,
    run_health_check,
)


def _spec(name: str, status: ComponentState, required: bool) -> ProbeSpec:
    report = ComponentReport(status=status, required=required)

    async def _run() -> ComponentReport:
        return report

    return ProbeSpec(name=name, required=required, run=_run)


@pytest.mark.asyncio
async def test_overall_ok_only_when_all_required_components_are_ok() -> None:
    probes = [
        _spec("database", ComponentState.OK, True),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.OK, False),
    ]

    result = await run_health_check(probes)

    assert result.status == ComponentState.OK
    assert set(result.components) == {"database", "broker", "worker", "model_runtime"}


@pytest.mark.asyncio
async def test_overall_down_when_any_required_component_is_down() -> None:
    probes = [
        _spec("database", ComponentState.DOWN, True),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.OK, False),
    ]

    result = await run_health_check(probes)

    assert result.status == ComponentState.DOWN


@pytest.mark.asyncio
async def test_model_runtime_down_leaves_overall_verdict_ok() -> None:
    probes = [
        _spec("database", ComponentState.OK, True),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.DOWN, False),
    ]

    result = await run_health_check(probes)

    assert result.status == ComponentState.OK
    assert result.components["model_runtime"].status == ComponentState.DOWN


@pytest.mark.asyncio
async def test_overall_degraded_when_a_required_component_is_degraded_and_none_are_down() -> None:
    probes = [
        _spec("database", ComponentState.DEGRADED, True),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.OK, False),
    ]

    result = await run_health_check(probes)

    assert result.status == ComponentState.DEGRADED


@pytest.mark.asyncio
async def test_a_probe_that_raises_reports_down_without_crashing_the_report() -> None:
    async def _boom() -> ComponentReport:
        raise ConnectionError("connection refused")

    probes = [
        ProbeSpec(name="database", required=True, run=_boom),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.OK, False),
    ]

    result = await run_health_check(probes)

    assert result.status == ComponentState.DOWN
    assert result.components["database"].status == ComponentState.DOWN
    assert "connection refused" in result.components["database"].detail


@pytest.mark.asyncio
async def test_a_probe_that_hangs_is_capped_at_the_timeout() -> None:
    import asyncio

    async def _hang() -> ComponentReport:
        await asyncio.sleep(10)
        return ComponentReport(status=ComponentState.OK, required=True)

    probes = [
        ProbeSpec(name="database", required=True, run=_hang),
        _spec("broker", ComponentState.OK, True),
        _spec("worker", ComponentState.OK, True),
        _spec("model_runtime", ComponentState.OK, False),
    ]

    result = await run_health_check(probes, timeout_s=0.05)

    assert result.status == ComponentState.DOWN
    assert result.components["database"].status == ComponentState.DOWN
    assert "timed out" in result.components["database"].detail
