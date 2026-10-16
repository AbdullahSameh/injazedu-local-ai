#!/usr/bin/env bash
# Deploys a pushed revision to production (docs/runbooks/production-deployment.md §6):
#
#   scripts/prod/deploy.sh <commit-sha>
#
# 1. Checks out <commit-sha> (detached); refuses if tracked files have local changes.
# 2. Builds every image, the `migrate` tool image included (CLAUDE.md: it goes stale otherwise).
# 3. Starts Postgres and Redis. If migrations are pending, lists them, dumps the database to
#    ../dumps first (unless it is still empty), and asks before applying them —
#    CONFIRM_MIGRATIONS=yes answers for you. Nothing here ever migrates down.
# 4. Starts the stack and waits for the API's /health and the panel's /up.
#
# Rollback: the last line prints the command that redeploys the previous revision; restore the
# dump only if a migration ran (runbook §9).
#
# Everything is inside main(), which bash reads in full before running it: the checkout in step 1
# rewrites this very file.
set -euo pipefail

main() {
  local rev="${1:?usage: scripts/prod/deploy.sh <commit-sha>}"
  local root
  root="$(cd "$(dirname "$0")/../.." && pwd)"
  cd "$root"
  local dc=scripts/prod/dc
  local dumps="${INJAZ_DUMPS_DIR:-$(dirname "$root")/dumps}"

  [ -f .env ] || { echo "deploy: no .env — run scripts/prod/init-env.sh first" >&2; exit 1; }
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "deploy: tracked files have local changes; refusing" >&2
    exit 1
  fi

  local prev now
  prev="$(git rev-parse HEAD)"
  git fetch --quiet origin
  git checkout --quiet --detach "$rev"
  now="$(git rev-parse HEAD)"
  echo "== deploying ${now:0:12} (was ${prev:0:12})"

  echo "== build"
  "$dc" --profile tools build

  echo "== postgres, redis"
  "$dc" up -d postgres redis
  wait_healthy postgres 180

  echo "== migrations"
  local current
  current="$("$dc" --profile tools run --rm -T migrate alembic current 2>/dev/null | tail -n 1)"
  if [[ "$current" == *"(head)"* ]]; then
    echo "  none pending (${current})"
  else
    "$dc" --profile tools run --rm -T migrate alembic history --indicate-current 2>/dev/null
    if [ -n "$current" ]; then
      dump_database "$dumps" "${prev:0:12}"
    else
      echo "  empty database: nothing to dump"
    fi
    if [ "${CONFIRM_MIGRATIONS:-}" != "yes" ]; then
      local answer
      read -r -p "Apply the pending migrations above? Type 'yes': " answer
      if [ "$answer" != "yes" ]; then
        echo "deploy: stopped before migrating. ${now:0:12} is checked out; the services still run" \
          "what they ran. Re-run, or: scripts/prod/deploy.sh ${prev}" >&2
        exit 1
      fi
    fi
    "$dc" --profile tools run --rm migrate alembic upgrade head
  fi

  echo "== services"
  "$dc" up -d --remove-orphans
  wait_http "http://127.0.0.1:$(env_value API_HOST_PORT)/health" 180
  wait_http "http://127.0.0.1:$(env_value CONTROL_HOST_PORT)/up" 120
  "$dc" ps
  echo "== deployed ${now:0:12}. Rollback: scripts/prod/deploy.sh ${prev}"
}

env_value() { grep "^$1=" .env | head -n 1 | cut -d= -f2-; }

wait_healthy() {
  local service="$1" timeout="$2" waited=0 id status
  id="$(scripts/prod/dc ps -q "$service")"
  while :; do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo unknown)"
    [ "$status" = "healthy" ] && { echo "  ${service}: healthy"; return 0; }
    if [ "$waited" -ge "$timeout" ]; then
      echo "deploy: ${service} not healthy after ${timeout}s (${status})" >&2
      exit 1
    fi
    sleep 3
    waited=$((waited + 3))
  done
}

wait_http() {
  local url="$1" timeout="$2" waited=0
  until curl -fsS -o /dev/null --max-time 5 "$url"; do
    if [ "$waited" -ge "$timeout" ]; then
      echo "deploy: ${url} not ready after ${timeout}s" >&2
      exit 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
  echo "  ${url}: ok"
}

dump_database() {
  local dir="$1" label="$2" file
  mkdir -p "$dir"
  file="${dir}/$(env_value POSTGRES_DB)-$(date -u +%Y%m%dT%H%M%SZ)-before-${label}.dump"
  ( umask 077
    scripts/prod/dc exec -T postgres \
      pg_dump -U "$(env_value POSTGRES_USER)" -d "$(env_value POSTGRES_DB)" -Fc > "$file" )
  echo "  dump: ${file} ($(du -h "$file" | cut -f1))"
}

main "$@"
