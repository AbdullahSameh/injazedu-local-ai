#!/usr/bin/env bash
# The quality gate: ruff, mypy, pytest, the PHP feature test, and a secret scan (FR-025).
#
# Must pass with Ollama quit and no network egress (FR-026, SC-009) — everything here is either
# static analysis or talks to the local Postgres/Redis containers `make up` already started.
#
# Each connection variable falls back to its value in .env / .env.testing, but an already-exported
# value (e.g. `TEST_DATABASE_URL=... make check`, used to prove the guard aborts — SC-010) always
# wins. Never unconditionally re-source the file over an operator's explicit override.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

_from_file() {
  local var="$1" file="$2"
  grep "^${var}=" "$file" 2>/dev/null | head -1 | cut -d= -f2-
}

: "${DATABASE_URL:=$(_from_file DATABASE_URL .env)}"
: "${REDIS_URL:=$(_from_file REDIS_URL .env)}"
: "${AI_APP_PASSWORD:=$(_from_file AI_APP_PASSWORD .env)}"
: "${AI_CONTROL_PASSWORD:=$(_from_file AI_CONTROL_PASSWORD .env)}"
: "${TEST_DATABASE_URL:=$(_from_file TEST_DATABASE_URL .env.testing)}"
export DATABASE_URL REDIS_URL AI_APP_PASSWORD AI_CONTROL_PASSWORD TEST_DATABASE_URL

echo "== ruff =="
(cd apps/ai-api && uv run ruff check .)

echo
echo "== mypy =="
(cd apps/ai-api && uv run mypy app/)

echo
echo "== pytest (aborts here if TEST_DATABASE_URL is unsafe — Principle II) =="
(cd apps/ai-api && uv run pytest)

# test_migrations.py deliberately leaves the test database's schema empty at teardown (T033) — put
# it back to head before the PHP feature test, which needs `users` to exist, runs against it.
echo
echo "== restoring the test schema for the PHP feature test =="
(cd apps/ai-api && MIGRATOR_DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head)

echo
echo "== PHP feature test =="
(cd apps/ai-control && vendor/bin/phpunit --testsuite=Feature)

echo
echo "== secret scan =="
./scripts/scan_secrets.sh

echo
echo "ALL CHECKS PASSED"
