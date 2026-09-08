"""`make doctor`'s answer to "is an active profile's model actually pulled?" (T069).

An activated-but-unpulled profile is otherwise invisible until the first real call 404s —
`ModelNotAvailableError` mid-run rather than a pre-flight check. Queries the active
`model_profiles` rows and, for each `ollama` one, checks the model against `/api/tags`.
Exempt from testing: a diagnostic pretty-printer, not a safety mechanism (plan.md's
Constitution Check) — the same standing as `print_profiles.py`.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import create_engine

from app.infrastructure.config import load_settings

_ACTIVE_QUERY = text(
    "SELECT name, role, provider, model, base_url "
    "FROM model_profiles WHERE is_active ORDER BY role, name"
)

_TAGS_TIMEOUT_S = 2.0


def _ollama_models(base_url: str) -> set[str] | None:
    """Model names Ollama reports as pulled, or `None` if the runtime could not be reached."""
    root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
    try:
        response = httpx.get(f"{root}/api/tags", timeout=_TAGS_TIMEOUT_S)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return {model["name"] for model in response.json().get("models", [])}


def check_profiles_pulled() -> int:
    """Prints one line per active profile; returns the process exit code (0 = all clear)."""
    try:
        settings = load_settings()
        engine = create_engine(settings.database_url)
        try:
            with engine.connect() as conn:
                rows: list[Any] = list(conn.execute(_ACTIVE_QUERY))
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 — doctor reports a reason, never a stack trace
        print(f"  SKIPPED: model_profiles not reachable ({exc})")
        return 0

    if not rows:
        print("  MISSING: no active profiles — run `make seed-profiles`, then activate one")
        return 1

    tags_by_base_url: dict[str, set[str] | None] = {}
    exit_code = 0
    for row in rows:
        if row.provider != "ollama":
            print(
                f"  SKIP     {row.name} ({row.role}): "
                f"provider={row.provider!r}, not checkable here"
            )
            continue

        if row.base_url not in tags_by_base_url:
            tags_by_base_url[row.base_url] = _ollama_models(row.base_url)
        models = tags_by_base_url[row.base_url]

        if models is None:
            print(f"  SKIP     {row.name} ({row.role}): Ollama unreachable at {row.base_url}")
        elif row.model in models:
            print(f"  OK       {row.name} ({row.role}): {row.model} is pulled")
        else:
            print(
                f"  MISSING  {row.name} ({row.role}): {row.model} is NOT pulled — "
                f"run `ollama pull {row.model}`"
            )
            exit_code = 1

    return exit_code


def main() -> None:
    sys.exit(check_profiles_pulled())


if __name__ == "__main__":
    main()
