#!/usr/bin/env bash
# Points model profiles at an inference endpoint. The endpoint is data — model_profiles.base_url,
# read on every call — so serving from the local `ollama` container today, or from a GPU host
# later, is this one update: no rebuild, no restart. Re-qualify a profile on its new host before
# activating it (spec 010: a model is qualified on the host that serves it). Runbook §10.
#
#   scripts/prod/set-model-endpoint.sh --show
#   scripts/prod/set-model-endpoint.sh <base_url> --provider <ollama|vllm>   # every profile of it
#   scripts/prod/set-model-endpoint.sh <base_url> <profile-name>...          # named profiles only
#
# e.g. after `seed_profiles` on a fresh database:
#   scripts/prod/set-model-endpoint.sh http://ollama:11434/v1 --provider ollama
set -euo pipefail
cd "$(dirname "$0")/../.."

env_value() { grep "^$1=" .env | head -1 | cut -d= -f2-; }
psql_() {
  scripts/prod/dc exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "$(env_value POSTGRES_USER)" -d "$(env_value POSTGRES_DB)" "$@"
}
show() {
  psql_ -c "SELECT name, role, provider, model, base_url, api_key_env, is_active
            FROM model_profiles ORDER BY role, name"
}

if [ $# -eq 0 ] || [ "$1" = "--show" ]; then
  show
  exit 0
fi

url="$1"
shift
if [ $# -eq 0 ]; then
  echo "usage: $0 <base_url> --provider <provider> | <profile-name>..." >&2
  exit 2
fi

if [ "$1" = "--provider" ]; then
  [ $# -eq 2 ] || { echo "usage: $0 <base_url> --provider <provider>" >&2; exit 2; }
  psql_ -v url="$url" -v provider="$2" <<'SQL'
UPDATE model_profiles SET base_url = :'url', updated_at = now() WHERE provider = :'provider';
SQL
else
  names="$(IFS=,; echo "$*")"
  unknown="$(psql_ -tA -v names="$names" <<'SQL'
SELECT n FROM unnest(string_to_array(:'names', ',')) AS n
WHERE n NOT IN (SELECT name FROM model_profiles);
SQL
)"
  if [ -n "$unknown" ]; then
    echo "set-model-endpoint: no such profile(s), nothing changed: $(echo "$unknown" | tr '\n' ' ')" >&2
    exit 1
  fi
  psql_ -v url="$url" -v names="$names" <<'SQL'
UPDATE model_profiles SET base_url = :'url', updated_at = now()
WHERE name = ANY (string_to_array(:'names', ','));
SQL
fi
show
