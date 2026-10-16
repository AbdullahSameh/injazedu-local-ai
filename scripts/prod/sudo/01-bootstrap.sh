#!/usr/bin/env bash
# One-time host preparation. Run by the operator, who types the sudo password in their own
# terminal (docs/runbooks/production-deployment.md §3):
#
#   ssh -t sambo@84.46.248.13 'sudo bash ~/injazedu-ai-sudo/01-bootstrap.sh'
#
# It changes exactly this, and nothing else:
#   1. creates /var/www/injazedu-ai/{repo,dumps} (0755) and /var/www/injazedu-ai/fixtures (0700),
#      owned by the invoking user (sambo); existing directories are left as they are;
#   2. creates a 4 GiB /swapfile (0600), turns it on, and adds one line to /etc/fstab
#      — a safety margin against out-of-memory kills of the host's other services while a model
#      is loaded; skipped if /swapfile is already active;
#   3. writes /etc/sysctl.d/99-injazedu-ai.conf with vm.swappiness=10 (prefer RAM; swap only under
#      pressure) and applies it.
# Every step is idempotent. Undo: swapoff /swapfile; rm /swapfile; delete its fstab line and the
# sysctl file; remove /var/www/injazedu-ai.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
owner="${SUDO_USER:?run through sudo, so the directories go to the invoking user}"
base=/var/www/injazedu-ai

echo "== 1. directories under ${base} (owner ${owner})"
install -d -o "$owner" -g "$owner" -m 0755 "$base" "$base/repo" "$base/dumps"
install -d -o "$owner" -g "$owner" -m 0700 "$base/fixtures"
ls -ld "$base" "$base"/*

echo "== 2. swap"
if swapon --show=NAME --noheadings | grep -qx /swapfile; then
  echo "  /swapfile already active; left unchanged"
else
  if [ -e /swapfile ]; then
    echo "  /swapfile exists but is not active; refusing to touch it" >&2
    exit 1
  fi
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo "  /swapfile created and active"
fi
if ! grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "  /etc/fstab: added /swapfile"
fi

echo "== 3. vm.swappiness"
printf '# InjazEdu AI (scripts/prod/sudo/01-bootstrap.sh): use swap only under memory pressure.\nvm.swappiness=10\n' \
  > /etc/sysctl.d/99-injazedu-ai.conf
sysctl -p /etc/sysctl.d/99-injazedu-ai.conf

echo "== done"
free -h
