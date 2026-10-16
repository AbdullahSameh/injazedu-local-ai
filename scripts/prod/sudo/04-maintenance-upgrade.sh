#!/usr/bin/env bash
# Maintenance window, step 1 of 2: package upgrades (docs/runbooks/production-deployment.md §13).
# Run by the operator, who types the sudo password in their own terminal, inside tmux so that a
# dropped SSH connection cannot interrupt dpkg half-way:
#
#   ssh -t sambo@84.46.248.13
#   tmux new -s maint
#   sudo bash ~/injazedu-ai-sudo/04-maintenance-upgrade.sh
#   sudo bash ~/injazedu-ai-sudo/04-maintenance-upgrade.sh --skip-origin LP-PPA-ondrej-php
#
# --skip-origin leaves one repository's packages out of this run, e.g. while that repository is down
# (a failed download makes apt install nothing). Those packages are put on hold for the run and
# released when it ends, success or not; packages already on hold are left as they are.
#
# Changes exactly this, and only after showing the list and asking:
#   - `apt-get update`, then `apt-get --with-new-pkgs upgrade`: upgrades installed packages and may
#     add new dependencies; removes nothing (no dist-upgrade, no autoremove). Phased updates stay
#     deferred, as Ubuntu intends.
#   - Every locally modified configuration file is kept (--force-confold, UCF_FORCE_CONFFOLD).
#   - needrestart only lists what would need a restart (NEEDRESTART_MODE=l) because a reboot follows.
#     The packages' own scripts still restart their daemons: docker (every container stops and
#     starts; restart policies bring them back, about a minute) and php8.2-fpm (a few seconds).
#   - The whole output goes to /var/log/injazedu-maintenance-<UTC time>.log.
# It never reboots and never edits a configuration file. Step 2 is `sudo reboot`, run separately.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
skip_origin=""
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-origin) skip_origin="${2:?--skip-origin needs an origin, e.g. LP-PPA-ondrej-php}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# sudo drops $TMUX, so look for tmux or screen among this process's ancestors instead.
in_multiplexer() {
  local pid=$$ name
  while [ "${pid:-1}" -gt 1 ]; do
    name="$(ps -o comm= -p "$pid" 2>/dev/null || true)"
    case "$name" in tmux*|screen*|SCREEN*) return 0 ;; esac
    pid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
  done
  return 1
}
in_multiplexer || { echo "run inside tmux (tmux new -s maint) so a dropped connection cannot interrupt dpkg" >&2; exit 1; }

log="/var/log/injazedu-maintenance-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log") 2>&1

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l UCF_FORCE_CONFFOLD=1
apt_opts=(-o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

echo "== before"
uname -r
audit="$(dpkg --audit || true)"
[ -z "$audit" ] || { printf '%s\n' "$audit"; echo "dpkg reports unfinished packages: stopping, nothing changed" >&2; exit 1; }
echo "dpkg: consistent"
df -h / /boot | tail -n +2
docker version -f 'docker {{.Server.Version}}' || echo "docker: not answering"

echo "== apt-get update"
apt-get "${apt_opts[@]}" update -q

held=()
if [ -n "$skip_origin" ]; then
  already="$(apt-mark showhold)"
  mapfile -t held < <(python3 -I -c '
import sys, apt
for p in apt.Cache():
    if p.is_upgradable and any(o.origin == sys.argv[1] for o in p.candidate.origins):
        print(p.name)
' "$skip_origin" | grep -vxF -e "${already:-<none>}" || true)
  if [ "${#held[@]}" -gt 0 ]; then
    trap 'apt-mark unhold "${held[@]}" >/dev/null && echo "released the temporary hold on ${#held[@]} packages"' EXIT
    trap 'exit 130' INT TERM HUP
    apt-mark hold "${held[@]}" >/dev/null
    echo "== left out of this run (${#held[@]} from ${skip_origin}, held until the script ends)"
    printf '%s ' "${held[@]}" | fold -s -w 100 | sed 's/^/  /'; echo
  else
    echo "== no upgradable package comes from ${skip_origin}"
  fi
fi

echo "== what would change"
plan="$(apt-get "${apt_opts[@]}" -s --with-new-pkgs upgrade)"
printf '%s\n' "$plan" | awk '/^Inst /{print $2}' | sort | paste -sd' ' - | fold -s -w 100 | sed 's/^/  /'
printf '%s\n' "$plan" | grep -E '^[0-9]+ upgraded' || true
printf '%s\n' "$plan" | awk '/^Inst /{print $2}' | grep -E '^(docker-ce|containerd\.io|php8\.2-fpm|nginx|mysql-server|openssh-server|linux-image|libc6)' \
  | sed 's/^/  restarts or needs the reboot: /' || true

read -rp "Upgrade these packages now? Docker restarts every container, php8.2-fpm restarts. [y/N] " answer
[ "$answer" = y ] || { echo "nothing changed"; exit 0; }

echo "== upgrade"
if ! apt-get "${apt_opts[@]}" -y --with-new-pkgs upgrade; then
  echo "UPGRADE FAILED (errors above). A failed download installs nothing; a failed install can leave"
  echo "packages half-configured: check 'sudo dpkg --audit'. Do not reboot; tell Claude."
  exit 1
fi

echo "== after"
dpkg --audit && echo "dpkg: consistent"
echo "still upgradable (phased or kept back): $(apt list --upgradable 2>/dev/null | tail -n +2 | wc -l)"
sleep 20
docker version -f 'docker {{.Server.Version}}' || echo "docker: not answering yet"
for unit in nginx mysql php8.2-fpm docker ssh.socket; do printf '%s=%s ' "$unit" "$(systemctl is-active "$unit")"; done; echo
docker ps -a --format '{{.Names}}\t{{.Status}}' || true
[ -f /var/run/reboot-required ] && echo "REBOOT REQUIRED: tell Claude, who checks the sites first; then sudo reboot"
echo "log: $log"
