# Tasks: M0 — Local AI Service Foundation

**Input**: Design documents from `/specs/001-m0-foundation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks ARE included. They are not optional here — the spec requires them (FR-025–FR-030)
and Constitution Principle I names the specific behaviors that earn a test. The exempt list is in
plan.md's Constitution Check: Dockerfiles, compose wiring, directory scaffolding, Laravel/Filament
framework behavior, log formatting, and Makefile plumbing get **no** tests.

**Organization**: Grouped by user story so each is independently implementable and testable.

**Branch note**: the current branch is `m0/foundation`, which Spec Kit's scripts do not recognize.
Prefix Spec Kit commands with `SPECIFY_FEATURE=001-m0-foundation`, or rename the branch to
`001-m0-foundation`. Either is fine; both are **operator** actions (Constitution IV).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1–US5, mapping to the spec's user stories
- Every task carries an exact file path

## Path Conventions

Per plan.md: `apps/ai-api/` (Python — FastAPI + Dramatiq, one package, two entrypoints),
`apps/ai-control/` (Laravel 12 + Filament 5), `infra/` (compose + postgres init), `scripts/`,
`docs/runbooks/`. All paths below are repository-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The skeleton every later phase writes into.

- [X] T001 Create the directory tree from plan.md in `apps/ai-api/app/{api/v1,domain,application,providers,infrastructure,workers,prompts}`, `apps/ai-api/tests/{unit,integration}`, `infra/postgres/initdb/`, `scripts/`, `docs/runbooks/`, each future-milestone directory (`domain/`, `providers/`, `prompts/`) holding only a `README.md` naming the milestone that fills it (FR-031)
- [X] T002 Extend `.gitignore` to cover `.env`, `.env.*`, `!.env.example`, `!.env.testing.example`, `__pycache__/`, `.venv/`, `vendor/`, `node_modules/`, `.DS_Store` — before any `.env` file exists (FR-033)
- [X] T003 [P] Create `apps/ai-api/pyproject.toml` (uv-managed; fastapi, uvicorn, dramatiq[redis], sqlalchemy 2, psycopg[binary], alembic, pydantic-settings, httpx; dev: ruff, mypy, pytest, pytest-asyncio) and `apps/ai-api/.python-version` pinned to `3.12` (research D-01, D-12)
- [X] T004 [P] Create `.env.example` and `.env.testing.example` at repo root with every variable from `contracts/environment.md`, using `CHANGE_ME…` placeholders and **no working credential** (FR-004, FR-033)
- [X] T005 [P] Create `Makefile` at repo root with the 14 target names from `contracts/make-targets.md` as stubs; later phases fill their own targets

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Configuration, logging, the database container with its identities, and — critically —
the test-database guard.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

**Why the `_test` guard lives here and not in US5**: Constitution Principle II forbids any
database-touching test from running without it, and US2, US3, and US4 all have database-touching
tests. A guard that arrives after the tests it must protect is not a guard. US5 still owns the
guard's negative-case tests and the assembled quality gate.

- [X] T006 Implement `apps/ai-api/app/infrastructure/config.py` with pydantic-settings: every required variable from `contracts/environment.md`, exiting on a missing/invalid value with a message that **names the variable** and no stack trace; validate that `WORKER_HEARTBEAT_INTERVAL_S < WORKER_HEARTBEAT_TTL_S` (FR-005)
- [X] T007 [P] Implement `apps/ai-api/app/infrastructure/logging.py` — a stdlib `logging.Formatter` emitting JSON lines to stdout, **no new dependency** (FR-009, research D-15)
- [X] T008 [P] Write `infra/postgres/initdb/00-extensions.sql` creating the `vector` extension as the image superuser on first boot (research D-03)
- [X] T009 [P] Write `infra/postgres/initdb/01-roles.sql` creating `ai_migrator`, `ai_app`, `ai_control`; `REVOKE CREATE ON SCHEMA public FROM PUBLIC`; `GRANT CREATE` to the migrator only; `ALTER DEFAULT PRIVILEGES` granting DML and sequence usage to the other two — statements verbatim from `contracts/database-roles.md` (FR-013)
- [X] T010 [P] Write `infra/postgres/initdb/02-test-database.sql` creating `injaz_ai_test` (FR-029)
- [X] T011 Create `infra/docker-compose.yml` with `postgres` (image `pgvector/pgvector:pg16`, named volume, initdb mount, `pg_isready` healthcheck, `mem_limit: 1500m`) and `redis` (`mem_limit: 384m`, `redis-cli ping` healthcheck), plus an `n8n` service carrying `profiles: ["automation"]` so `up` never starts it (FR-003, research D-16, D-19)
- [X] T012 Implement `apps/ai-api/app/infrastructure/db.py` — async SQLAlchemy 2 engine and session factory over `postgresql+psycopg://`, reading `DATABASE_URL` (the `ai_app` identity, never the migrator's) (research D-12, D-05)
- [X] T013 [P] Implement `apps/ai-api/app/infrastructure/redis.py` — client factory reading `REDIS_URL`
- [X] T014 Implement the test-database guard: a pure predicate in `apps/ai-api/app/infrastructure/test_safety.py` (name must contain `_test`, must differ from `DATABASE_URL`, host must be local) plus a session-scoped autouse fixture in `apps/ai-api/tests/conftest.py` that calls `pytest.exit()` **before collection finishes** when the predicate rejects (FR-027, FR-028, Principle II)
- [X] T015 Verify the foundation from `infra/docker-compose.yml`: `docker compose -f infra/docker-compose.yml up -d postgres redis` reports both healthy, and `SELECT extversion FROM pg_extension WHERE extname='vector'` returns a version (plan §22 M0 check)

