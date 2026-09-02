#!/usr/bin/env bash
# Per-service and total container memory against the 5 GB budget (SC-004).
set -euo pipefail

cd "$(dirname "$0")/.."

cids=$(docker compose -f infra/docker-compose.yml --env-file .env ps -q)
if [ -z "$cids" ]; then
  echo "No services running — run 'make up' first."
  exit 1
fi

# shellcheck disable=SC2086
docker stats --no-stream --format '{{json .}}' $cids | python3 -c '
import json
import sys

def to_bytes(s: str) -> float:
    s = s.strip()
    units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    for unit in sorted(units, key=len, reverse=True):
        if s.endswith(unit):
            return float(s[: -len(unit)]) * units[unit]
    return 0.0

budget = 5 * 1024**3
total = 0.0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    used_raw = row["MemUsage"].split(" / ")[0]
    used = to_bytes(used_raw)
    total += used
    name = row["Name"]
    print(f"{name:<35} {used_raw:>12}")

print()
print(f"Total: {total / 1024**3:.2f} GiB (budget: {budget / 1024**3:.1f} GiB)")
if total > budget:
    print("OVER BUDGET")
    sys.exit(1)
print("within budget")
'
