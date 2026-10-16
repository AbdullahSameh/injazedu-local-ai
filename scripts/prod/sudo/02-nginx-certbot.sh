#!/usr/bin/env bash
# Publishes the two sites through the host's existing nginx and gets their certificates. Run by the
# operator from the deployed checkout, once both DNS records point at this server
# (docs/runbooks/production-deployment.md §3, §4):
#
#   ssh -t sambo@84.46.248.13 'cd /var/www/injazedu-ai/repo && sudo bash scripts/prod/sudo/02-nginx-certbot.sh'
#
# It changes exactly this, and nothing else:
#   1. adds three files, copied from infra/nginx/ — never overwriting an existing one:
#        /etc/nginx/conf.d/injazedu-ai-limits.conf          (rate-limit zones only)
#        /etc/nginx/sites-available/ai-control.injazedu.co
#        /etc/nginx/sites-available/ai.injazedu.co
#   2. links the two sites into /etc/nginx/sites-enabled/;
#   3. runs `nginx -t` — on failure it removes what steps 1-2 added and stops, before any reload;
#      then `systemctl reload nginx` (graceful: the other sites keep serving);
#   4. `certbot --nginx --redirect --hsts` once per domain: adds that domain's certificate and
#      renewal config, and edits only that domain's site file (TLS listener, HTTP->HTTPS redirect,
#      HSTS without includeSubDomains). The existing timer renews them with the others.
# The other sites' files are never read or written.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
cd "$(dirname "$0")/../../.."
domains=(ai-control.injazedu.co ai.injazedu.co)

echo "== preflight: DNS points here"
local_ips="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1)"
for d in "${domains[@]}"; do
  resolved="$(getent ahostsv4 "$d" | awk 'NR==1{print $1}')"
  if [ -z "$resolved" ] || ! grep -qx "$resolved" <<<"$local_ips"; then
    echo "  ${d} resolves to '${resolved:-nothing}', not this server; create the A record first" >&2
    exit 1
  fi
  echo "  ${d} -> ${resolved}"
done

echo "== preflight: the stack answers on localhost"
curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:18080/up && echo "  panel: ok" \
  || echo "  panel: not answering on 127.0.0.1:18080 (certificates still work; check the stack)"
curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:18000/health/live && echo "  api: ok" \
  || echo "  api: not answering on 127.0.0.1:18000 (certificates still work; check the stack)"

added=()
place() {
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then
    echo "  ${dst} exists; left unchanged"
  else
    install -o root -g root -m 0644 "$src" "$dst"
    added+=("$dst")
    echo "  added ${dst}"
  fi
}
link() {
  local target="$1" name="$2"
  if [ -e "$name" ] || [ -L "$name" ]; then
    echo "  ${name} exists; left unchanged"
  else
    ln -s "$target" "$name"
    added+=("$name")
    echo "  linked ${name}"
  fi
}

echo "== 1-2. nginx files"
place infra/nginx/injazedu-ai-limits.conf /etc/nginx/conf.d/injazedu-ai-limits.conf
for d in "${domains[@]}"; do
  place "infra/nginx/${d}.conf" "/etc/nginx/sites-available/${d}"
  link "/etc/nginx/sites-available/${d}" "/etc/nginx/sites-enabled/${d}"
done

echo "== 3. nginx -t, reload"
if ! nginx -t; then
  echo "  nginx -t failed: removing what this run added; nothing was reloaded" >&2
  for f in "${added[@]}"; do rm -f "$f"; done
  exit 1
fi
systemctl reload nginx

echo "== 4. certificates"
for d in "${domains[@]}"; do
  if [ -d "/etc/letsencrypt/live/${d}" ]; then
    echo "  ${d}: certificate exists; left unchanged"
  else
    certbot --nginx --cert-name "$d" -d "$d" --redirect --hsts
  fi
done

echo "== check"
nginx -t
for d in "${domains[@]}"; do
  printf '  https://%s -> %s\n' "$d" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${d}/")"
done