**Checkpoint**: Database, broker, configuration, logging, and the test guard exist. User stories can begin.

---

## Phase 3: User Story 1 - Start and verify the whole local environment (Priority: P1) 🎯 MVP

**Goal**: One command starts every default service, and one health check names the state of all four
components — including reporting failures honestly instead of crashing.

**Independent Test**: From a clean checkout with only the documented prerequisites, run the start
command and call the health check; then stop one dependency at a time and confirm the report names
exactly that one. No AI model, no textbook, no InjazEdu access.

### Tests for User Story 1

- [X] T016 [P] [US1] Unit-test health aggregation in `apps/ai-api/tests/unit/test_health_aggregation.py`: overall `ok` only when all required components are ok; `down` when any required one is down; **`model_runtime` down must leave the overall verdict `ok`** (FR-006, FR-008)
- [X] T017 [P] [US1] Unit-test configuration fail-fast in `apps/ai-api/tests/unit/test_config.py`: each missing required variable produces an error naming that variable; a TTL not exceeding the heartbeat interval is rejected (FR-005)

### Implementation for User Story 1

- [X] T018 [US1] Implement `apps/ai-api/app/application/health_service.py` — runs all probes **concurrently**, caps each at 1 s, and always returns a complete four-component report (FR-007, SC-002, research D-08)
- [X] T019 [P] [US1] Implement the database probe in `apps/ai-api/app/application/probes/database.py` — connectivity plus an explicit `vector` extension check that reports `down` with the reason when the extension is absent (FR-010, spec edge case)
- [X] T020 [P] [US1] Implement the broker probe in `apps/ai-api/app/application/probes/broker.py` (Redis `PING`, version in `detail`)
- [X] T021 [P] [US1] Implement the worker probe in `apps/ai-api/app/application/probes/worker.py` — scans `ai:worker:heartbeat:*`, reports `ok` when at least one unexpired key exists and `down` with "no heartbeat within Ns" otherwise (research D-09, data-model.md §4)
- [X] T022 [P] [US1] Implement the model-runtime probe in `apps/ai-api/app/application/probes/model_runtime.py` — `GET {OLLAMA_BASE_URL}/api/version`, 1 s timeout, marked `required: false` so it never changes the overall verdict (FR-008, research D-18)
- [X] T023 [US1] Implement `apps/ai-api/app/api/v1/health.py` — `GET /health/live` (always 200, touches nothing) and `GET /health` (200 when ok, 503 otherwise, identical complete body either way), matching `contracts/openapi.yaml` exactly
- [X] T024 [US1] Implement `apps/ai-api/app/main.py` — FastAPI app, router wiring, logging setup, and configuration validation at startup so an incomplete `.env` fails before the port is bound (FR-005)
- [X] T025 [P] [US1] Implement `apps/ai-api/app/infrastructure/queue.py` — Dramatiq Redis broker plus `HeartbeatMiddleware` that starts a daemon thread on `after_process_boot` writing `ai:worker:heartbeat:{host}:{pid}` every `INTERVAL_S` with `SETEX` TTL `TTL_S` (research D-09)
- [X] T026 [P] [US1] Implement `apps/ai-api/app/workers/main.py` — the Dramatiq entrypoint, started with `--processes 2 --threads 4` per §16.4 (FR-016, FR-020, research D-11)
- [X] T027 [US1] Write `apps/ai-api/Dockerfile` — Python 3.12 base, uv-installed dependencies, one image serving both entrypoints (`app.main` and `app.workers.main`)
- [X] T028 [US1] Add `ai-api` (`mem_limit: 768m`, healthcheck on `/health/live`) and `ai-worker` (`mem_limit: 1g`) to `infra/docker-compose.yml`, both receiving only the `ai_app` credential (research D-05, D-16)
- [X] T029 [US1] Fill the `up`, `down`, `down-hard`, `logs`, `health`, and `doctor` targets in `Makefile`; `down-hard` must name the database it will destroy and prompt; `doctor` must check Docker memory ≤ 5 GB, Ollama reachability, the four Ollama variables, and `.env` completeness (FR-001, FR-002, FR-034)
- [X] T030 [P] [US1] Write `scripts/check_ollama_env.sh` — report `launchctl getenv` for the four variables, print the exact `setenv` fix for any that are unset, and **state plainly** that it reads the login session rather than the running Ollama process (research D-17; all four are currently unset)
- [X] T031 [P] [US1] Write `scripts/mem_report.sh` — `docker stats --no-stream` per service and total, compared against the 5 GB budget (SC-004)
- [X] T032 [US1] Integration-test the endpoint in `apps/ai-api/tests/integration/test_health_endpoint.py`: all four components always present; a stubbed failing required probe yields 503 with a complete body naming that component; a stubbed failing model-runtime probe yields 200 (FR-007, SC-003)

