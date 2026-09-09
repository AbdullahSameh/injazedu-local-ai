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
# REDIS_URL in .env names the docker-compose service ("redis"), for the containers that share
# its network — it does not resolve from the host running this script. pytest talks to the same
# Redis over its published port instead (mirrors TEST_DATABASE_URL vs. DATABASE_URL, above).
: "${REDIS_URL:=redis://localhost:6379/0}"
: "${AI_APP_PASSWORD:=$(_from_file AI_APP_PASSWORD .env)}"
: "${AI_CONTROL_PASSWORD:=$(_from_file AI_CONTROL_PASSWORD .env)}"
: "${TEST_DATABASE_URL:=$(_from_file TEST_DATABASE_URL .env.testing)}"
export DATABASE_URL REDIS_URL AI_APP_PASSWORD AI_CONTROL_PASSWORD TEST_DATABASE_URL

echo "== ruff =="
(cd apps/ai-api && uv run ruff check .)

echo
echo "== architecture (SC-001, SC-005) =="
# Mechanically enforces CLAUDE.md's rule: no httpx/ollama/openai import, and no embedding
# task-prefix string, outside apps/ai-api/app/providers/ (research D-40's "§5.1 rule 3 becomes
# mechanical"). Three pre-existing files are allowlisted — each talks to Ollama's bare admin API
# (`/api/version`, `/api/tags`) for liveness or "what's pulled", never a model or embedding call,
# so they sit outside SC-001's actual scope ("model and embedding calls ... go through the
# gateway") and outside the OpenAI-compatible surface the provider layer abstracts (D-24):
#   - app/application/probes/model_runtime.py  — M0's health probe (`/api/version`)
#   - app/scripts/smoke_llm.py                 — the fast-fail reachability pre-check (T049)
#   - app/scripts/check_profiles_pulled.py     — `make doctor`'s "is it pulled?" check (T069)
_ARCH_IMPORT_ALLOWLIST='apps/ai-api/app/application/probes/model_runtime\.py'
_ARCH_IMPORT_ALLOWLIST="${_ARCH_IMPORT_ALLOWLIST}|apps/ai-api/app/scripts/smoke_llm\.py"
_ARCH_IMPORT_ALLOWLIST="${_ARCH_IMPORT_ALLOWLIST}|apps/ai-api/app/scripts/check_profiles_pulled\.py"

if grep -rnE '^\s*(import|from)\s+(httpx|ollama|openai)\b' --include='*.py' apps/ai-api/app \
    | grep -v '^apps/ai-api/app/providers/' \
    | grep -vE "^(${_ARCH_IMPORT_ALLOWLIST}):"; then
  echo "Architecture violation: httpx/ollama/openai imported outside apps/ai-api/app/providers/ (SC-001)." >&2
  exit 1
fi

# The task-prefix templates (data-model.md §1) live only on the profile (D-29); the seed script
# is the one legitimate place their literal wording appears, as the data it writes to that column.
if grep -rnE 'task: search result|title: none' --include='*.py' apps/ai-api/app \
    | grep -v '^apps/ai-api/app/providers/' \
    | grep -v '^apps/ai-api/app/scripts/seed_profiles.py:'; then
  echo "Architecture violation: an embedding task-prefix string appears outside apps/ai-api/app/providers/ (SC-005)." >&2
  exit 1
fi
echo "  OK: no httpx/ollama/openai import and no task-prefix string outside app/providers/"

echo
echo "== moderation domain boundary (contracts/domain-boundary.md) =="
# Check 1 — forward allowlist (FR-002, FR-003, D-TG-18): a moderation module may import from
# app.* only the seven permitted prefixes. An allowlist, not a denylist — see D-TG-18.
_MOD_DIRS='apps/ai-api/app/domain/moderation apps/ai-api/app/application/moderation apps/ai-api/app/providers/telegram apps/ai-api/app/workers/tasks/moderation'
_MOD_ALLOWED='app\.domain\.moderation|app\.application\.moderation|app\.providers\.telegram|app\.workers\.tasks\.moderation|app\.application\.gateway|app\.infrastructure|app\.domain\.model_profile'

