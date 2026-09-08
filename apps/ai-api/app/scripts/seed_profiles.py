"""Seed the §16.1 model roster into `model_profiles` (research D-36, data-model.md §1).

`ON CONFLICT (name) DO NOTHING` — idempotent, and never overwrites an operator's edit to a
`base_url` or any other column. Run via `make seed-profiles`, deliberately separate from
`make migrate` so a fresh-database migration never resurrects a profile the operator deleted.

Uses `DATABASE_URL` (the `ai_app` identity) — seeding is DML, not DDL (M0 D-04 default
privileges already grant `ai_app` INSERT on this table).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import create_engine

from app.infrastructure.config import load_settings

_SEED_SQL = text(
    "INSERT INTO model_profiles "
    "(name, provider, base_url, model, role, params, dim, api_key_env, is_active) "
    "VALUES (:name, :provider, :base_url, :model, :role, CAST(:params AS JSONB), :dim, "
    ":api_key_env, :is_active) "
    "ON CONFLICT (name) DO NOTHING"
)

_ROSTER: tuple[dict[str, object], ...] = (
    {
        "name": "ollama-gemma4-e2b",
        "provider": "ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "gemma4:e2b-it-qat",
        "role": "llm",
        "params": '{"num_ctx": 8192, "num_predict": 1024, "temperature": 0.6}',
        "dim": None,
        "api_key_env": None,
        "is_active": True,
    },
    {
        "name": "ollama-qwen3-8b",
        "provider": "ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "qwen3:8b",
        "role": "llm",
        "params": '{"num_ctx": 8192, "num_predict": 1024, "temperature": 0.6}',
        "dim": None,
        "api_key_env": None,
        "is_active": False,
    },
    {
        "name": "ollama-gemma3-4b",
        "provider": "ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "gemma3:4b-it-qat",
        "role": "llm",
        "params": '{"num_ctx": 8192, "num_predict": 1024, "temperature": 0.6}',
        "dim": None,
        "api_key_env": None,
        "is_active": False,
    },
    {
        "name": "ollama-embeddinggemma-300m",
        "provider": "ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "embeddinggemma:300m-qat-q4_0",
        "role": "embedding",
        "params": (
            '{"batch_size": 32, '
            '"prefix_document": "title: none | text: {text}", '
            '"prefix_query": "task: search result | query: {text}"}'
        ),
        "dim": 768,
        "api_key_env": None,
        "is_active": True,
    },
    {
        "name": "ollama-bge-m3",
        "provider": "ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "bge-m3",
        "role": "embedding",
        "params": '{"batch_size": 32}',
        "dim": 1024,
        "api_key_env": None,
        "is_active": False,
    },
)


def seed_profiles() -> int:
    """Insert the roster, skipping any name that already exists. Returns rows actually inserted."""
    settings = load_settings()
    engine = create_engine(settings.database_url)
    inserted = 0
    try:
        with engine.begin() as conn:
            for row in _ROSTER:
                result = conn.execute(_SEED_SQL, row)
                inserted += result.rowcount
    finally:
        engine.dispose()
    return inserted


def main() -> None:
    inserted = seed_profiles()
    print(f"seed-profiles: {inserted} row(s) inserted, {len(_ROSTER) - inserted} already present")


if __name__ == "__main__":
    main()
