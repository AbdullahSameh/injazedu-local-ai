# Phase 0 Research: M0 — Local AI Service Foundation

**Date**: 2026-09-02 · **Plan**: [plan.md](./plan.md) · **Spec**: [spec.md](./spec.md)

Everything marked **verified** was measured on this machine during planning. Everything else is a
decision with its rationale and the alternative that was rejected.

---

## 0. Ground truth measured this session

| Item | Measured value | Consequence for M0 |
|---|---|---|
| Python (host) | **3.13.7 only — 3.12 absent** | D-01: `uv` provisions 3.12; container pins it |
| `uv` | 0.10.12 | Available, no install step needed |
| Docker Engine / Compose | 29.4.0 / v5.1.2 | Compose `profiles`, `mem_limit` both supported |
| Docker memory allocation | **8 393 289 728 B ≈ 7.8 GiB, 10 CPUs** | Still at 8 GB — **operator must reduce to 5 GB** (SC-004) |
| Ollama | 0.33.2, running on `:11434` | Reachable for the informational health probe |
| Ollama models present | `gemma4:e2b-it-qat` (4.34 GB), `embeddinggemma:300m-qat-q4_0` (0.24 GB) | Enough for M0; `qwen3:8b`/`bge-m3` are M1/M4 concerns |
| `OLLAMA_NUM_PARALLEL` / `MAX_LOADED_MODELS` / `KEEP_ALIVE` / `FLASH_ATTENTION` | **all unset** | D-09: documented operator prerequisite + a report script |
| PHP (host) | 8.2.27, Composer 2.8.4 | Meets Filament 5's PHP ≥ 8.2 requirement |
| Node (host) | 23.5.0 | Available, but the image builds assets in its own stage |
| `psql` client (host) | **14.18** vs server 16 | D-20: host `pg_dump` would refuse; use the container's client |
| `.gitignore` | contains only `injazedu/` | D-14: must be extended before any `.env` exists |

---

## 1. Runtime and language

### D-01 — Python 3.12 in the container, provisioned by `uv`

**Decision**: Pin Python **3.12** in `apps/ai-api/.python-version` and in the Dockerfile base image.
`uv` installs 3.12 locally on demand; the host's 3.13 is left alone.

**Rationale**: The approved plan specifies 3.12 (§19), and Principle V says stay inside it. The
container is what actually runs the service, so the host version is irrelevant to correctness — but
the local quality gate must run on the same version as the container, or `mypy` and `ruff` results
diverge from CI-equivalent runs. `uv python install 3.12` makes that free.

**Alternatives rejected**: (a) Adopt 3.13 because it is what the host has — deviates from the
approved plan for no benefit, and 3.13 wheel coverage for build-heavy dependencies is still the
riskier bet. (b) Use the host interpreter directly — breaks reproducibility the moment the operator
upgrades Homebrew.

### D-02 — PostgreSQL 16 via the `pgvector/pgvector:pg16` image

**Decision**: Use the official pgvector image rather than building the extension onto `postgres:16`.

**Rationale**: One pinned image tag, arm64 available, no build step in the operator's first run.
M0 must *prove* vector search is available (FR-010) — starting from an image where it already is
removes an entire failure class from the first-run experience.

**Alternatives rejected**: Build pgvector into a custom image — adds minutes to first start and a
compile toolchain to maintain, for no gain at this scale.

### D-03 — `CREATE EXTENSION vector` happens in init SQL, not in a migration

**Decision**: `infra/postgres/initdb/00-extensions.sql` creates the extension on first boot as the
image's superuser. Alembic's baseline migration **asserts** the extension exists and raises a clear
error if it does not — it never creates it.

**Rationale**: `vector` is not a trusted extension, so `CREATE EXTENSION` requires superuser. Doing
it in a migration would force the migrator role to be a superuser, which would make the whole
role-separation design (D-04) decorative. Asserting instead of creating also gives the exact
behavior the spec's edge case demands: *"migration fails loudly and the health check reports the
database as not ready; it must never be silently skipped."*

**Alternatives rejected**: (a) Run Alembic as `postgres` — kills the privilege model. (b) `CREATE
EXTENSION IF NOT EXISTS` in the migration — silently succeeds as a no-op only if privileges happen
to allow it, and hides the failure otherwise.

---

## 2. Schema ownership and database privileges

### D-04 — Three database identities, enforced by PostgreSQL

**Decision**:

| Role | Used by | Privileges |
|---|---|---|
| `ai_migrator` | the one-shot `migrate` container only | owns all objects; full DDL |
| `ai_app` | `ai-api`, `ai-worker` | `SELECT/INSERT/UPDATE/DELETE` + sequence `USAGE`; **no CREATE** |
| `ai_control` | Filament panel | same as `ai_app` in M0 |

