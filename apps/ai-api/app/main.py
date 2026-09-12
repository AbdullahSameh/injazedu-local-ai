"""FastAPI entrypoint. Configuration is validated before the port is bound (FR-005)."""

from __future__ import annotations

import dramatiq
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.health import SERVICE_VERSION
from app.api.v1.health import router as health_router
from app.application.health_service import ComponentReport, ComponentState
from app.application.moderation import ingestion_probe
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.db import make_engine
from app.infrastructure.logging import configure_logging
from app.infrastructure.queue import make_broker
from app.infrastructure.redis import make_redis_client


async def _telegram_ingestion_probe(engine: AsyncEngine, settings: Settings) -> ComponentReport:
    # ingestion_probe.py may not import health_service (the moderation forward boundary
    # permits only app.application.moderation), so the wrapping happens here (D-TG-31).
    result = await ingestion_probe.check(engine=engine, settings=settings)
    return ComponentReport(
        status=ComponentState(result.status),
        required=result.required,
        detail=result.detail,
        ingestion=result.ingestion,
    )


def create_app() -> FastAPI:
    settings = load_settings()
    configure_logging(settings.log_level)
    dramatiq.set_broker(make_broker(settings))

    from app.api.v1.diagnostics import router as diagnostics_router

    app = FastAPI(title="InjazEdu Local AI — ai-api", version=SERVICE_VERSION)
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.redis = make_redis_client(settings)
    # D-TG-31: always wired, regardless of credential — an absent credential is one of the four
    # states the block itself must distinguish (G6), not a reason to omit the block.
    app.state.ingestion_probe = lambda: _telegram_ingestion_probe(app.state.engine, settings)

    app.include_router(health_router)
    app.include_router(diagnostics_router)
    return app


app = create_app()
