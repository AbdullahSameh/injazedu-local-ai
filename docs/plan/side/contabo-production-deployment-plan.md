# InjazEdu Local AI — Contabo production deployment plan (v2)

## Status and context

- **v2 (2026-10-16)** replaces v1 (2026-10-15). It folds in the operator's final decisions and a re-check of the server.
- **Progress (2026-10-16):**
  - **Phase C** merged to `main` as `e5a4bd6`.
  - **Phase E** E0–E8b, E10 and E11 are done on the server; E9 (the admin account) is the operator's.
    - Deployed `e5a4bd6`; HTTPS on both domains; `ai.` serves only `/health/live`.
    - From outside, only ports 22, 80 and 443 are open; the neighbours still answer 302 / 200 / 401.
    - E2B + `classify_v2` is **QUALIFIED** on this host, line for line as on the Mac. The moderation profile stays inactive until the operator approves it.
    - The E4B measurement was taken and E4B was never activated.
    - Restart and `down`/`up` survival hold, with the volumes intact.
    - Measured figures: runbook §8.
  - **Found on the host:**
    - llama.cpp ran 6 threads on Ollama's 5 CPUs, giving 0.2 instead of 18.3 tokens/s. The fix (`OLLAMA_THREADS`) is local, waiting for the operator's commit; the server runs it from a temporary override file until then.
    - `make` isn't installed on the server, so the runbook uses `scripts/prod/dc`.
  - **Still to come:**
    - Phase M, the maintenance window;
    - Phase G, Telegram (separate approval).
  - Operating guide: `docs/runbooks/production-deployment.md`.
- **Goal:** a secure, practical, resource-efficient production deployment of the whole stack on the Contabo VPS (`84.46.248.13`):
  - Laravel/Filament, FastAPI, the workers, Postgres + pgvector, Redis and Ollama, all in Docker;
  - the existing host nginx and certbot in front;
  - Telegram off.
- **Later:** only LLM inference may move to a GPU host (Vast.ai or RunPod). The deployment must leave that seam open without building any of it now.

**Constraints that hold throughout:**
- The existing apps are not disturbed: clinic, kunooz.ai, amin.kunooz.ai, arch.kunooz.ai, host MySQL, and the existing nginx/certbot configuration.
- No passwordless sudo. You run every privileged step yourself, after reviewing it.
- You make every Git commit and push (constitution IV).
- Never run `make check`, `db:seed` or `migrate-down` against production.
- No connection to the main InjazEdu MySQL.
- TG-M5.x behaviour is unchanged:
  - `classify_v2`, thresholds 0.60 / 0.85;
  - attention settings blank, so AI-assisted opening is off;
  - no `classify_v3`.
- Real Telegram fixtures never go into Git.

---

## 1. Server re-check (2026-10-16, read-only)

| Item | Audit (10-15) | Now | Effect |
|---|---|---|---|
| RAM | 11.6 GB, 1.6 GB used | **10.4 GB available**, no swap | Unchanged |
| Disk | `/` 96 G, 83 G free | Same (single 100 GB disk; no 200 GB volume) | Unchanged |
| Containers and ports | clinic ×4 on 127.0.0.1:8081/8082; host MySQL on 127.0.0.1:3306; nginx on 80/443; ssh 22 | Same | No conflicts on the planned 127.0.0.1:18000/18080 |
| Neighbour restart policies | — | All 4 clinic containers `unless-stopped`; Docker `live-restore=false` | A Docker upgrade restarts clinic, and it comes back on its own |
| `/var/www` | clinic, html, k-wating-list | Same; `injazedu-ai/` absent | Creating it needs sudo |
| DNS | `ai.`, `ai-control.` absent | Still absent | You create them |
| Updates | 142 (26 security) | **119 upgradable, 3 standard security** (+7 ESM). Unattended-upgrades has applied most security fixes | See §7 |
| Reboot | pending | **Still pending.** Running kernel 6.8.0-111, installed 6.8.0-147, plus libc6 | See §7 |
| Journal | ~4 GB | **4.0 G.** No overrides (default cap = min(10% of disk, 4 G) = 4 G, already reached, so it no longer grows). 92 system + 4 user files spanning 2026-06-21 → today | See §7 |
| `btmp` | — | 101 MB this month + 169 MB last month of failed logins. Password auth is already off, so these are blocked SSH brute-force attempts | fail2ban optional |
| Backup agents on the VPS | — | None (Contabo Auto Backup is host-side) | See §8 |
| Neighbour baseline | — | kunooz.ai **302**, amin.kunooz.ai **200**, arch.kunooz.ai **401** (basic auth); all with valid TLS | Re-checked after every server step |