Granted through `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public GRANT …`, so tables
created by future migrations are automatically reachable without re-granting. `CREATE ON SCHEMA
public` is revoked from `PUBLIC` (PostgreSQL 15+ does this by default; the init SQL states it
explicitly so the guarantee does not depend on a default).

**Rationale**: Architecture rule 4 of the approved plan says Filament connects with DML but no DDL.
Encoding that as a database privilege rather than a code convention is what makes FR-013 testable —
the integration test issues `CREATE TABLE` as `ai_control` and asserts the server refuses it.

**Alternatives rejected**: (a) One shared application user — the privilege test would be untestable
and the guarantee would rest on nobody typing `php artisan migrate`. (b) A dedicated `app` schema
instead of `public` — adds `search_path` configuration to three services (including Laravel's
PostgreSQL driver) to buy an isolation we already get from privileges.

### D-05 — Alembic runs from its own one-shot container

**Decision**: A compose service `migrate` (no `depends_on` from api/worker, `restart: "no"`, started
via `make migrate` → `docker compose run --rm migrate`) holds the only copy of the `ai_migrator`
DSN. The `ai-api` and `ai-worker` services receive `DATABASE_URL` built from `ai_app`.

**Rationale**: Credentials the API never receives are credentials the API cannot misuse. It also
makes migration a deliberate operator act rather than a side effect of `up`, which matters the day
a migration is destructive.

**Alternatives rejected**: Run migrations in the API container's startup command — convenient, but
it hands migrator rights to the long-running internet-adjacent process and makes rollback awkward.

### D-06 — Alembic's baseline migration creates exactly one table

**Decision**: `0001_baseline.py` asserts the `vector` extension and creates `users` (Laravel-shaped:
`id` bigserial, `name`, `email` unique, `email_verified_at`, `password`, `remember_token`,
`created_at`, `updated_at`). Nothing else. `downgrade()` drops `users` and is exercised by a test.

**Rationale**: FR-015 bounds M0 to schema-version tracking, the vector capability, and control-panel
account storage. The plan's §8 domain model is introduced by the milestones that consume it —
building it now would create tables no code reads, which is precisely the scope creep Principle V
forbids.

**Alternatives rejected**: Front-load the full §8 schema — would leave a dozen unused tables whose
shape is likely to change once the parser (M2) and answering pipeline (M5) are real.

### D-07 — Laravel's `sessions`, `cache`, and `jobs` tables are avoided, not created

**Decision**: The control panel runs with `SESSION_DRIVER=file`, `CACHE_STORE=file`,
`QUEUE_CONNECTION=sync`. `apps/ai-control/database/migrations/` stays empty, and
`DB::prohibitDestructiveCommands()` is called for every non-testing environment.

**Rationale**: Every Laravel-owned table would be a second thing Alembic has to mirror by hand and
keep in sync forever. Choosing file-backed session and cache drivers reduces Alembic's Laravel
surface to a single `users` table. The panel is a single-operator local tool; file sessions are
entirely adequate.

**Trade-off accepted and documented**: password-reset and database-notification flows are
unavailable in M0 (their tables do not exist). The operator resets a password with the same CLI
command that creates the account. Recorded as a known limitation in the runbook.

**Alternatives rejected**: `SESSION_DRIVER=database` — adds a table, a migration, and a divergence
risk for zero benefit at one user.

---

## 3. Service design

### D-08 — Health check: two endpoints, four components, concurrent probes

**Decision**:

- `GET /health/live` — always `200` while the process is up; no dependency touched. Used as the
  container healthcheck.
- `GET /health` — probes **database**, **broker**, **worker**, **model runtime** concurrently, each
  with a 1 s timeout, and returns the complete per-component body every time. HTTP `200` when the
  overall verdict is `ok`, `503` when it is `degraded` or `down`; the body shape is identical in
  both cases.
- The **model runtime is informational**: it can be `down` while the overall verdict stays `ok`.

**Rationale**: FR-007 requires a definitive per-component answer even when dependencies are down —
which is about always returning a full body, not about always returning 200. Splitting liveness from
readiness stops a down database from causing Docker to restart-loop a perfectly healthy API process.
Concurrent probes with a 1 s cap are what keep SC-002's 2 s budget achievable when two components
are timing out at once.

**Alternatives rejected**: (a) Always return 200 — makes the endpoint useless to any automated
watcher. (b) Sequential probes — three simultaneous timeouts would blow the 2 s budget.

### D-09 — Worker liveness via a Redis heartbeat

