"""Model-runtime probe: informational only, never changes the overall verdict (FR-008, D-18)."""

from __future__ import annotations

import httpx

from app.application.health_service import ComponentReport, ComponentState

REQUIRED = False

PROBE_TIMEOUT_S = 1.0


async def check(base_url: str) -> ComponentReport:
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        response = await client.get(f"{base_url}/api/version")
        response.raise_for_status()
        version = response.json().get("version", "unknown")

    return ComponentReport(status=ComponentState.OK, required=REQUIRED, detail=f"Ollama {version}")