**Not readable without sudo:** ufw rules, journal contents and sources, the unattended-upgrades log. Privileged script `00` (read-only) collects them.

## 2. Corrections and new findings since v1

1. **Moderation qualification has no latency gate.**
   - v1 was wrong about this. `make qualify TASK=moderation` hard-gates Q5–Q8, Q11 and Q12 (false negatives and positives on the real, shipped and policy sets; repeat; errors; tracked lines).
   - Latency is reported only. The `p95 ≤ 10 000 ms` gate (A8) applies **only to attention**.
   - So E2B moderation can qualify on CPU even if slow. Whether the speed is acceptable is judged separately, against your workload (§6).
2. **Baseline on the Mac:** e2b + `classify_v2` was `QUALIFIED` (T002 and its re-run on 2026-10-08, identical per line).
3. **Qualifying on the CPU is still required.** CPU and Metal arithmetic can produce different answers even at temperature 0, which is exactly why spec 010 says to qualify on the production host.
   - If Contabo gives `NOT QUALIFIED`, the moderation profile stays inactive (rules-only) and I report it.
   - No prompt or threshold is changed to make it pass.
4. **The GPU seam already exists in code. No new abstraction is needed.**
   - `model_profiles.provider ∈ {ollama, vllm, fake}`.
   - `base_url` is set per profile and stored in Postgres.
   - `api_key_env` names an environment variable whose value is sent as `Authorization: Bearer …` (`app/providers/llm/openai_compatible.py:87-95`).
   - `options.num_ctx` is sent only for `ollama`.
   - `OLLAMA_BASE_URL` only feeds the optional `/health` probe.
5. **Contabo Auto Backup** is daily, full disk then incremental, stored off-server, with 10 versions. **Restore is whole-VPS only:** it overwrites the entire server, which would also roll back clinic and kunooz. See §8.
6. **Real fixtures exist locally** in `~/Projects/injaz-m5-fixtures/`. See §5.

## 3. Architecture

```
Internet ─443─▶ host nginx (existing; two new site files) ─┬─ ai-control.injazedu.co ─▶ 127.0.0.1:18080 ─▶ ai-control
                                                            └─ ai.injazedu.co (GET /health/live only) ─▶ 127.0.0.1:18000 ─▶ ai-api
Compose project "injazedu-local-ai", own bridge network, nothing else published:
  postgres (pgvector/pgvector:0.8.6-pg16-bookworm, volume)    redis (7.4, AOF, volume, noeviction)
  ai-worker   ai-classifier   ai-telegram (TELEGRAM_BOT_TOKEN blank → exits 0, stays down)
  ollama (ollama/ollama:0.40.4 = dev version, volume) ◀── reached only through model_profiles.base_url
```

**Endpoints are data, not code.**
- After seeding, a small script (`scripts/prod/set-model-endpoint.sh`) sets the Ollama profiles' `base_url` to `http://ollama:11434/v1`. `OLLAMA_BASE_URL` is set to `http://ollama:11434`. There is no `host.docker.internal` dependency in production.
- The same script, or the panel's Model Profiles page, is the future GPU switch. Mac development keeps `host.docker.internal` unchanged.

**Future GPU host (documented only, nothing built):**
1. Create a profile for the remote host: `provider` `ollama` or `vllm`, `base_url https://<gpu>/v1`, `api_key_env=INFERENCE_API_KEY`.
2. Put the key in the server `.env`. The prod override pre-wires a blank `INFERENCE_API_KEY` passthrough to ai-classifier, ai-worker and migrate.
3. Secure the link with HTTPS plus that Bearer key (vLLM `--api-key`, or Ollama behind a token-checking proxy), restricted to the Contabo IP, or with a WireGuard/Tailscale tunnel.
4. **Re-qualify on that host** before activating, as on any inference-host change.
5. Then stop the local `ollama` service.

**Resource isolation:**

