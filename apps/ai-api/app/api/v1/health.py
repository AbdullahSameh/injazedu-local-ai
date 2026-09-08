"""GET /health/live and GET /health — matching contracts/openapi.yaml exactly."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.application.health_service import ComponentState, ProbeSpec, run_health_check
from app.application.probes import broker as broker_probe
from app.application.probes import database as database_probe
from app.application.probes import model_runtime as model_runtime_probe
from app.application.probes import worker as worker_probe

SERVICE_NAME = "ai-api"
SERVICE_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Always 200 while the process is up. Touches no dependency."""
    return {"status": "alive", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@router.get("/health")
async def readiness(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    engine = request.app.state.engine
    redis_client = request.app.state.redis

    probes = [
        ProbeSpec("database", database_probe.REQUIRED, lambda: database_probe.check(engine)),
        ProbeSpec("broker", broker_probe.REQUIRED, lambda: broker_probe.check(redis_client)),
        ProbeSpec(
            "worker",
            worker_probe.REQUIRED,
            lambda: worker_probe.check(redis_client, settings.worker_heartbeat_ttl_s),
        ),
        ProbeSpec(
            "model_runtime",
            model_runtime_probe.REQUIRED,
            lambda: model_runtime_probe.check(
                settings.ollama_base_url, engine, settings.gateway_capture_payloads
            ),
        ),
    ]

    report = await run_health_check(probes)
    status_code = 200 if report.status == ComponentState.OK else 503
    return JSONResponse(status_code=status_code, content=report.model_dump(mode="json"))
