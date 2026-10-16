#!/usr/bin/env bash
# READ-ONLY. Changes nothing. Run by the operator, who types the sudo password in their own
# terminal (docs/runbooks/production-deployment.md §3):
#
#   ssh -t sambo@84.46.248.13 'sudo bash ~/injazedu-ai-sudo/00-readonly-report.sh'
#
# Reports what the deployment cannot see without root: the firewall, the nginx configuration test,
# the journal's size and which units write to it (counts only — never a message), recent
# unattended-upgrades runs (package names only), and the existing certificates (names and expiry).
set -u

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

section() { printf '\n== %s\n' "$1"; }

section "ufw"
ufw status verbose

section "nginx -t"
nginx -t 2>&1

section "journal disk usage"
journalctl --disk-usage
grep -hvE '^\s*(#|$)' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf 2>/dev/null

section "journal entries per unit, last 7 days (top 15; counts only)"
journalctl --since "-7 days" --no-pager -o json --output-fields=_SYSTEMD_UNIT,SYSLOG_IDENTIFIER \
  | python3 -I -c '
import collections, json, sys
counts = collections.Counter()
for line in sys.stdin:
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    counts[entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "?"] += 1
for name, n in counts.most_common(15):
    print(f"{n:>10}  {name}")
'

section "failed SSH logins recorded in btmp (count only)"
lastb -w 2>/dev/null | grep -cv '^$\|^btmp begins' || true

section "unattended-upgrades, last runs (package names only)"
grep -hE 'Packages that will be upgraded|All upgrades installed|No packages found|ERROR' \
  /var/log/unattended-upgrades/unattended-upgrades.log 2>/dev/null | tail -n 10

section "certificates (names and expiry)"
certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry Date'

section "docker daemon configuration"
cat /etc/docker/daemon.json 2>/dev/null || echo "(no /etc/docker/daemon.json — defaults)"
