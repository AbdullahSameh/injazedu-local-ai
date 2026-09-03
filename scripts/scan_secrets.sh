#!/usr/bin/env bash
# Fails when a credential-shaped value appears in any version-controlled file (FR-033, SC-011).
#
# Only git-tracked files are scanned — .env itself is gitignored (contracts/environment.md), so
# this catches the two real risks: a real .env accidentally force-added, or a working secret
# pasted directly into a committed file. `.env.example` / `.env.testing.example` are expected to
# contain nothing but CHANGE_ME... placeholders, which this scan treats as safe.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PYEOF'
import re
import subprocess
import sys

tracked = subprocess.run(
    ["git", "ls-files", "-z"], capture_output=True, check=True
).stdout.split(b"\0")
tracked = [f.decode() for f in tracked if f]

SECRET_KEY_NAME = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*(PASSWORD|SECRET|_TOKEN|APIKEY|API_KEY|_KEY)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)
SAFE_VALUE = re.compile(
    r'^(""|\'\'|)$|^CHANGE_ME|^\$\{|^null$|^none$|^\s*$', re.IGNORECASE
)
PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
GITHUB_TOKEN = re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")
SLACK_TOKEN = re.compile(r"xox[baprs]-[0-9A-Za-z-]+")

# The KEY=value heuristic below only makes sense for actual config — narrative docs routinely show
# illustrative `SOME_KEY=example` snippets that are not secrets. The four fixed-signature checks
# above (private key blocks, AWS/GitHub/Slack tokens) apply to every tracked file regardless.
CONFIG_SHAPED = re.compile(r"\.(env.*|ya?ml|sh|php|py|ini)$|(^|/)Makefile$", re.IGNORECASE)

findings: list[str] = []

for path in tracked:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        continue
    if b"\0" in raw:
        continue  # binary file
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue

    for lineno, line in enumerate(text.splitlines(), start=1):
        if PRIVATE_KEY_HEADER.search(line):
            findings.append(f"{path}:{lineno}: private key block")
            continue
        if AWS_ACCESS_KEY.search(line):
            findings.append(f"{path}:{lineno}: AWS access key ID")
            continue
        if GITHUB_TOKEN.search(line):
            findings.append(f"{path}:{lineno}: GitHub token")
            continue
        if SLACK_TOKEN.search(line):
            findings.append(f"{path}:{lineno}: Slack token")
            continue

        if not CONFIG_SHAPED.search(path):
            continue

        match = SECRET_KEY_NAME.match(line)
        if match and not SAFE_VALUE.match(match.group(2)):
            findings.append(f"{path}:{lineno}: credential-shaped assignment: {line.strip()}")

if findings:
    print("Secret scan FAILED — credential-shaped value(s) found in version-controlled files:")
    for finding in findings:
        print(f"  {finding}")
    sys.exit(1)

print(f"Secret scan OK — {len(tracked)} tracked files, no credential-shaped values found.")
PYEOF
