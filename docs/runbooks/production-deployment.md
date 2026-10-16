# Production deployment — Contabo VPS

The whole stack runs on one Contabo VPS (`sambo@84.46.248.13`) in Docker, behind the host's existing
nginx and certbot. Only LLM inference may later move to a GPU host (§10).

- **Plan of record:** `docs/plan/side/contabo-production-deployment-plan.md`.
- **Development is unchanged:** `.env.example`, `make up` on the Mac, Ollama native. This runbook is
  production only.

> **Never on production:** `make check`, `make test-db-reset`, `make migrate-down`,
> `make down-hard`, `php artisan db:seed`, `docker compose down -v`, `docker system prune --volumes`
> (§12). The Makefile and `scripts/check.sh` refuse the first four where `.env` has
> `DEPLOYMENT_ENV=production`.

## 1. Architecture

```
Internet ─443─▶ host nginx ─┬─ ai-control.injazedu.co ─▶ 127.0.0.1:18080 ─▶ ai-control (FrankenPHP)
                            └─ ai.injazedu.co: GET /health/live only ─▶ 127.0.0.1:18000 ─▶ ai-api
Compose project "injazedu-local-ai", network 172.31.240.0/24 — nothing else published:
  postgres (pgvector 0.8.6, pg16)   redis (AOF)   ai-worker   ai-classifier   ai-telegram
  ollama (0.40.4, CPU) ◀── reached through model_profiles.base_url
```

