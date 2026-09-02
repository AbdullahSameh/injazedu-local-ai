# Quickstart: M0 — Local AI Service Foundation

**Audience**: the operator, on this MacBook · **Target**: fully healthy environment in under 15
minutes from a clean checkout (SC-001), following only this page.

Nothing here calls a language model. If you are looking for the AI, it starts at M1.

---

## 0. Prerequisites — measured on this machine, 2026-09-02

Three of these are **already satisfied**; two need your hand.

| Prerequisite | Required | Current | Action |
|---|---|---|---|
| Docker Desktop | running, **memory ≤ 5 GB** | running, **7.8 GiB** | ⚠️ **Reduce it** — Settings → Resources → Memory → 5 GB → Apply & Restart |
| Ollama | running natively (not in Docker) | 0.33.2 on `:11434` ✅ | none |
| Ollama environment | 4 variables set | **all 4 unset** | ⚠️ **Set them** — step 1 below |
| `uv` | any recent version | 0.10.12 ✅ | none |
| PHP | ≥ 8.2 | 8.2.27 ✅ | none |
| Python | 3.12 for the local gate | host has 3.13 only | `uv python install 3.12` (step 2) |

> **Why Docker's memory matters.** The budget is Ollama ~6.5 GB + containers 5 GB + macOS ~4 GB on a
> 16 GB machine. At 7.8 GiB for Docker, loading an 8 B model later will swap the machine to a halt.
> Fixing it now costs one restart; fixing it at M5 costs an afternoon of confusing slowness.

### Step 1 — Ollama environment (once, then relaunch Ollama)

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_FLASH_ATTENTION 1
# then quit Ollama from the menu bar and start it again — it reads these at launch
```

Verify with `make doctor`. Note the honest limit: the check reads your login session's environment,
which is what a *relaunched* Ollama inherits. It cannot inspect an already-running process — so if
you skip the relaunch, the check will look green while Ollama still runs on its old settings.

### Step 2 — Python toolchain

```bash
uv python install 3.12     # host has only 3.13; the container pins 3.12 and the gate should match
```

---

## 1. Configure

```bash
cp .env.example .env
```

Then edit `.env` and replace every `CHANGE_ME…` placeholder with a real value. There are **five**
passwords, and they should differ from one another:

- `POSTGRES_PASSWORD` — the image superuser
- `AI_MIGRATOR_PASSWORD` — the only identity allowed to change the schema
- `AI_APP_PASSWORD` — the API and worker
- `AI_CONTROL_PASSWORD` — the Filament panel
- `ADMIN_PASSWORD` — your panel sign-in (used once by `make seed-admin`)

`.env` is gitignored and must stay that way. Full variable reference:
[`contracts/environment.md`](./contracts/environment.md).

```bash
make doctor    # everything must be green before you continue
```

---

## 2. Start

```bash
make up
```

Five services start: `postgres`, `redis`, `ai-api`, `ai-worker`, `ai-control`. **n8n does not** — it
is behind a profile and stays off until a workflow milestone needs it (`make automation-up`).

First run pulls images and builds two of them, so it takes longer than the 90-second warm-start
target; that target (SC-002) is for every subsequent start.

---

## 3. Migrate and create your account

```bash
make migrate       # Alembic → head, from a one-shot container that holds the only migrator credential
make seed-admin    # creates or updates the panel account from ADMIN_EMAIL / ADMIN_PASSWORD
```

`make seed-admin` is idempotent by email — re-run it to reset your own password. No default account
and no default password ships anywhere in this repository.

---

## 4. Verify — the M0 acceptance walkthrough

Each block below proves one of the spec's user stories. Run them in order; the whole sequence takes
about three minutes.

### US1 — the environment starts and reports itself

```bash
make health
```

Expect `"status": "ok"` and **four** named components: `database`, `broker`, `worker`,
`model_runtime`. Then prove it reports failure honestly:

```bash
docker compose -f infra/docker-compose.yml stop postgres
make health          # → 503, database "down", the other three still reported
docker compose -f infra/docker-compose.yml start postgres