**Checkpoint**: `make up` → `make health` returns four named components. US1 is independently demonstrable.

---

## Phase 4: User Story 2 - Own the database schema safely through migrations (Priority: P2)

**Goal**: One identity — and only one — can change the schema; vector search is proven present; the
panel's identity is refused DDL by PostgreSQL itself.

**Independent Test**: Apply migrations to an empty database, confirm the vector capability, roll back
and re-apply, then attempt a schema change with the control panel's credentials and watch it fail.

### Tests for User Story 2

- [X] T033 [P] [US2] Test the migration lifecycle in `apps/ai-api/tests/integration/test_migrations.py`: empty → head; re-apply is a no-op that succeeds; head → down one → head returns the identical version with no manual repair (FR-011, FR-012, SC-006)
- [X] T034 [P] [US2] Test privileges in `apps/ai-api/tests/integration/test_db_privileges.py`: as `ai_control` and as `ai_app`, `CREATE TABLE`, `DROP TABLE users`, and `ALTER TABLE users ADD COLUMN` are all refused; `SELECT` and `UPDATE` on `users` succeed (FR-013, SC-005, `contracts/database-roles.md`)
- [X] T035 [P] [US2] Test that the baseline migration **fails loudly with a readable message** when the `vector` extension is absent, in `apps/ai-api/tests/integration/test_vector_assertion.py` — it must never silently skip (FR-010, spec edge case)

### Implementation for User Story 2

- [X] T036 [US2] Create `apps/ai-api/alembic.ini` and `apps/ai-api/alembic/env.py` — synchronous psycopg connection reading `MIGRATOR_DATABASE_URL` (research D-05, D-12)
- [X] T037 [US2] Write `apps/ai-api/alembic/versions/0001_baseline.py` — assert the `vector` extension (never create it), create `users` with the nine columns in `data-model.md` §1 including `is_panel_operator`, and implement a working `downgrade()` (FR-015, research D-03, D-06)
- [X] T038 [US2] Add the one-shot `migrate` service to `infra/docker-compose.yml` (`restart: "no"`, run via `docker compose run --rm`) as the **only** place `MIGRATOR_DATABASE_URL` is injected (FR-011, research D-05)
- [X] T039 [US2] Fill the `migrate`, `migrate-down`, and `psql` targets in `Makefile`; `psql` must exec inside the postgres container because the host client is 14 against a server 16 (research D-20)
- [X] T040 [US2] Verify by inspection that the `ai-api` and `ai-worker` service environments contain **no** migrator credential, and that `apps/ai-control/database/migrations/` is empty (FR-014)