| Setting | Value |
|---|---|
| `mem_limit` | postgres 1g · redis 256m · ai-api 512m · ai-worker 768m · ai-classifier 384m · ai-telegram 256m · ai-control 512m · ollama 6.5g |
| Ollama CPUs | `cpuset 1-5` (CPU 0 left for nginx, MySQL and the neighbours) |
| Ollama environment | `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KEEP_ALIVE=24h` |
| Logs | json-file 10 MB × 5 per service |
| Restart policy | `unless-stopped`; `on-failure` for ai-telegram, so its deliberate exits (no token, 409 stand-down) are respected |

Expected memory with E2B: ≈ 8.4 GB of 11.6.

## 4. Conflicts and risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | CPU latency is unknown. Mac Metal gave ~1 s; this is 6 shared vCPUs with AVX2 only | Measure p50/p95, load time and throughput (§6). Recommend a GPU host only if the measurements say so |
| R2 | CPU qualification may differ from the Mac | Qualify here; inactive (rules-only) if not `QUALIFIED`; no prompt or threshold edits |
| R3 | Auto Backup restore is whole-server | Before each migration, a manual `pg_dump` to disk, so the AI DB can be rolled back alone (§8) |
| R4 | E4B (~7–7.5 GB) is tight next to the neighbours | Test only with swap on and MemAvailable ≥ 8.5 GB; ai-worker and ai-control paused during the test; Ollama limit 8.5g temporarily; never activated |
| R5 | Telegram 409 conflicts: your dev `.env` has a token set | Prod token stays blank until Phase G; the Phase G checklist confirms no other consumer |
| R6 | Raw Telegram text is kept indefinitely (no purge yet) | Accepted for now. Auto Backup copies hold personal data. Watch disk growth: 146k members ⇒ `chat_member` updates may far outnumber the 50–150 messages per day |
| R7 | PHP 8.2 security support ends 2026-12-31 | Keep 8.2 now for parity with the tests; upgrade later |
| R8 | The paid textbooks are in the (private) repo, so they land on the server with the clone | Accepted; the repo is private |
| R9 | Without Telegram, the classifier actor can't run end to end (it needs ingested messages) | Infrastructure phase proves gateway, model and storage (`model_runs`) via the smokes. The full pipeline is proven in Phase G with a test bot first, only if you approve |

## 5. Fixtures

**Location on the server:** `/var/www/injazedu-ai/fixtures/` (mode 700, files 600), outside the clone, never in Git. The smoke and qualify commands never print fixture text. I won't `cat` the files and will compare only SHA-256 hashes.

| File | Needed for | Required keys (schema) | Optional keys | Local status (`~/Projects/injaz-m5-fixtures/`) |
|---|---|---|---|---|
| `real-moderation.jsonl` | **Required.** Smoke before activation, and Q5 of `qualify TASK=moderation` | `text`, `category` (taxonomy, e.g. `SPAM_OR_AD`, `ABUSE`, `CHITCHAT`, `OTHER`), `needs_moderation` (bool) | `tracked`: `no-link-rule` \| `label-review` | **Present**, 11 lines (keys: text, category, needs_moderation, tracked) |
| `real-attention.jsonl`, `real-attention-extra.jsonl` | Optional: E4B measurement only (attention suite) | `text`, `needs_response` | `intent` (one of six; `asking` ⇔ needs_response), `label_class` (`clear`/`ambiguous`), `peer`, `tracked` | **Present**, 24 + 24 lines |
| `real-attention-fresh-v1.jsonl` | Optional: E4B measurement (picked up by the `real-attention*.jsonl` glob) | as above | as above | **Present**, 37 lines |
| `fresh-attention.jsonl` | Attention verdict only (not needed: attention stays off) | as above | — | **Absent** from the active folder (only `backup/`). The attention verdict would read INCOMPLETE, which is acceptable for a measurement-only run |

- **Shipped sets** (`moderation_smoke_fixtures.jsonl`, `moderation_smoke_policy_fixtures.jsonl`, `attention_*_fixtures.jsonl`) are synthetic or sanitised and already in the repo. They arrive with the clone.
- **Additional real examples:** none are required for the gates. *Recommended but optional:* 20–30 fresh real messages from the main groups, especially legitimate posts that look like adverts, labelled by you before any run. They give a CPU-host false-positive check. I will not fill this gap with synthetic data.