# and that the model runtime is informational, not fatal (FR-008):
# quit Ollama from the menu bar, then:
make health          # → still "ok" overall, model_runtime "down"
```

### US2 — the schema has exactly one owner

```bash
make migrate         # again → no-op, succeeds
make migrate-down    # rolls back one revision
make migrate         # back to head, no manual repair

# and the panel's identity cannot change the schema:
make psql
# then, as ai_control:  CREATE TABLE nope (id int);   → ERROR: permission denied for schema public
```

### US3 — background work actually runs

```bash
NONCE=$(curl -s -XPOST localhost:8000/v1/diagnostics/ping | python3 -c 'import sys,json;print(json.load(sys.stdin)["nonce"])')
sleep 2 && curl -s localhost:8000/v1/diagnostics/ping/$NONCE   # → "completed"

# the failure path is recorded, not swallowed:
NONCE=$(curl -s -XPOST localhost:8000/v1/diagnostics/ping -H 'content-type: application/json' -d '{"should_fail":true}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["nonce"])')
sleep 2 && curl -s localhost:8000/v1/diagnostics/ping/$NONCE   # → "failed" + error_type + error_message
make health                                                    # → worker still "ok"
```

### US4 — sign in to the Control Center

Open <http://localhost:8080/admin>, sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Then confirm the
door is actually locked: sign out and request `/admin` again — you should be redirected to sign-in,
not served.

There are **no review screens yet**. An authenticated empty shell is the correct M0 outcome; the
Book Questions queue arrives at M5.

### US5 — the quality gate

```bash
make check           # ruff + mypy + pytest + the PHP feature test + a secret scan. Under 3 minutes.
```

It must pass **with Ollama quit and no network**. If it needs either, that is a bug in M0, not in
your setup.

Then prove the guard that protects your data:

```bash
TEST_DATABASE_URL='postgresql+psycopg://ai_migrator:x@localhost:5432/injaz_ai' make check
# → aborts before any test runs, because the database name has no _test marker
```

### Memory budget

```bash
make mem-report      # per-service and total, against the 5 GB cap
```

---

## 5. Stopping

```bash
make down            # keeps your data
make down-hard       # DELETES the database volume — prompts first, and names what it will destroy
```

`make down` then `make up` must leave your account and schema intact (SC-013). That is worth
verifying once, deliberately, so you trust it later.

---

## Known limitations of M0 — by design, not oversight

- **No AI.** No model call, no prompt, no textbook, no retrieval. M1 onward.
- **No InjazEdu integration.** Nothing reads or writes InjazEdu, and `injazedu/` is untouched.
- **The panel is an empty authenticated shell.** Review screens are M5.
- **No password-reset or in-app notification flow** — those Laravel tables are deliberately not
  created (research D-07). Use `make seed-admin` to reset your own password.
- **Your host `psql` is 14 against a server 16.** Use `make psql`. Host `pg_dump` will refuse the
  version mismatch; install a PostgreSQL 16 client before backup work begins.
- **No backups yet.** The plan's §18 nightly encrypted dump has no milestone assigned. Worth fixing
  before the corpus is large — flagged in [`research.md`](./research.md) §7.
- **Local only.** Everything binds to localhost; there is no inbound access and no TLS, because
  nothing needs to reach this machine.

---

## If something is wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `make up` fails naming a variable | `.env` incomplete | Fill the named placeholder; the message tells you which |
| `make up` fails on a port | Something already owns 8000 / 8080 / 5432 / 6379 | Stop it, or change `API_PORT` / `CONTROL_PORT` in `.env` |
| `make migrate` errors on the `vector` extension | The volume predates the init SQL | `make down-hard` then `make up` — this recreates the volume, so only do it when the data is disposable |
| `worker` reads `down` while the container is running | Heartbeat TTL shorter than the interval | Check `WORKER_HEARTBEAT_INTERVAL_S` < `WORKER_HEARTBEAT_TTL_S`; startup validates this |
| Panel shows "403 / cannot access" after signing in | `is_panel_operator` is false on that account | Re-run `make seed-admin` for that email |
| Everything is slow, machine swapping | Docker memory still at 8 GB | Prerequisite step 0 — reduce to 5 GB and restart Docker |