**Checkpoint**: Schema has exactly one owner, provable by a permission error. US1 and US2 both work.

---

## Phase 5: User Story 3 - Prove background work is actually processed (Priority: P3)

**Goal**: Enqueue → a separate worker process executes → the outcome is observable, failures included.

**Independent Test**: Enqueue the diagnostic task and watch it complete; enqueue one designed to fail
and confirm the failure and its reason are recorded while the worker stays available.

### Tests for User Story 3

- [X] T041 [P] [US3] Integration-test the success round trip in `apps/ai-api/tests/integration/test_diagnostics_task.py`: enqueue, then observe `completed` with its result (FR-017, SC-007)
- [X] T042 [P] [US3] Integration-test the failure path in `apps/ai-api/tests/integration/test_diagnostics_failure.py`: the outcome is `failed` carrying `error_type` and `error_message`, and the worker processes a subsequent task successfully (FR-018)

### Implementation for User Story 3

- [X] T043 [US3] Implement `apps/ai-api/app/workers/tasks/diagnostics.py` — a `ping(nonce, should_fail)` actor with `max_retries=0` that writes `ai:diag:{nonce}` (`SETEX`, TTL 300 s) with `completed` + result, or `failed` + exception type and message, and logs either way (research D-10, data-model.md §4)
- [X] T044 [US3] Implement `apps/ai-api/app/api/v1/diagnostics.py` — `POST /v1/diagnostics/ping` returning 202 with a nonce, and `GET /v1/diagnostics/ping/{nonce}` returning `pending|completed|failed`, matching `contracts/openapi.yaml`; enqueueing must fail visibly with 503 when the broker is unreachable rather than silently dropping the task (FR-017, spec edge case)
- [X] T045 [US3] Confirm the queued-while-no-worker path in `apps/ai-api/tests/integration/test_diagnostics_pending.py`: with the worker stopped the endpoint reports `pending`, and the task executes once the worker starts (FR-019)

**Checkpoint**: The enqueue → execute → observe loop every later milestone depends on is proven.

---

## Phase 6: User Story 4 - Sign in to the AI Control Center (Priority: P4)

**Goal**: An authenticated panel shell, backed by the AI database through a DDL-less identity.

**Independent Test**: Create the initial account with the documented command, sign in, sign out, and
confirm a wrong password and an unauthenticated URL are both refused.

**Depends on**: US2 — the `users` table (and its `is_panel_operator` column) is created by T037.

### Tests for User Story 4

- [X] T046 [P] [US4] Write `apps/ai-control/tests/Feature/PanelAccessTest.php`: an unauthenticated request to `/admin` redirects to sign-in rather than being served, and an incorrect password establishes no session (FR-023)

### Implementation for User Story 4