**Transfer** (you run these after privileged step 01 creates the folder):
```bash
F=~/Projects/injaz-m5-fixtures
scp -p "$F/real-moderation.jsonl" "$F/real-attention.jsonl" "$F/real-attention-extra.jsonl" \
       "$F/real-attention-fresh-v1.jsonl" sambo@84.46.248.13:/var/www/injazedu-ai/fixtures/
ssh sambo@84.46.248.13 'chmod 600 /var/www/injazedu-ai/fixtures/*.jsonl && cd /var/www/injazedu-ai/fixtures && sha256sum *.jsonl'
(cd "$F" && shasum -a 256 real-moderation.jsonl real-attention.jsonl real-attention-extra.jsonl real-attention-fresh-v1.jsonl)   # compare
```

## 6. Workload and what will be measured

**Initial load:** about 50–150 messages per day from the main groups. With attention off, each eligible message makes **one** `classify_message` call, so ≤ 150 model calls per day (about one every 10 minutes on average).

| Per-call latency | Daily inference time | Burst of 20 drains in |
|---|---|---|
| 30 s | ≤ 75 min | ~10 min |
| 10 s | ≤ 25 min | ~3–4 min |

Postgres and Redis load is negligible. Latency only delays when an incident appears in the panel; no bot action depends on it.

**Measured on Contabo and reported, with no assumptions:**
- Ollama cold-load time for E2B and the embedding model.
- Per-call latency p50/p95, from the qualify run (each line run twice) and `model_runs`.
- Throughput (calls per minute in a back-to-back smoke).
- CPU from `docker stats` and `mpstat`; RAM from `free` and Ollama `/api/ps`.
- Queue behaviour: diagnostics ping round trip; `/health` worker heartbeat.
- Qualification verdict and gate table.
- The same measurements for E4B, separately.

**Recommendation rule:** move only inference to a GPU host if:
- p95 makes a 20-message burst take longer than you find acceptable, or
- qualification fails on CPU, or
- E4B is ever wanted.

## 7. Server maintenance (a separate operation, needs your window)

**Package updates:**

| Package group | Upgrade | Effect on running services |
|---|---|---|
| Docker | `docker-ce` 29.5.0→29.9.1, `containerd` 2.2.3→2.4.2, compose 5.1.3→5.6.0 | Upgrading restarts dockerd, so **every container stops and starts**: clinic (comes back via `unless-stopped`) and ours. Downtime ~1 min |
| PHP | `php8.2-fpm` 8.2.29→8.2.34, plus php8.4/8.5 CLI | php-fpm restarts: kunooz.ai and arch.kunooz.ai blip for seconds |
| Kernel and libc | 6.8.0-147, libc6 | **Reboot needed.** All sites down ~1–3 min. Small risk of a boot problem (recovery via the Contabo VNC console) |
| Not in the list | nginx, mysql-server | — |

**Journal:**
- No action is needed for the deployment: journald is capped at 4 G already, and our containers log to rotated json-file.
- Optional, in the window:
  1. review the top sources (script 00 prints counts per unit, never message text);
  2. add `/etc/systemd/journald.conf.d/50-injazedu-size.conf` with `SystemMaxUse=1G`;
  3. vacuum, which **deletes June–September entries**; archive them first if you want to keep them.

**Recommendation:** run the window **after** Phase F verification. The reboot then doubles as the restart-survival test. fail2ban is optional and not proposed by default.

## 8. Backups (simplified, per your decision)

**Kept:**
- Named volumes for Postgres, Redis (AOF), Ollama models and Laravel `storage/`.
- **One manual `pg_dump -Fc` to `/var/www/injazedu-ai/dumps/` before every migration** (inside `deploy.sh`; not a cron, no retention system).
- Documented export and import commands.

**Dropped:** nightly cron, the 14-day retention, offsite integrations, restore drills.

**Auto Backup:**
- Docker data (`/var/lib/docker/volumes`) and `/var/www` live on the single backed-up disk, so they are included.
- **A file-level copy of a running Postgres is not guaranteed consistent.** The pre-migration dumps, which Auto Backup also picks up, are the reliable restore point.
- Restoring Auto Backup rolls back the **whole VPS**, so use it only for disaster recovery.
- **Please confirm in the Contabo panel** that Auto Backup is active for this VPS, and note the time of the last backup. I can't see that from the server.