**Decision**: A Dramatiq middleware starts a daemon thread on `after_process_boot` that writes
`ai:worker:heartbeat:{hostname}:{pid}` every 5 s with `SETEX` TTL 15 s, carrying pid, host, and
timestamp. The health check reports the worker as `ok` if at least one unexpired heartbeat key
exists, `down` otherwise.

**Rationale**: Dramatiq deliberately exposes no liveness endpoint, and FR-006 requires the health
check to name the worker's status. A TTL'd key means a killed worker disappears on its own — no
stale-state cleanup, no extra table. Redis is already a hard dependency, so this costs one key.

**Alternatives rejected**: (a) Inspect Dramatiq's Redis broker internals for consumers — depends on
private implementation details that are free to change between versions. (b) A `worker_heartbeats`
database table — adds a table to a milestone whose whole point is that it creates one.

### D-10 — Diagnostic tasks are Redis-backed, not database-backed

**Decision**: `POST /v1/diagnostics/ping` enqueues `ping(nonce, should_fail)` and returns the nonce
immediately; the actor writes `ai:diag:{nonce}` (`SETEX`, TTL 300 s) with `completed` and its result,
or `failed` and the exception type and message. `GET /v1/diagnostics/ping/{nonce}` returns
`pending | completed | failed`. `max_retries=0` so the failure path is observable immediately.

**Rationale**: This proves the whole enqueue → execute → observe loop (FR-017–FR-019) without
introducing a `generation_jobs` table that M0 has no other use for. The real job-state table arrives
with the milestone that runs real jobs.

**Alternatives rejected**: Create the plan's `generation_jobs` table now — an unused table, and its
final shape depends on M2/M5.

### D-11 — Concurrency capped for a 16 GB machine

**Decision**: Dramatiq worker started with `--processes 2 --threads 4`. Model-lane semaphores are
**not** built here — they are M1's, because M0 makes no model calls. FR-020 is satisfied by the
documented process/thread caps and the container `mem_limit`.

**Rationale**: §16.4 of the plan specifies 2×4 with the LLM semaphores in the gateway. Building the
semaphores now would mean building the gateway now, which is M1.

### D-12 — `psycopg` 3 for both the async app and sync Alembic

**Decision**: SQLAlchemy 2.0 with `postgresql+psycopg://` — async in the app, sync in `alembic/env.py`,
one driver package.

**Rationale**: `psycopg` 3 supports both modes, so there is one dependency, one DSN format, and one
place where connection behavior can surprise us. `asyncpg` would be marginally faster and would
require `psycopg2` alongside it for Alembic — two drivers, two DSN dialects, for a service whose
bottleneck is a language model.

---

## 4. Control panel

### D-13 — Laravel 12 + Filament 5 *(deviation from the plan's wording — operator visible)*

**Decision**: Laravel **12** with Filament **5.x**.

**Rationale**: Filament 5 requires PHP ≥ 8.2, Laravel ≥ 11.28, Tailwind ≥ 4.1 (checked against the
current Filament docs). The host has PHP 8.2.27, so both Laravel 11 and 12 are viable; Laravel 12
has the longer support window and Filament 5 targets it directly. The approved plan says "Laravel 11
+ Filament", written before Filament 5 shipped.

**This is a deviation from the approved plan's exact wording and is flagged for the operator.** It
changes no architecture, no data flow, and no constitutional gate — the panel is still a
DML-only-database consumer. Say the word and it becomes Laravel 11; nothing else in the plan moves.

### D-14 — `FilamentUser::canAccessPanel()` is mandatory, not optional

**Decision**: `App\Models\User` implements `Filament\Models\Contracts\FilamentUser`, with
`canAccessPanel()` returning true only for accounts flagged as panel operators.

**Rationale**: Filament's own docs are explicit that in any non-local environment the contract must
be implemented or access is refused. Discovering this at deploy time is a wasted afternoon;
implementing it in M0 is a five-line class change and directly serves FR-023.

**Note for M5**: the reviewer/moderator role distinction the review queue will need belongs to M5.
M0 gives every created account panel access and does not build roles — recorded here, not built.

### D-15 — One container, `php artisan serve`

**Decision**: A single `ai-control` container: a `node:22-alpine` build stage compiles Filament's
Tailwind 4 assets, and a `php:8.2-cli` runtime stage serves the panel on port 8080 with
`php artisan serve`, bound to localhost only.

**Rationale**: This is a single-operator panel on a laptop with no inbound access (architecture rule
5). nginx + PHP-FPM would add a second process, a config file, and ~200 MB for throughput nobody
needs. Documented as local-only so it is never mistaken for a production posture.