- [X] T047 [US4] Scaffold Laravel 12 + Filament 5 in `apps/ai-control/`, with the `pgsql` connection configured for the `ai_control` identity against `injaz_ai` (research D-13)
- [X] T048 [US4] Make `apps/ai-control/app/Models/User.php` implement `Filament\Models\Contracts\FilamentUser`, with `canAccessPanel()` returning the `is_panel_operator` flag — mandatory outside local environments (FR-021, research D-14)
- [X] T049 [US4] Call `DB::prohibitDestructiveCommands()` for every non-testing environment in `apps/ai-control/app/Providers/AppServiceProvider.php`, blocking `migrate:fresh`, `migrate:refresh`, `migrate:reset`, and `db:wipe` (Principle II)
- [X] T050 [US4] Configure `SESSION_DRIVER=file`, `CACHE_STORE=file`, `QUEUE_CONNECTION=sync`, and leave `apps/ai-control/database/migrations/` empty with a `README.md` stating that Alembic owns this schema (FR-014, research D-07)
- [X] T051 [US4] Implement the `seed-admin` console command in `apps/ai-control/app/Console/Commands/SeedAdmin.php` — idempotent by email, bcrypt-hashed, reading `ADMIN_EMAIL`/`ADMIN_PASSWORD` from the environment, with **no default credential anywhere** (FR-022, FR-033)
- [X] T052 [US4] Write `apps/ai-control/Dockerfile` (a `node:22-alpine` stage building Filament's Tailwind 4 assets, then a `php:8.2-cli` runtime serving on 8080), add the `ai-control` service (`mem_limit: 640m`) to `infra/docker-compose.yml`, and fill the `seed-admin` Makefile target (research D-15)
- [X] T053 [US4] Create `apps/ai-control/.env.testing.example` pointing at `injaz_ai_test` (FR-027)
- [X] T054 [US4] Verify `apps/ai-control/config/database.php` and the `ai-control` service block in `infra/docker-compose.yml` define no MySQL connection and carry no InjazEdu credential of any kind (FR-024, architecture rule 1)

**Checkpoint**: The operator can sign in. The shell is intentionally empty — review screens are M5.

---

## Phase 7: User Story 5 - Run the quality gate against an isolated test database (Priority: P5)

**Goal**: One command lints, type-checks, and tests — offline, model-free, and structurally unable to
touch a non-test database.

**Independent Test**: Run the gate on a clean checkout with Ollama quit and confirm it passes; then
point the test configuration at a non-test database and confirm the run aborts before any test executes.

**Note**: the guard itself was built in T014 (Principle II makes it a prerequisite, not a deliverable
of the last story). This phase proves it and assembles the gate around it.

### Tests for User Story 5

- [X] T055 [P] [US5] Unit-test the guard predicate in `apps/ai-api/tests/unit/test_test_safety.py` against a table of URLs: accepted (`injaz_ai_test` on localhost) and rejected (no `_test` marker, identical to `DATABASE_URL`, non-local host) (FR-028, SC-010, research D-21)

### Implementation for User Story 5

- [X] T056 [US5] Configure ruff and mypy in `apps/ai-api/pyproject.toml`, with mypy **strict** on `app/domain/` and `app/application/` per plan §19
- [X] T057 [US5] Add a secret scan step in `scripts/scan_secrets.sh` that fails when a credential-shaped value appears in any version-controlled file (FR-033, SC-011)
- [X] T058 [US5] Fill the `check` target in `Makefile` to run ruff, mypy, pytest, the PHP feature test, and the secret scan in one command (FR-025)
- [X] T059 [US5] Fill the `test-db-reset` target in `Makefile` — recreates `injaz_ai_test` from migrations and **refuses** any database name lacking the `_test` marker (FR-029, FR-030)
- [X] T060 [US5] Verify `make check` passes with Ollama quit and no network egress, in under 3 minutes (FR-026, SC-009)
- [X] T061 [US5] Verify the abort: run `TEST_DATABASE_URL=…/injaz_ai make check` and confirm the `apps/ai-api/tests/conftest.py` guard exits the session before any test runs and before any data is modified (SC-010)

**Checkpoint**: Every milestone from here can be called done on evidence rather than assertion.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T062 [P] Write `docs/runbooks/m0-foundation.md` — prerequisites, the required Docker memory value, the Ollama settings, start/stop/health commands, and the known-limitations list from `quickstart.md` (FR-034)
- [X] T063 Run the full `quickstart.md` walkthrough end to end and correct any step that does not work exactly as written (SC-001) — fixed: raw `docker compose -f infra/docker-compose.yml ...` calls in the US1 failure-injection steps need `--env-file .env` (compose resolves its default `.env` relative to the `-f` file's directory, not the shell's cwd); all five user-story acceptance blocks reproduced successfully otherwise
- [X] T064 [P] Verify the memory budget with `make mem-report`: measured **0.27 GiB** for the running stack, well within the 5 GB container budget — Docker Desktop's own VM allocation is still 7.8 GiB on this machine, so the machine-wide "≥ 6 GB free" criterion (SC-004) still needs the operator's one-time Settings change from the quickstart prerequisites
- [X] T065 [P] Verify data survives a restart: `make down` then `make up` leaves the schema and the operator account intact (FR-002, SC-013) — confirmed
- [X] T066 [P] Verify `git status` reports **zero** changes under `injazedu/` (Principle III, FR-032, SC-012) — **FAILS today**: `git status` shows `injazedu` with modified content (`app/Models/Course.php` reindented, two `.DS_Store` files) predating this M0 work; no M0 task touches `injazedu/`, confirmed by re-checking after this session's changes. Left unresolved — deciding whether to discard or commit inside that project is an operator call (Principle IV), documented in the runbook's verification log
- [X] T067 Record M0's known limitations in the runbook: no AI, no InjazEdu integration, an empty panel shell, no password reset or in-app notifications (research D-07), host `pg_dump` version mismatch (D-20), and no backups yet (research §7)
- [ ] T068 **Operator action** (Constitution IV — not the agent's): rename the branch to `001-m0-foundation` or keep using `SPECIFY_FEATURE=…`, then commit M0

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: needs Setup — **blocks every user story**
- **US1 (Phase 3)**: needs Foundational. No dependency on any other story
- **US2 (Phase 4)**: needs Foundational. Independent of US1
- **US3 (Phase 5)**: needs Foundational, and T025/T026 from US1 for a running worker container
- **US4 (Phase 6)**: needs Foundational **and US2** — the `users` table comes from T037
- **US5 (Phase 7)**: needs Foundational; its verification tasks (T060, T061) are most meaningful once US2–US4 have contributed tests
- **Polish (Phase 8)**: needs everything

### The two real cross-story dependencies

Most stories are independent. Two are not, and pretending otherwise would produce a plan that
does not build:

1. **US4 → US2**: the panel authenticates against `users`, which the baseline migration creates.
2. **US3 → US1**: the diagnostic actors need the worker container and broker wiring from T025–T028.

Everything else can proceed in any order after Phase 2.

### Within each story

Tests are written before the implementation they cover and must fail first. Probes before the
service that aggregates them; the service before the endpoint; the endpoint before the container.

---

## Parallel Opportunities

**Phase 1**: T003, T004, T005 together (three different files).

**Phase 2**: T007, T008, T009, T010, T013 together — one logging module and four independent
infrastructure files.

**Phase 3 (US1)** — the largest parallel block in the milestone:

```bash
# Tests first, together:
Task: "Unit-test health aggregation in apps/ai-api/tests/unit/test_health_aggregation.py"
Task: "Unit-test configuration fail-fast in apps/ai-api/tests/unit/test_config.py"

# Then all four probes, one file each, no shared state:
Task: "Database probe in apps/ai-api/app/application/probes/database.py"
Task: "Broker probe in apps/ai-api/app/application/probes/broker.py"
Task: "Worker probe in apps/ai-api/app/application/probes/worker.py"
Task: "Model-runtime probe in apps/ai-api/app/application/probes/model_runtime.py"

# And the two operator scripts, independent of all of the above:
Task: "scripts/check_ollama_env.sh"
Task: "scripts/mem_report.sh"
```

**Phase 4 (US2)**: T033, T034, T035 together — three separate test files.

**Phase 5 (US3)**: T041 and T042 together.

**Phase 8**: T062, T064, T065, T066 together — documentation and four independent verifications.

---

## Implementation Strategy

### MVP (User Story 1 only)

Phase 1 → Phase 2 → Phase 3, then **stop and validate**: `make up` starts the stack and `make health`
names four components, with each dependency stopped in turn to confirm the report is honest.

That is a genuine deliverable on its own. It replaces "is anything broken?" with a definitive answer,
and it is the thing you will use every single day of M1 through M13.

### Incremental delivery after the MVP

1. **+ US2** → the schema has one owner and the panel provably cannot change it
2. **+ US3** → background work is proven, unblocking every expensive operation later
3. **+ US4** → you can sign in to the shell that M5's review queue will live in
4. **+ US5** → milestones can be called done on evidence
5. **+ Polish** → the runbook and the four verifications

### Solo-operator note

The plan's estimate for M0 is 2–3 days. The Parallel Opportunities above are written for the agent
executing independent files in one pass, not for a team — there is one of you. The sequence that
matters is the incremental one: each numbered step above leaves the environment in a working,
demonstrable state, so you can stop at any checkpoint without a half-built system.

---

## Notes

- `[P]` means a different file with no dependency on incomplete work
- Every database-touching test runs against `injaz_ai_test` and nothing else (Principle II)
- **No task writes inside `injazedu/`** (Principle III); T066 verifies it
- **No task performs a Git action**; T068 is explicitly the operator's (Principle IV)
- Every task traces to a numbered requirement in `spec.md`, which traces to the M0 row of the
  approved plan (Principle V)
- Nothing here calls a language model. If a task seems to need one, it belongs to M1