if grep -rnE '^[[:space:]]*(import|from)[[:space:]]+app\.' --include='*.py' ${_MOD_DIRS} \
    | grep -vE "(import|from)[[:space:]]+(${_MOD_ALLOWED})([.[:space:]]|\$)"; then
  echo "Architecture violation: a moderation module imports outside the seven permitted app.* prefixes (contracts/domain-boundary.md §2). Moderation modules may import only: app.domain.moderation, app.application.moderation, app.providers.telegram, app.workers.tasks.moderation, app.application.gateway, app.infrastructure, app.domain.model_profile." >&2
  exit 1
fi
echo "  OK: moderation imports only the 7 permitted prefixes"

# Check 2 — reverse rule (FR-002): no module under app/domain/, app/application/, app/providers/
# or app/api/, outside the moderation and telegram subdirectories, may import app.*moderation* or
# app.providers.telegram. Composition roots (app/main.py, app/workers/, app/scripts/) sit outside
# this scope by directory, so they are exempt without needing an allowlist entry.
if grep -rnE '^[[:space:]]*(import|from)[[:space:]]+app\.[A-Za-z0-9_.]*(moderation[A-Za-z0-9_.]*|providers\.telegram([.[:space:]]|$))' \
      --include='*.py' \
      apps/ai-api/app/domain apps/ai-api/app/application apps/ai-api/app/providers apps/ai-api/app/api \
    | grep -v '^apps/ai-api/app/domain/moderation/' \
    | grep -v '^apps/ai-api/app/application/moderation/' \
    | grep -v '^apps/ai-api/app/providers/telegram/'; then
  echo "Architecture violation: an assessment-side module imports moderation (contracts/domain-boundary.md §3). No module under app/domain/, app/application/, app/providers/ or app/api/, outside the moderation and telegram subdirectories, may import app.*moderation* or app.providers.telegram." >&2
  exit 1
fi
echo "  OK: no assessment-side module imports moderation"

# Check 3 — no Telegram SDK outside the provider (FR-004, D-TG-19). The provider speaks the Bot
# API over httpx, which the existing httpx rule already exempts inside app/providers/.
if grep -rnE '^[[:space:]]*(import|from)[[:space:]]+(telegram|aiogram|telebot|pyrogram|telethon)([.[:space:]]|$)' \
      --include='*.py' apps/ai-api/app \
    | grep -v '^apps/ai-api/app/providers/telegram/'; then
  echo "Architecture violation: a Telegram SDK (telegram/aiogram/telebot/pyrogram/telethon) is imported outside app/providers/telegram/ (contracts/domain-boundary.md §4). The provider speaks the Bot API over httpx; no SDK dependency is permitted anywhere else." >&2
  exit 1
fi
echo "  OK: no Telegram SDK imported outside app/providers/telegram/"

# Check 4 — no message text in logs (FR-030, D-TG-28). A backstop over the formatter's six-key
# whitelist (data-model.md §3): the whitelist closes the extra= route structurally, which leaves
# exactly one route, interpolation into the message string itself. Line-based, so a sufficiently
# creative multi-line call could evade it — the contract says so rather than implying this is total.
if grep -rnE 'logger\.(debug|info|warning|error|exception|critical)\(' \
      --include='*.py' ${_MOD_DIRS} \
    | grep -E '(original_text|normalized_text|redacted_text|message_text|caption)'; then
  echo "Architecture violation: a moderation module logs message text (contracts/domain-boundary.md §5). A logging call may not appear on a line that also references original_text, normalized_text, redacted_text, message_text or caption." >&2
  exit 1
fi
echo "  OK: no message text referenced on a logging call line in moderation modules"

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
