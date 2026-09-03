#!/usr/bin/env bash
# Recreates the test database from migrations. Refuses any database whose name lacks the `_test`
# marker (FR-029, FR-030) — this is the one Makefile target that touches a database's structure by
# design, so it gets its own explicit guard rather than relying on the pytest-only one.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

TEST_DATABASE_URL="${TEST_DATABASE_URL:-$(grep '^TEST_DATABASE_URL=' .env.testing 2>/dev/null | head -1 | cut -d= -f2-)}"

if [ -z "$TEST_DATABASE_URL" ]; then
  echo "Refusing: TEST_DATABASE_URL is not set (checked the environment and .env.testing)." >&2
  exit 1
fi

DB_NAME="${TEST_DATABASE_URL##*/}"
DB_NAME="${DB_NAME%%\?*}"

case "$DB_NAME" in
  *_test*) ;;
  *)
    echo "Refusing: database name \"$DB_NAME\" does not contain \"_test\" (Principle II)." >&2
    exit 1
    ;;
esac

MIGRATOR_PASSWORD="$(grep '^AI_MIGRATOR_PASSWORD=' .env | head -1 | cut -d= -f2-)"
if [ -z "$MIGRATOR_PASSWORD" ]; then
  echo "Refusing: AI_MIGRATOR_PASSWORD is not set in .env." >&2
  exit 1
fi

COMPOSE="docker compose -f infra/docker-compose.yml --env-file .env"

echo "Resetting \"$DB_NAME\" (dropping known tables, then migrating to head)..."

$COMPOSE exec -T -e PGPASSWORD="$MIGRATOR_PASSWORD" postgres \
  psql -v ON_ERROR_STOP=1 -U ai_migrator -d "$DB_NAME" \
  -c "DROP TABLE IF EXISTS users, alembic_version CASCADE;"

$COMPOSE --profile tools run --rm \
  -e MIGRATOR_DATABASE_URL="postgresql+psycopg://ai_migrator:${MIGRATOR_PASSWORD}@postgres:5432/${DB_NAME}" \
  migrate alembic upgrade head

echo "\"$DB_NAME\" reset to head."