## 9. Implementation sequence

Legend: **[SAFE]** = I do it after you approve this plan. **[YOU]** = you run it. **[STOP]** = I wait for you.

### Phase C — local repo changes [SAFE]; Mac development unchanged

1. **`infra/docker-compose.prod.yml`** (new override, using `!override`/`!reset`):
   - ports bound to localhost or not published;
   - restart policies, log rotation, memory limits, Ollama cpuset;
   - Redis AOF + volume;
   - pinned images;
   - initdb mounts only `00-extensions.sql` + `01-roles.sql`, so **no `injaz_ai_test` in prod**;
   - the `ollama` service;
   - `ai-control` production environment (`APP_URL`, `APP_DEBUG=false`, `LOG_CHANNEL=stderr`, `SESSION_SECURE_COOKIE=true`, `TRUSTED_PROXIES`), storage volume, healthchecks;
   - blank `INFERENCE_API_KEY` passthrough.
2. **`apps/ai-control/Dockerfile.prod`** (new): FrankenPHP (classic mode), PHP 8.2 with the same extensions + opcache, non-root, the same Vite stage. An entrypoint caches config, routes, views and Filament at start. The dev Dockerfile is untouched.
3. **`apps/ai-control/bootstrap/app.php`**: `trustProxies(at: env('TRUSTED_PROXIES'))`. Unset means nothing changes, so dev is identical. Plus `tests/Feature/TrustedProxiesTest.php`. No UI strings.
4. **`infra/nginx/`**: templates for `ai-control.injazedu.co.conf` (proxy, HSTS, security headers, `limit_req`, `/`→`/admin`), `ai.injazedu.co.conf` (`= /health/live` only, otherwise 404), and `injazedu-ai-limits.conf` (rate-limit zones only).
5. **`scripts/prod/`**:
   - `dc`: compose wrapper.
   - `deploy.sh`: pull a pinned SHA, build including `migrate`, pre-migration `pg_dump`, `alembic upgrade head`, up, health gate.
   - `set-model-endpoint.sh`.
   - `sudo/00-readonly-report.sh`, `sudo/01-bootstrap.sh`, `sudo/02-nginx-certbot.sh`, `sudo/03-maintenance-journald.sh` (optional).
6. **`.env.production.example`**: names and placeholders only.
7. **Makefile**: `COMPOSE_FILES ?= -f infra/docker-compose.yml` (dev default identical) so the smoke, qualify and migrate targets work in prod.
8. **`docs/runbooks/production-deployment.md`**: architecture; environment; Docker commands; first deploy; updates; logs and troubleshooting; restarting a service; migrations; manual pg export/import; Ollama model updates; **switching to a GPU host**; rollback; monitoring; **Telegram activation**. Plus a one-line pointer in `README.md`.
9. **Checks (all local):**
   - `make check` on the Mac (ruff, mypy, pytest, PHPUnit, secret scan);
   - `docker compose -f … -f infra/docker-compose.prod.yml config` renders;
   - `Dockerfile.prod` builds, and the panel boots locally under a separate project name.
10. **[STOP 1]** I give you a summary of the diff and the exact `git switch -c …` / `git add` / `git commit` / `git push` commands. **[YOU]** commit and push. I continue from the pushed SHA.

### Phase E — Contabo deployment