| Service | Role | Restart | Memory |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.6-pg16-bookworm`, volume `postgres-data` | unless-stopped | 1g |
| `redis` | Dramatiq broker, AOF on, `noeviction`, volume `redis-data` | unless-stopped | 256m |
| `ollama` | CPU inference, CPUs 1–5, one model loaded, one request at a time, volume `ollama-models` | unless-stopped | `OLLAMA_MEM_LIMIT` (6500m) |
| `ai-api` | FastAPI: `/health`, diagnostics | unless-stopped | 512m |
| `ai-worker` | Dramatiq `default` queue | unless-stopped | 768m |
| `ai-classifier` | `moderation_attention` + `moderation_classify`, 1 thread | unless-stopped | 384m |
| `ai-telegram` | `getUpdates` poller; **token blank until go-live**, so it exits 0 | **on-failure** | 256m |
| `ai-control` | Laravel/Filament (`Dockerfile.prod`), volume `control-storage` | unless-stopped | 512m |

Laravel never calls FastAPI; both share Postgres. Telegram is polled, so nothing outside calls the
API. The production override is `infra/docker-compose.prod.yml`; its header lists everything it
changes against the base file.

## 2. Layout and environment

```
/var/www/injazedu-ai/
├── repo/          git checkout (detached at the deployed commit); .env lives here (mode 600)
├── fixtures/      real labelled messages for smoke/qualify (0700, files 0600) — never in Git
└── dumps/         pg_dump files written before each migration (§9)
```

**`.env`:**
- It is generated once by `scripts/prod/init-env.sh` from `.env.production.example`. The script fills
  every password and the `APP_KEY` with random values and prints none.
- To change a value, edit it with `ssh -t sambo@84.46.248.13 'nano /var/www/injazedu-ai/repo/.env'`.
- Then recreate the services that read it: `scripts/prod/dc up -d <service>…`. A plain `restart`
  does not re-read `.env`.
- **Role passwords are fixed at the volume's first start.** Rotating one means `ALTER ROLE … PASSWORD`
  in `psql` plus the `.env` edit (both the `*_PASSWORD` and the `*_DATABASE_URL`).

**Values production sets differently from development:**

| Setting | Value | Note |
|---|---|---|
| `DEPLOYMENT_ENV` | `production` | |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Feeds the `/health` probe only |
| `API_HOST_PORT` / `CONTROL_HOST_PORT` | 18000 / 18080 | |
| `WORKER_PROCESSES` | 1 | |
| `MODERATION_PROMPT_VERSION` | `classify_v2` | |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | blank | See §5 |
| `TELEGRAM_BOT_TOKEN` | blank | See §11 |
| `MODERATION_AI_ATTENTION_FROM` / `MODERATION_ATTENTION_PROMPT_VERSION` | blank | No attention instruction is qualified |

**Commands:**
- `scripts/prod/dc <compose args>` is `docker compose` with both files and `.env`.
- `make <target>` works too: on production it adds the override automatically.

## 3. Privileged steps (the operator runs them)

Nothing in this deployment uses passwordless sudo. Each script states in its header exactly what it
changes. You read it, then run it yourself and type the sudo password in your own terminal.

| Script | When | Changes |
|---|---|---|
| `scripts/prod/sudo/00-readonly-report.sh` | Before deploying, and any time | **Nothing.** Prints ufw, `nginx -t`, journal size and top writers (counts only), unattended-upgrades runs, and certificate names and expiry |
| `scripts/prod/sudo/01-bootstrap.sh` | Once | `/var/www/injazedu-ai/{repo,dumps,fixtures}`, a 4 GiB `/swapfile` plus its fstab line, `vm.swappiness=10` |
| `scripts/prod/sudo/02-nginx-certbot.sh` | Once DNS resolves (§4) | Three new nginx files plus two symlinks, `nginx -t` (rolls back on failure), reload, `certbot --nginx --redirect --hsts` per domain |
| `scripts/prod/sudo/03-maintenance-journald.sh` | Maintenance window only (§13) | Dry run by default; `--apply` caps the journal at 1 GiB |

Scripts 00 and 01 run before the repository is on the server, so copy them from the Mac first:

```bash
ssh sambo@84.46.248.13 'mkdir -p ~/injazedu-ai-sudo'
scp scripts/prod/sudo/00-readonly-report.sh scripts/prod/sudo/01-bootstrap.sh sambo@84.46.248.13:~/injazedu-ai-sudo/
ssh -t sambo@84.46.248.13 'sudo bash ~/injazedu-ai-sudo/00-readonly-report.sh'
ssh -t sambo@84.46.248.13 'sudo bash ~/injazedu-ai-sudo/01-bootstrap.sh'
```

Later scripts run from the checkout:
`ssh -t sambo@84.46.248.13 'cd /var/www/injazedu-ai/repo && sudo bash scripts/prod/sudo/02-nginx-certbot.sh'`.

## 4. DNS and HTTPS

In Cloudflare, zone `injazedu.co`:

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| A | `ai` | `84.46.248.13` | **DNS only** (grey) | Auto |
| A | `ai-control` | `84.46.248.13` | **DNS only** (grey) | Auto |

- Add no AAAA record for now.
- Check with `dig +short @1.1.1.1 ai.injazedu.co` before running script 02.
- Let's Encrypt (HTTP-01) then reaches nginx directly, as for the host's other sites, and the existing
  `certbot.timer` renews the certificates.
- **If you ever switch the proxy on (orange cloud):** set SSL/TLS to *Full (strict)* for these
  hostnames first, or you get a redirect loop. The real client address would then arrive in
  `CF-Connecting-IP`, and nginx would need a `real_ip` configuration for it.

**What the two sites do:**
- **ai-control:** proxies everything to the panel and redirects `/` to `/admin`.
  - Every `X-Forwarded-*` header is set by nginx, overwriting the client's. The panel trusts these
    headers only from the network gateway (`TRUSTED_PROXIES=172.31.240.1`,
    `apps/ai-control/config/trustedproxy.php`).
  - Rate limits: 10 r/s (burst 40) per address; `/admin/login` 10 per minute (burst 10).
  - Filament also throttles failed logins per client address.
  - Security headers; HSTS added by certbot.
- **ai:** only `GET /health/live`. Everything else returns 404 (`/health`, `/docs`, `/openapi.json`,
  `/v1/*`). The full `/health` is for the host only: `curl -s http://127.0.0.1:18000/health`.

## 5. First deployment

On the server, as `sambo`, after §3 scripts 00 and 01:

```bash
git clone git@github.com:AbdullahSameh/injazedu-local-ai.git /var/www/injazedu-ai/repo
cd /var/www/injazedu-ai/repo
scripts/prod/init-env.sh                       # .env, mode 600, random secrets, nothing printed
CONFIRM_MIGRATIONS=yes scripts/prod/deploy.sh <pushed-commit-sha>
```

`deploy.sh`:
1. builds the images;
2. starts Postgres, which initialises roles and `vector`, without a test database;
3. applies Alembic 0001–0008 to the empty database;
4. starts every service and waits for `/health` and `/up`.

**Then:**

```bash
make seed-profiles                                                   # idempotent
scripts/prod/set-model-endpoint.sh http://ollama:11434/v1 --provider ollama
scripts/prod/dc exec ollama ollama pull gemma4:e2b-it-qat
scripts/prod/dc exec ollama ollama pull embeddinggemma:300m-qat-q4_0
```

**The panel account.** Run this in your own terminal. You type the address and password, they go
straight into a one-off container, and they are never stored in `.env` or the running container:

```bash
ssh -t sambo@84.46.248.13 'cd /var/www/injazedu-ai/repo && read -rp "Email: " ADMIN_EMAIL && read -rsp "Password: " ADMIN_PASSWORD && echo && export ADMIN_EMAIL ADMIN_PASSWORD && scripts/prod/dc run --rm -e ADMIN_EMAIL -e ADMIN_PASSWORD ai-control php artisan app:seed-admin'
```

Running it again with the same address resets that account's password.

**The moderation profile** stays inactive until §8's smoke test and qualification pass. Then: panel →
Model Profiles → `ollama-gemma4-e2b-moderation` → Active. It does nothing until Telegram is live (§11).

## 6. Updating

1. On the Mac: `make check` passes.
2. You commit and push.
3. On the server:

```bash
cd /var/www/injazedu-ai/repo
scripts/prod/deploy.sh <commit-sha>
```

`deploy.sh` does the following:
- refuses if tracked files changed;
- checks out the commit and builds every image, including the `migrate` tool image;
- if migrations are pending, lists them, writes a dump to `../dumps/`, and asks before applying them
  (`CONFIRM_MIGRATIONS=yes` answers for you);
- recreates the changed services and health-gates them;
- prints the rollback command.

**Before answering `yes`, read the pending migrations.** If one drops or rewrites existing data, stop
and decide first.

## 7. Everyday operations

**Status:**
```bash
scripts/prod/dc ps
curl -s http://127.0.0.1:18000/health | python3 -m json.tool
```
The `/health` output has three required components: database, broker and worker heartbeat.

**Logs** are JSON lines; message text is never logged:
```bash
scripts/prod/dc logs -f --tail 200 ai-classifier
```

**Restart a service:**
```bash
scripts/prod/dc restart ai-worker
```
After a `.env` change, use `scripts/prod/dc up -d ai-worker ai-classifier` instead.

**Stop or start everything** (volumes are kept):
```bash
scripts/prod/dc stop
scripts/prod/dc up -d
```

**Queues:**
```bash
scripts/prod/dc exec redis redis-cli LLEN dramatiq:moderation_classify
```
- `dramatiq:<queue>` holds pending messages;
- `dramatiq:<queue>.DQ` holds delayed ones;
- `ZCARD dramatiq:<queue>.XQ` counts dead-lettered ones.

**Resources:**
```bash
docker stats --no-stream
free -h
df -h /
scripts/prod/dc exec ollama ollama ps
docker system df -v | grep injazedu
```

**Model latency, last 24 hours** (no message text):
```bash
scripts/prod/dc exec -T postgres psql -U postgres -d injaz_ai -c "
  SELECT p.name, count(*) AS calls, count(*) FILTER (WHERE NOT r.ok) AS failed,
         percentile_disc(0.5)  WITHIN GROUP (ORDER BY r.latency_ms) AS p50_ms,
         percentile_disc(0.95) WITHIN GROUP (ORDER BY r.latency_ms) AS p95_ms
  FROM model_runs r JOIN model_profiles p ON p.id = r.model_profile_id
  WHERE r.created_at > now() - interval '24 hours' GROUP BY p.name;"
```

**Logs on disk:** container logs rotate at 10 MB × 5 per service. Host nginx keeps its own logs under
`/var/log/nginx/`.

## 8. Models

**Endpoints** are data: see `scripts/prod/set-model-endpoint.sh --show` and §10. The runtime settings
are fixed in the override:
- `OLLAMA_CONTEXT_LENGTH=8192` (the profile's `num_ctx` is ignored over `/v1`);
- `NUM_PARALLEL=1`;
- `MAX_LOADED_MODELS=1`;
- `FLASH_ATTENTION=1`;
- `KEEP_ALIVE=24h`.

**Pull or update a model.** Tags are pinned; verify a new tag on ollama.com before pulling it:
```bash
scripts/prod/dc exec ollama ollama pull <tag>
scripts/prod/dc exec ollama ollama list
scripts/prod/dc exec ollama ollama rm <tag>
```

**Upgrade Ollama itself:** change the `ollama/ollama` tag in the override, deploy, then **re-run the
qualification**, because a runtime change can change answers.

**Fixtures** go in `/var/www/injazedu-ai/fixtures/` and are copied from the Mac. They are never in Git,
and the smoke and qualify commands never print their text:
```bash
F=~/Projects/injaz-m5-fixtures
scp -p "$F/real-moderation.jsonl" "$F/real-attention.jsonl" "$F/real-attention-extra.jsonl" \
       "$F/real-attention-fresh-v1.jsonl" sambo@84.46.248.13:/var/www/injazedu-ai/fixtures/
ssh sambo@84.46.248.13 'chmod 600 /var/www/injazedu-ai/fixtures/*.jsonl && cd /var/www/injazedu-ai/fixtures && sha256sum *.jsonl'
(cd "$F" && shasum -a 256 real-moderation.jsonl real-attention.jsonl real-attention-extra.jsonl real-attention-fresh-v1.jsonl)
```

**Smoke and qualify E2B** before activating the moderation profile:
```bash
make smoke-llm                                         # one structured generation + one embedding
FIXTURES=/var/www/injazedu-ai/fixtures/real-moderation.jsonl \
  make smoke-moderation ARGS="--profile ollama-gemma4-e2b-moderation --prompt classify_v2"
make qualify TASK=moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 \
  FIXTURES_DIR=/var/www/injazedu-ai/fixtures REPEAT=2
```
- Activate only on **QUALIFIED**.
- Moderation gates Q5–Q8, Q11 and Q12; latency is reported, not gated.
- Never edit a prompt or threshold to make it pass.

**E4B is measurement only, never activated.** It is about 6.1 GB on disk and ~7 GB loaded, so
measure it alone:
1. Confirm `free -h` shows swap on and at least 8.5 GB available.
2. Set `OLLAMA_MEM_LIMIT=8500m` in `.env`, then run `scripts/prod/dc stop ai-worker ai-control` and
   `scripts/prod/dc up -d ollama`.
3. Pull `gemma4:e4b-it-qat`. Run `make smoke-attention ARGS="--profile ollama-gemma4-e4b-attention
   --prompt attention_v1" FIXTURES=…` and/or
   `make qualify TASK=attention PROFILE=ollama-gemma4-e4b-attention PROMPT=attention_v1 FIXTURES_DIR=… REPEAT=2`.
   Watch `docker stats`.
4. Unload E4B with `scripts/prod/dc exec ollama ollama stop gemma4:e4b-it-qat`. Restore
   `OLLAMA_MEM_LIMIT=6500m` and run `scripts/prod/dc up -d`.

## 9. Database: migrations, export, import, rollback

**Migrations** are additive Alembic revisions applied by `deploy.sh` as `ai_migrator`. Never apply them
as another role, or new tables lose the automatic grants to `ai_app` and `ai_control`. To inspect:
```bash
scripts/prod/dc --profile tools run --rm migrate alembic current
scripts/prod/dc --profile tools run --rm migrate alembic history --indicate-current
```

**Export** (any time; `deploy.sh` does it before migrating):
```bash
( umask 077; scripts/prod/dc exec -T postgres pg_dump -U postgres -d injaz_ai -Fc \
    > /var/www/injazedu-ai/dumps/injaz_ai-$(date -u +%Y%m%dT%H%M%SZ).dump )
```

**Import over the live database.** This replaces all its data, so first stop everything that writes:
```bash
scripts/prod/dc stop ai-api ai-worker ai-classifier ai-telegram ai-control
scripts/prod/dc exec -T postgres pg_restore -U postgres -d injaz_ai --clean --if-exists --single-transaction \
  < /var/www/injazedu-ai/dumps/<file>.dump
scripts/prod/dc up -d
```

**Import onto a new server:**
1. First deployment (§5) **without** `deploy.sh`'s migration step: start only `postgres`.
2. `pg_restore -d injaz_ai` the dump; owners and grants come with it, because initdb created the roles.
3. Then `deploy.sh`, which finds the database already at head.

**Rollback:**
- **Code only** (no migration ran): `scripts/prod/deploy.sh <previous sha>`. The previous deploy printed
  it.
- **A migration ran:** import the `dumps/…-before-<sha>.dump` file written by that deploy (above), then
  `scripts/prod/deploy.sh <previous sha>`.

**Backups.** Contabo Auto Backup copies the whole disk daily (10 versions), including Docker volumes.
- **Its restore is whole-VPS only:** it rolls back every site on the host. It is the last resort.
- A file-level copy of a running Postgres is not guaranteed consistent; the dumps are the reliable
  restore point for this database.

## 10. Switching the inference endpoint (a future GPU host)

Each profile's `base_url` (Postgres, `model_profiles`) decides where its calls go. The gateway already
supports `provider` `ollama` or `vllm`, plus a Bearer key through the profile's `api_key_env`, so no
code change is needed.

1. Run the inference server on the GPU host with the same model and the same runtime version:
   - **Ollama 0.40.4** with the same tags, behind a proxy that checks a Bearer token; or
   - **vLLM** with `--api-key` and `--max-model-len 8192`.

   Expose it only over HTTPS, firewalled to `84.46.248.13`, or only inside a WireGuard/Tailscale
   tunnel.
2. Put the key in `.env` (`INFERENCE_API_KEY=…`), then run
   `scripts/prod/dc up -d ai-worker ai-classifier`. The override already passes the variable through.
3. In the panel, create a new **inactive** profile:
   - same role, model and params;
   - `base_url https://<gpu-host>/v1`;
   - `api_key_env INFERENCE_API_KEY`.

   Alternatively, move an existing profile with
   `scripts/prod/set-model-endpoint.sh https://<gpu-host>/v1 <profile>`.
4. **Qualify it on that host** (`make qualify …` as in §8). A model is qualified on the host that
   serves it.
5. Activate it in the panel; one profile is active per role.
6. Optional: point `OLLAMA_BASE_URL` at the remote for the `/health` probe. That probe speaks Ollama's
   API, so with vLLM it reports the optional `model_runtime` component as unreachable.
7. Stop the local runtime with `scripts/prod/dc stop ollama`. To keep `deploy.sh` from starting it
   again, move `ollama` under a compose profile in the override.

## 11. Telegram activation (separate approval)

**Preconditions:**
1. **No other consumer of this token.** A second poller causes 409 conflicts, and the poller stands
   down after 5 in a row.
   - The Mac's dev stack runs `ai-telegram` with its own `.env` token.
   - Use a different bot for development, or stop the Mac poller with
     `docker compose -f infra/docker-compose.yml --env-file .env stop ai-telegram`.
   - No webhook may be set on the token.
2. You know the production bot's @username.

**Steps:**

1. Put the token in `.env`: `ssh -t sambo@84.46.248.13 'nano /var/www/injazedu-ai/repo/.env'`, setting
   `TELEGRAM_BOT_TOKEN=`. Never paste it into chat or a ticket.
2. Run `make tg-doctor` (on the server, in the repo). It must show the token present, the expected
   @username from `getMe`, no webhook, and the subscriptions.
3. Start polling: `scripts/prod/dc up -d ai-telegram ai-api`. `ai-api` reads the token for `/health`'s
   Telegram block.
4. In the panel, go to Telegram Chats and mark **only the main groups** as monitored.
5. Watch for the first days:
   - `scripts/prod/dc logs -f ai-telegram ai-classifier`;
   - the queues (§7);
   - latency (§7's query);
   - `/health`'s `telegram_ingestion` block;
   - the panel's Classification Accuracy page.

**Roll back:** blank the token, then `scripts/prod/dc up -d ai-telegram ai-api`. The poller exits 0,
and captured data stays.

**Known limitation:** after a stand-down, `/health` keeps reporting "stood down" until the
`ingestion_state` row is corrected. Restarting the poller resumes capture.

## 12. Never on production

| Command | Why |
|---|---|
| `make check`, `make test-db-reset` | The suite starts its own worker on localhost Redis and resets a test schema. Production has no test database; run the suite on the Mac. *(refused)* |
| `make migrate-down` | Downgrades drop tables. Use a dump instead (§9). *(refused)* |
| `make down-hard`, `docker compose down -v`, `docker volume rm`, `docker system prune --volumes` | Delete the volumes: the database, the queue, the models, the panel's storage. *(`make down-hard` refused)* |
| `php artisan db:seed` | Creates `test@example.com` / `password` as a panel operator |
| `php artisan migrate`, `migrate:fresh`, `db:wipe` | Alembic owns the schema; the destructive ones are blocked by the app |
| Publishing a port on `0.0.0.0` | Docker bypasses ufw |

## 13. Maintenance window (needs the operator's approval)

**Package updates and their effects on the running sites:**

| Package | Upgrade | Effect |
|---|---|---|
| `docker-ce` / `containerd` | `apt upgrade` | Restarts dockerd, so **every container**, including the clinic stack, stops and starts. Restart policies bring them back |
| `php8.2-fpm` | `apt upgrade` | Restarts it: kunooz.ai and arch.kunooz.ai blip |
| A new kernel or libc | Needs a reboot | Every site is down for 1–3 minutes. The Contabo VNC console is the fallback |

**Order:**
1. Run `00-readonly-report.sh`.
2. `sudo apt update && sudo apt upgrade`.
3. Optionally `03-maintenance-journald.sh --archive <dir> --apply`.
4. `sudo reboot`.
5. Afterwards, verify:
   - `scripts/prod/dc ps` shows everything up (`ai-telegram` stays exited while its token is blank);
   - `curl -s http://127.0.0.1:18000/health`;
   - `https://ai-control.injazedu.co/admin` loads;
   - the other sites load: kunooz.ai 302, amin.kunooz.ai 200, arch.kunooz.ai 401.

**The journal** is already capped by journald at 4 GiB on this host. Lowering the cap deletes the
oldest entries, so archive first.

## 14. Troubleshooting

| Symptom | Look at |
|---|---|
| The panel shows `http://` links or a redirect loop | Is nginx sending `X-Forwarded-Proto`? Does `TRUSTED_PROXIES` equal the network gateway (`docker network inspect injazedu-local-ai_default`)? |
| `/health` returns 503 | Its JSON names the failing part (database, broker, or worker heartbeat). Check `scripts/prod/dc ps` and that service's logs |
| Classifications stop | `ai-classifier` logs; `ollama ps`; the queue lengths (§7). The gateway's breaker opens after 5 failures for 30 s, and tasks retry 30/60/120/240 s |
| Ollama is killed (OOM) | `docker inspect -f '{{.State.OOMKilled}}' $(scripts/prod/dc ps -q ollama)`. Check that only one model is loaded, then check `OLLAMA_MEM_LIMIT` |
| Slow answers | `docker stats` for CPU steal and saturation; §7's latency query. CPU inference is the limit, and §10 is the way out |
| Certificate renewal fails | `sudo certbot renew --dry-run`. If the Cloudflare proxy was switched on, see §4 |
| 409 conflicts in the `ai-telegram` logs | Another poller uses the token (§11) |
| The `migrate` image runs old code | `deploy.sh` rebuilds it. When running by hand: `scripts/prod/dc --profile tools build migrate` |