**Alternatives rejected**: FrankenPHP / Octane — faster, but adds a runtime whose failure modes the
operator would have to learn, in the milestone whose purpose is a boring foundation.

---

## 5. Operator environment

### D-16 — Docker memory: a global operator prerequisite plus per-service limits

**Decision**: The 8 GB → 5 GB reduction is a Docker Desktop setting the operator changes by hand
(`make doctor` reports the current value and fails if it exceeds 5 GB). Compose additionally sets
per-service `mem_limit`: postgres 1.5g · redis 384m · ai-api 768m · ai-worker 1g · ai-control 640m ·
n8n 768m (profiled off). Default-profile total ≈ **4.3 GB**, inside the 5 GB cap.

**Rationale**: §16.6's budget only holds if the global allocation actually drops — measured at 7.8
GiB today. Per-service limits stop any one container from eating the whole budget and are what make
SC-004 verifiable via `make mem-report`.

### D-17 — Ollama environment variables are an operator prerequisite with a report script

**Decision**: `scripts/check_ollama_env.sh` reports `launchctl getenv` for `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_FLASH_ATTENTION=1`, flags any that are
unset, and prints the exact `launchctl setenv` commands to fix them. All four are **currently unset**.

**Honest limitation, documented**: the script reads the *user session's* environment, which is what a
relaunched Ollama will inherit — it cannot read the environment of the already-running Ollama
process. The runbook therefore instructs the operator to quit and relaunch Ollama after setting them.

**Alternatives rejected**: Claim verification via the Ollama HTTP API — `/api/ps` shows loaded
models, not `NUM_PARALLEL`. Asserting a guarantee the API cannot give would be a false green.

### D-18 — Containers reach Ollama at `host.docker.internal:11434`

**Decision**: `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env.example`; the health probe
calls `GET /api/version` with a 1 s timeout.

**Rationale**: Ollama must run natively for Metal access (§16.2), so containers reach it through
Docker Desktop's host alias. `/api/version` is the cheapest endpoint that proves the server is
answering, and it loads no model.

### D-19 — n8n exists in compose but behind a profile

**Decision**: The n8n service carries `profiles: ["automation"]`, so `docker compose up` never starts
it; `docker compose --profile automation up n8n` does.

**Rationale**: §16.6 requires n8n off by default on a 16 GB machine, and FR-003 requires optional
components excluded from the default start with a documented way to start them deliberately.
Defining it now means M11 changes no infrastructure.

### D-20 — Database access goes through the container's client, not the host's

**Decision**: `make psql` runs `docker compose exec postgres psql`. The runbook records that the
host's `psql`/`pg_dump` is **14.18** against a server 16 and that `pg_dump` will refuse the version
mismatch.

**Rationale**: Measured this session. M0 needs no backups (§18 backup work comes later), but the
operator will reach for `psql` on day one and deserves to know why the host binary misbehaves before
they debug it.

---

## 6. Testing and quality gate

### D-21 — The `_test` guard aborts the session, and is itself unit-tested

**Decision**: `tests/conftest.py` defines a session-scoped autouse fixture that resolves
`TEST_DATABASE_URL`, and calls `pytest.exit()` before collection completes unless **all** hold: the
database name contains `_test`; the URL differs from `DATABASE_URL`; and the host is local. The
predicate lives in a plain function that is unit-tested against a table of accepted and rejected URLs.

**Rationale**: Constitution Principle II is non-negotiable, and a guard nobody tests is a guard that
silently rots. Extracting the predicate makes the negative cases testable without needing a real
misconfigured database.

### D-22 — Every M0 test runs offline and model-free

**Decision**: No test starts a model, opens an external connection, or requires network egress. The
model-runtime health probe is exercised against a stub in unit tests; the recorded-round-trip tests
described in §19 of the plan arrive with M1's providers.

**Rationale**: FR-026 and SC-009. It is also what makes the quality gate fast enough to run before
every milestone is called done.

---

## 7. Out-of-scope observations (recorded, not built — Principle V)

1. **The approved plan's §8 domain schema** is fully specified but belongs to M2–M8. Not created here.
2. **Backups** (§18: nightly encrypted `pg_dump`) are named in the plan with no milestone. Worth
   assigning — the operator's textbooks are irreplaceable — but M0's spec does not include it.
3. **Password reset and in-panel notifications** are unavailable until their Laravel tables exist
   (D-07). Suggest revisiting at M5, when the review queue makes the panel a daily tool.
4. **Host `pg_dump` version mismatch** (D-20) will block backup work until the operator installs a
   PostgreSQL 16 client.
5. The plan's §23 open questions (STEP DOCX source, staging InjazEdu, textbook count, question reuse)
   all bear on M2–M8 and **none block M0**.
