"""Model-runtime probe: informational only, never changes the overall verdict (FR-008, D-18).

M1 adds the `gateway` block — active profile names and `capture_payloads` state
(`contracts/gateway-interface.md` §8) — read straight from `model_profiles`, independent of
whether the runtime itself answers, so the operator sees debug capture's state even while it is
down (FR-039's visibility half).
"""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.application.health_service import ComponentReport, ComponentState
from app.infrastructure.models import model_profiles

REQUIRED = False

PROBE_TIMEOUT_S = 1.0


async def _gateway_block(
    engine: AsyncEngine, capture_payloads: bool
) -> dict[str, str | bool | None]:
    async with engine.connect() as conn:
        result = await conn.execute(
            select(model_profiles.c.role, model_profiles.c.name).where(
                model_profiles.c.is_active.is_(True)
            )
        )
        active_by_role = {row.role: row.name for row in result}

    return {
        "llm_profile": active_by_role.get("llm"),
        "embedding_profile": active_by_role.get("embedding"),
        "capture_payloads": capture_payloads,
    }


async def check(base_url: str, engine: AsyncEngine, capture_payloads: bool) -> ComponentReport:
    gateway = await _gateway_block(engine, capture_payloads)

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            response = await client.get(f"{base_url}/api/version")
            response.raise_for_status()
            version = response.json().get("version", "unknown")
    except httpx.HTTPError as exc:
        return ComponentReport(
            status=ComponentState.DOWN, required=REQUIRED, detail=str(exc), gateway=gateway
        )

    return ComponentReport(
        status=ComponentState.OK,
        required=REQUIRED,
        detail=f"Ollama {version}",
        gateway=gateway,
    )
