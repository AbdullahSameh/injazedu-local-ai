#!/usr/bin/env bash
# Writes the production .env (mode 600) from .env.production.example, replacing each CHANGE_ME_...
# placeholder with a fresh random value — the same value wherever a placeholder repeats, so the
# connection strings match the role passwords. Prints the placeholder names it filled, never a
# value. Refuses to overwrite an existing .env: Postgres sets role passwords only when its volume
# is first initialised, so rotating one later is ALTER ROLE plus an edit, never a re-run.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -e .env ]; then
  echo "init-env: .env already exists; left unchanged." >&2
  exit 1
fi

umask 077
python3 -I - .env.production.example .env <<'PY'
import base64
import re
import secrets
import sys

source, target = sys.argv[1], sys.argv[2]
text = open(source, encoding="utf-8").read()

# Hex passwords: safe inside a postgresql:// URL without escaping. APP_KEY is Laravel's format.
fills = {
    "CHANGE_ME_APP_KEY": "base64:" + base64.b64encode(secrets.token_bytes(32)).decode(),
    "CHANGE_ME_POSTGRES": secrets.token_hex(24),
    "CHANGE_ME_MIGRATOR": secrets.token_hex(24),
    "CHANGE_ME_APP": secrets.token_hex(24),
    "CHANGE_ME_CONTROL": secrets.token_hex(24),
}
for placeholder, value in fills.items():
    text = re.sub(rf"\b{placeholder}\b", value, text)

leftover = sorted(
    {m for line in text.splitlines() if not line.lstrip().startswith("#")
     for m in re.findall(r"CHANGE_ME\w*", line)}
)
if leftover:
    sys.exit(f"init-env: placeholder(s) with no generator: {', '.join(leftover)}")

with open(target, "x", encoding="utf-8") as handle:
    handle.write(text)
print("init-env: wrote .env (mode 600); filled " + ", ".join(sorted(fills)))
PY