| Step | Who | Action |
|---|---|---|
| E0 | [YOU] | `sudo bash scripts/prod/sudo/00-readonly-report.sh`. Read-only: ufw status, `nginx -t`, journal sources by count, journal disk usage, unattended-upgrades summary. **Changes nothing.** |
| E1 | [YOU] | `01-bootstrap.sh`, which **modifies**:<br>• creates `/var/www/injazedu-ai/{repo,fixtures,dumps}` owned by `sambo` (fixtures 700);<br>• adds a 4 GB `/swapfile` with an `/etc/fstab` line;<br>• adds `/etc/sysctl.d/99-injazedu-ai.conf` (`vm.swappiness=10`).<br>Nothing else. Then you `scp` the fixtures (§5). |
| E2 | [SAFE] | Clone the pinned SHA into `repo/`. Generate `.env` (mode 600) with random secrets, never printed. `TELEGRAM_BOT_TOKEN=` blank, attention settings blank, `MODERATION_PROMPT_VERSION=classify_v2`. |
| E3 | [SAFE] | Build. Start postgres and redis; verify the `vector` extension, the roles, that there is no test DB, and that nothing is published. |
| E4 | [SAFE] | `alembic upgrade head` on the **fresh empty** DB (0001–0008, additive). `seed_profiles`. `set-model-endpoint.sh` → `http://ollama:11434/v1`. |
| E5 | [SAFE] | Start Ollama; pull `gemma4:e2b-it-qat` and `embeddinggemma:300m-qat-q4_0`; record load times. |
| E6 | [SAFE] | Start ai-api, ai-worker, ai-classifier and ai-control. ai-telegram exits 0 and stays down. Re-check the neighbour baseline. |
| E7 | [SAFE] | `smoke-llm` (generation + embedding); `smoke-moderation` on `real-moderation.jsonl`; `make qualify TASK=moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=… REPEAT=2`. **If both pass:** activate `ollama-gemma4-e2b-moderation` (inert while Telegram is off). **Otherwise:** leave it inactive and **[STOP]** with the report. |
| E8 | [YOU] | Create the DNS records (§10). |
| E8b | [YOU] | `02-nginx-certbot.sh`, which **modifies** only:<br>• adds the 3 new files under `/etc/nginx/sites-available` + `conf.d`;<br>• symlinks the 2 sites into `sites-enabled`;<br>• runs `nginx -t` (aborts on failure, before reload);<br>• `systemctl reload nginx`;<br>• `certbot --nginx -d ai.injazedu.co -d ai-control.injazedu.co` (adds only these certificates and renewal configs).<br>It does not touch existing site files. Then I verify HTTPS and the neighbours. |
| E9 | [YOU] | Create the admin. One interactive command, so the password never reaches me:<br>`ssh -t sambo@84.46.248.13 'cd /var/www/injazedu-ai/repo && read -rp "Email: " ADMIN_EMAIL && read -rsp "Password: " ADMIN_PASSWORD && echo && export ADMIN_EMAIL ADMIN_PASSWORD && scripts/prod/dc run --rm -e ADMIN_EMAIL -e ADMIN_PASSWORD ai-control php artisan app:seed-admin'` |
| E10 | [SAFE] | E4B measurement, gated on swap on and MemAvailable ≥ 8.5 GB. Temporarily: Ollama limit 8.5g, ai-worker and ai-control paused. Pull `gemma4:e4b-it-qat`; run `smoke-attention` + `qualify TASK=attention PROFILE=ollama-gemma4-e4b-attention PROMPT=attention_v1` (read-only). Measure, then restore the limits and services. **Never activated.** |
| E11 | [SAFE] | Verification (§11) and a `docker compose restart` survival test. The full-reboot test happens in the maintenance window. |
| E12 | [SAFE] | Final report with measured numbers. Runbook updated with them (local edit, so **[STOP]** for your commit). |

**Rollback:** `deploy.sh` keeps the previous SHA and image tags plus the pre-migration dump. Rollback means checking out the old SHA, rebuilding and starting it, and restoring the dump only if a migration ran.

**Data safety:** the production DB is fresh, so there is nothing to lose during first deploy. **On any later deploy, if a migration would drop or alter existing data, I stop and ask.**

### Phase M — maintenance window ([STOP]; you choose the time)

`apt upgrade` → optional journald cap → reboot → I verify every service (ours and the neighbours) comes back.

### Phase G — Telegram go-live ([STOP]; separate explicit approval)

1. Confirm no other process polls the production token: stop the Mac stack's `ai-telegram`, or confirm the dev `.env` token is a different bot.
2. Optional dry run: a **test** bot in a private test group proves ingest → classify → `message_classifications` → panel.
3. Put the production token in the server `.env` via `ssh -t` + an editor, never in chat. Run `make tg-doctor`; it must show the correct bot and no webhook.
4. Start ai-telegram. Mark **only the main groups** as monitored in the panel.
5. Watch queue depth, classification latency, errors and 409 conflicts for the first days.

## 10. DNS records (Cloudflare, zone `injazedu.co`)

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| A | `ai` | `84.46.248.13` | **DNS only (grey)** | Auto |
| A | `ai-control` | `84.46.248.13` | **DNS only (grey)** | Auto |

