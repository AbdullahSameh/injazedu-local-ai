"""FastAPI entrypoint. Configuration is validated before the port is bound (FR-005)."""

from __future__ import annotations

import dramatiq
from fastapi import FastAPI

from app.api.v1.health import SERVICE_VERSION
from app.api.v1.health import router as health_router
from app.infrastructure.config import load_settings
from app.infrastructure.db import make_engine
from app.infrastructure.logging import configure_logging
from app.infrastructure.queue import make_broker
from app.infrastructure.redis import make_redis_client


def create_app() -> FastAPI:
    settings = load_settings()
    configure_logging(settings.log_level)
    dramatiq.set_broker(make_broker(settings))

    from app.api.v1.diagnostics import router as diagnostics_router

    app = FastAPI(title="InjazEdu Local AI — ai-api", version=SERVICE_VERSION)
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.redis = make_redis_client(settings)

    app.include_router(health_router)
    app.include_router(diagnostics_router)
    return app


app = create_app()
