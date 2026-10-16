#!/usr/bin/env bash
# OPTIONAL, maintenance window only (docs/runbooks/production-deployment.md §13). The deployment
# does not need it: journald already caps itself at 4 GiB on this host, and the stack logs to
# Docker's rotated json-file, not the journal.
#
#   sudo bash scripts/prod/sudo/03-maintenance-journald.sh                  # dry run: changes nothing
#   sudo bash scripts/prod/sudo/03-maintenance-journald.sh --archive DIR    # copy the journal first
#   sudo bash scripts/prod/sudo/03-maintenance-journald.sh --archive DIR --apply
#
# --apply changes exactly this: writes /etc/systemd/journald.conf.d/50-injazedu-size.conf
# (SystemMaxUse=1G) and restarts systemd-journald, which then DELETES the oldest journal files
# until the journal fits in 1 GiB. That deletion cannot be undone — hence --archive, which first
# packs /var/log/journal into DIR/journal-<date>.tar.gz. Undo the cap: delete the file, restart.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
archive="" apply=no
while [ $# -gt 0 ]; do
  case "$1" in
    --archive) archive="${2:?--archive needs a directory}"; shift 2 ;;
    --apply) apply=yes; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

echo "== now"
journalctl --disk-usage
df -h /var/log | tail -n 1

if [ -n "$archive" ]; then
  echo "== archive"
  install -d -m 0700 "$archive"
  file="${archive}/journal-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
  tar -C /var/log -czf "$file" journal
  chmod 600 "$file"
  echo "  ${file} ($(du -h "$file" | cut -f1))"
fi

if [ "$apply" != yes ]; then
  echo "== dry run: would write /etc/systemd/journald.conf.d/50-injazedu-size.conf (SystemMaxUse=1G)"
  echo "   and restart systemd-journald, deleting the oldest entries beyond 1 GiB. Re-run with --apply."
  exit 0
fi

echo "== apply"
install -d -m 0755 /etc/systemd/journald.conf.d
printf '# InjazEdu AI maintenance (scripts/prod/sudo/03-maintenance-journald.sh)\n[Journal]\nSystemMaxUse=1G\n' \
  > /etc/systemd/journald.conf.d/50-injazedu-size.conf
systemctl restart systemd-journald
journalctl --disk-usage
