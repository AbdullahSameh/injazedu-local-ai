"""Database probe: connectivity plus an explicit `vector` extension check (FR-010).

Reports down with the reason when the extension is absent — never silently skipped
(spec edge case, research D-03).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.application.health_service import ComponentReport, ComponentState

REQUIRED = True


async def check(engine: AsyncEngine) -> ComponentReport:
    async with engine.connect() as conn:
        server_version = (await conn.execute(text("SHOW server_version"))).scalar_one()
        ext_version = (
            await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one_or_none()

    if ext_version is None:
        return ComponentReport(
            status=ComponentState.DOWN,
            required=REQUIRED,
            detail="extension 'vector' is not installed",
        )

    return ComponentReport(
        status=ComponentState.OK,
        required=REQUIRED,
        detail=f"PostgreSQL {server_version}, extension vector {ext_version}",
    )