- No AAAA for now.
- Grey cloud lets Let's Encrypt HTTP-01 reach nginx directly, the same as the existing sites.
- If you later turn the proxy on, set SSL/TLS to **Full (strict)** for these hosts first, or you get a redirect loop.

## 11. Verification checklist (evidence, not assumptions)

**Infrastructure:**
- All healthchecks green.
- Volumes persist across `down`/`up` (postgres, redis AOF, ollama, storage).
- `vector` present; no `injaz_ai_test`.
- `docker stats` stays within the limits.
- `restart` survival.
- **From the Mac:** only 22, 80 and 443 are reachable; 5432, 6379, 11434, 18000 and 18080 are closed.

**Security:**
- Valid certificates.
- `Set-Cookie` has `Secure`; redirects are `https://`, which proves trusted proxies work. The Feature test covers client IP.
- `ai.` routes: `/health`, `/docs`, `/openapi.json` and `/v1/*` return 404; `/health/live` returns 200.
- No secret in `docker inspect` output that I print, or in logs.
- Neighbours still at **302 / 200 / 401**.

**Applications:**
- Panel login over HTTPS.
- Localhost `/health` passes, with the worker heartbeat.
- Diagnostics ping round trip through the `default` queue.
- The panel shows the profiles and the `model_runs` written by the smokes.

**Models:**
- `smoke-llm` (structured output + embedding).
- Real-Arabic `smoke-moderation`.
- Moderation qualification verdict.
- Load times, p50/p95, CPU and RAM for E2B; the same for E4B separately.

**Never on production:** `make check`, `db:seed`, `migrate-down`.

## 12. What I need from you

| # | What | Why | Where you get it | Where it goes | When |
|---|---|---|---|---|---|
| 1 | Approval of this plan (v2) | Starts Phase C | — | — | Now |
| 2 | Review, commit and push of Phase C | Git is yours; the server deploys from the pushed SHA | — | GitHub | STOP 1 |
| 3 | Run privileged scripts 00, 01 and 02 | Root steps without sharing sudo | Your SSH session | Server | E0, E1, E8b |
| 4 | Fixture `scp` (§5) | Real-message smoke and qualification | `~/Projects/injaz-m5-fixtures/` | `/var/www/injazedu-ai/fixtures/` | After E1 |
| 5 | Two Cloudflare A records (§10) | Domains and TLS | Cloudflare dashboard | Cloudflare | Before E8b |
| 6 | Admin email and password, typed into the E9 command | Panel access | You choose | Silent prompt on the server | E9 |
| 7 | Confirm Contabo Auto Backup is active, and the last backup time | Disaster recovery assumption | Contabo customer panel | — | Before E2 |
| 8 | Maintenance window | Updates and the reboot affect clinic and kunooz | — | — | Any time after Phase F |
| 9 | Production bot token, and whether the dev token is a separate bot | One consumer per token | @BotFather | Server `.env` (via `ssh -t`) | Phase G only |
| 10 | *(Optional)* 20–30 fresh labelled real messages | Extra false-positive check on the CPU host | The main groups | Fixtures folder | Before or after E7 |

**Not needed:** main InjazEdu DB or API credentials, n8n, SMTP, or external LLM keys (until a GPU host exists).

## 13. Decisions confirmed

All of these are from your v2 decisions; no other open questions:
- Everything in Docker on Contabo, including Ollama 0.40.4.
- Host nginx and certbot; DNS-only records; `ai.` exposes `/health/live` only.
- You run the privileged scripts yourself; no passwordless sudo.
- Fresh production DB; no test DB; no dev data.
- Ollama settings: `CONTEXT_LENGTH 8192`, `NUM_PARALLEL 1`, `MAX_LOADED_MODELS 1`, `FLASH_ATTENTION 1`.
- E2B active (once qualified); E4B tested only, never activated.
- `classify_v2`, current thresholds, attention off.
- Telegram blank until Phase G.
- Backups: persistent volumes + Auto Backup + a pre-migration `pg_dump` only.
- Updates and reboot in a separate window you approve.
- **Small defaults I chose** (say if you want otherwise): `KEEP_ALIVE=24h`, Ollama `cpuset 1-5`, 4 GB swapfile, E4B kept on disk after the test (6.1 GB of 83 GB free).
