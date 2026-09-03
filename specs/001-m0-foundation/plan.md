# Implementation Plan: M0 — Local AI Service Foundation

**Branch**: `001-m0-foundation` *(operator-created — Constitution IV)* | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-m0-foundation/spec.md`
**Source plan**: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md` (M0 row, §16.2, §16.4, §16.6, §19, §22)

## Summary

M0 stands up the local runtime the whole project is built on: a container stack the operator
starts with one command, a health check that names the state of every component, a migration
tool that solely owns the database schema, a background worker proven end-to-end, an
authenticated control panel, and a quality gate that runs offline with a hard guard against
touching any non-test database.

The technical approach is deliberately narrow. Six services (five started by default) on a
private Docker network; **PostgreSQL 16 + pgvector** as the only data store; **Redis** as the
broker; **FastAPI** serving HTTP and **Dramatiq** consuming work as two entrypoints into one
Python package; **Laravel 12 + Filament 5** as the human panel, connected with a database
identity that has no DDL rights. **Alembic owns the schema** — including the single `users`
table the panel authenticates against — and runs from a separate one-shot container so neither
the API nor the worker ever holds migrator credentials. Ollama stays native on the host and is
an *informational* dependency in M0: nothing here calls a model.

Two facts measured on this machine change what M0 must do: Docker Desktop is still allocated
**8 GB** (must drop to 5 GB) and **none** of the four Ollama environment variables are set.
Both are operator prerequisites with verification commands, not code.

## Technical Context

**Language/Version**: Python 3.12 (pinned via `.python-version`, provisioned by `uv`; host currently has only 3.13 — see research D-01) · PHP 8.2.27 (host, verified)
**Primary Dependencies**: FastAPI + Uvicorn · Dramatiq[redis] · SQLAlchemy 2.0 (async) + psycopg 3 · Alembic · pydantic-settings · Laravel 12 + Filament 5 · Redis 7 · PostgreSQL 16 + pgvector
**Storage**: PostgreSQL 16 with the `vector` extension, one Docker volume. M0 creates exactly one table (`users`) plus Alembic's own version table.
**Testing**: pytest + pytest-asyncio (Python, offline, no model) · Pest/PHPUnit (one authorization feature test) · ruff + mypy (strict on `domain/` and `application/`)
**Target Platform**: macOS 26.6 on Apple Silicon (M1 Pro, 16 GB), local-only, no inbound network
**Project Type**: Multi-service local application — Python service (API + worker) + PHP control panel + infrastructure
**Performance Goals**: health check answers < 2 s with concurrent probes · warm start to fully healthy < 90 s · diagnostic task observable within 10 s · full quality gate < 3 min
**Constraints**: container stack ≤ 5 GB total, ≥ 6 GB system memory left free for the host model runtime · every test offline and model-free · test database name must contain `_test` or the run aborts · zero writes inside `injazedu/`
**Scale/Scope**: one operator, one machine, 6 compose services (5 default + 1 profiled), 1 database table, ~15 focused tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution's Development Workflow requires every plan to answer five questions.

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested — these are contracts, safety mechanisms, or authorization:**

| Behavior | Why it earns a test | Covers |
|---|---|---|
| Test-database guard aborts on a non-`_test` name | This *is* the Principle II mechanism; if it silently passes, the rule is fiction | FR-028, SC-010 |
| Health aggregation: per-component status, degraded paths, model runtime never fails the overall verdict | Public contract; the operator's only diagnostic | FR-006–FR-008, SC-003 |
| Migration up → down → up; idempotent re-apply; pgvector assertion fails loudly when absent | Schema contract + data integrity | FR-010–FR-012, SC-006 |
| Control-panel and app DB identities are refused any DDL | Authorization + data integrity | FR-013, SC-005 |
| Task enqueue → execute → observe, including the failure path | Job-payload contract; every later milestone rides on it | FR-017–FR-019, SC-007 |
| Configuration fail-fast names the missing variable | Startup contract; a silent default here is a production-shaped bug | FR-005 |
| Unauthenticated panel request is refused, not served | Security | FR-023 |

**Explicitly exempt under Principle I — no tests written:**
Dockerfile and compose wiring · directory scaffolding · Laravel and Filament framework behavior
(routing, Blade, panel rendering) · log formatting · `Makefile` target plumbing · the `.env.example`
file contents. These are simple wiring or framework behavior, re-tested by nobody's benefit.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

**Yes.** The migration tests, the role-privilege tests, and the one Laravel feature test are
database-backed. Wiring:

- Python: `TEST_DATABASE_URL` in `.env.testing`, read only by `tests/conftest.py`. Database name
  `injaz_ai_test`.
- PHP: `apps/ai-control/.env.testing`, same `injaz_ai_test` database.
- A session-scoped autouse fixture runs **before any test** and calls `pytest.exit()` unless the
  resolved database name contains `_test` **and** differs from `DATABASE_URL`.
- `DB::prohibitDestructiveCommands()` is enabled in the Laravel app for every non-testing
  environment, blocking `migrate:fresh`, `migrate:refresh`, `migrate:reset`, and `db:wipe`.
- Neither test suite drops or recreates any database other than `injaz_ai_test`.
- No test in M0 can reach an imported or mirrored dataset: none is configured in this repository,
  and the guard rejects any URL whose database name lacks the marker.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** M0 creates, modifies, and deletes nothing inside `injazedu/`, and reads nothing from it —
the milestone has no InjazEdu integration. `injazedu/` is already listed in `.gitignore`.
**Operator/InjazEdu-team work in M0: none.** The first InjazEdu-side work arrives at M6.

### 4. Are there Git actions in the task list? (Principle IV)

**Yes, and every one of them is an operator step, not an agent step:**

- Creating the `001-m0-foundation` branch — operator (`git checkout -b 001-m0-foundation`).
- The `before_plan` / `after_plan` auto-commit hooks in `.specify/extensions.yml` — surfaced by
  the agent, executed only by the operator.
- Committing M0's implementation — operator.

The agent will inspect Git state (`status`, `diff`, `log`) and nothing more.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

**Yes.** Every design element below maps to a numbered requirement in `spec.md`, which in turn
maps to the M0 row of the approved plan's milestone table. Three boundary calls worth naming:

- The **first migration creates one table only** (`users`). The plan's §8 domain schema belongs to
  the milestones that consume it.
- **No model call anywhere.** The Model Gateway, `model_profiles`, and provider code are M1.
- **n8n is present in compose but excluded from the default start** (`profiles`), per §16.6.

Out-of-scope observations found while planning are recorded in `research.md` as notes, not built.

**GATE RESULT: PASS.** No violations. See Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-m0-foundation/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 — 22 decisions with rationale and rejected alternatives
├── data-model.md        # Phase 1 — the one table, the roles, the Redis keyspace
├── quickstart.md        # Phase 1 — operator prerequisites + first-run walkthrough
├── contracts/
│   ├── openapi.yaml     # HTTP surface: health, liveness, diagnostics
│   ├── database-roles.md# Role/privilege contract (who may do DDL)
│   ├── environment.md   # Required environment variables and failure behavior
│   └── make-targets.md  # Operator command surface
└── checklists/
    └── requirements.md  # Spec quality checklist (from /speckit-specify)
```

### Source Code (repository root)

```text
injazedu-local-ai/
├── Makefile                        # up, down, health, migrate, seed-admin, check, mem-report, ollama-env
├── .env.example                    # documented, no real values
├── .env.testing.example
├── .gitignore                      # extended: .env*, __pycache__, .venv, vendor/, node_modules/
├── apps/
│   ├── ai-api/                     # one Python package, two entrypoints (API + worker)
│   │   ├── pyproject.toml          # uv-managed; ruff + mypy + pytest config
│   │   ├── .python-version         # 3.12
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   │       └── 0001_baseline.py        # asserts vector ext; creates users
│   │   ├── app/
│   │   │   ├── main.py                     # FastAPI entrypoint
│   │   │   ├── api/v1/
│   │   │   │   ├── health.py
│   │   │   │   └── diagnostics.py
│   │   │   ├── domain/                     # (skeleton + README; populated from M2)
│   │   │   ├── application/
│   │   │   │   └── health_service.py       # concurrent component probes
│   │   │   ├── providers/                  # (skeleton + README; populated at M1)
│   │   │   ├── infrastructure/
│   │   │   │   ├── config.py               # pydantic-settings, fail-fast
│   │   │   │   ├── db.py                   # async engine/session
│   │   │   │   ├── redis.py
│   │   │   │   ├── queue.py                # Dramatiq broker + heartbeat middleware
│   │   │   │   └── logging.py              # stdlib JSON formatter, zero new deps
│   │   │   ├── workers/
│   │   │   │   ├── main.py                 # Dramatiq entrypoint
│   │   │   │   └── tasks/diagnostics.py    # ping / failing-ping actors
│   │   │   └── prompts/                    # (skeleton + README; populated at M1)
│   │   └── tests/
│   │       ├── conftest.py                 # the _test guard
│   │       ├── unit/                       # config fail-fast, guard, health aggregation
│   │       └── integration/                # migrations, DB roles, task round-trip
│   └── ai-control/                 # Laravel 12 + Filament 5
│       ├── Dockerfile              # node build stage → php:8.2-cli runtime
│       ├── .env.testing.example
│       ├── app/Models/User.php     # implements FilamentUser::canAccessPanel
│       ├── app/Providers/AppServiceProvider.php   # DB::prohibitDestructiveCommands()
│       ├── database/migrations/    # intentionally EMPTY — Alembic owns the schema
│       └── tests/Feature/PanelAccessTest.php
├── infra/
│   ├── docker-compose.yml          # 5 default services + n8n behind a profile
│   └── postgres/initdb/
│       ├── 00-extensions.sql       # CREATE EXTENSION vector (superuser, first boot)
│       ├── 01-roles.sql            # migrator / app / control roles + default privileges
│       └── 02-test-database.sql    # injaz_ai_test
├── scripts/
│   ├── check_ollama_env.sh         # reports the four required variables
│   └── mem_report.sh               # docker stats against the 5 GB budget
└── docs/
    └── runbooks/m0-foundation.md   # start/stop/health/limitations
```

**Structure Decision**: The layout is the approved plan's §19 tree, created in full for the
directories M0 touches and as `README`-only skeletons for `domain/`, `providers/`, and `prompts/`
so that M1–M13 add files without relocating anything (FR-031). `apps/ai-api` is deliberately one
Python package with two entrypoints (`app.main` for HTTP, `app.workers.main` for Dramatiq) rather
than two packages: they share configuration, database, and logging, and splitting them would
duplicate all three. `infra/` holds everything an operator runs; `apps/ai-control/database/migrations/`
is kept empty on purpose and documented, because an empty directory is the visible reminder that
Alembic — not Laravel — owns this schema.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

**No violations.** All five gate questions pass without exception, so this table is empty.

Two choices that *look* like added complexity, recorded here because a reviewer will ask:

| Choice | Why it is not gratuitous |
|---|---|
| A separate one-shot `migrate` container with its own credentials | It is what makes FR-013 real: the API and worker images never receive the migrator password, so "the panel cannot do DDL" is enforced by the database, not by convention. The simpler alternative — one shared superuser DSN — would make the privilege tests meaningless. |
| A worker heartbeat written to Redis | Dramatiq exposes no liveness signal, and FR-006 requires the health check to name the worker's status. Redis is already required, so this adds a key, not a dependency. |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 (research.md, data-model.md, contracts/, quickstart.md). Required by the
constitution's Compliance clause.*

**RESULT: PASS — unchanged.** The design introduced no violation, and two decisions made a gate
*stronger* than the pre-design plan promised:

| Gate | Pre-design | After design | Change |
|---|---|---|---|
| I — Risk-proportional testing | 7 tested behaviors, exemptions named | Unchanged, plus D-21 makes the `_test` guard's predicate independently unit-testable | Strengthened |
| II — Test DB isolation | `_test` marker + testing environment | Plus a session abort *before collection*, a local-host check, a `DATABASE_URL` inequality check, and `DB::prohibitDestructiveCommands()` on the PHP side | Strengthened |
| III — `injazedu/` read-only | No writes | Confirmed: M0 neither reads nor writes it; `git status` shows no change under `injazedu/` | Unchanged |
| IV — Git operator-owned | Branch + commits are operator steps | Unchanged; no artifact or command in this plan performs a Git action | Unchanged |
| V — Approved scope | Traceable to the M0 row | D-06 (one table), D-10 (Redis, not a jobs table), and D-11 (no semaphores — those are M1) each *declined* to build something the plan describes for a later milestone | Strengthened |

**Two things a reviewer should look at deliberately:**

1. **D-13 is a deviation from the approved plan's wording.** The plan says "Laravel 11 + Filament";
   the design specifies **Laravel 12 + Filament 5**, because Filament 5 requires Laravel ≥ 11.28 and
   the host's PHP 8.2.27 supports both. No architecture, data flow, or gate changes. It is the
   operator's call, and reverting to Laravel 11 moves nothing else.
2. **The approved plan's §18 nightly encrypted backup has no milestone.** It is out of M0's scope
   and stays unbuilt, but the textbooks are irreplaceable and the host `pg_dump` is currently the
   wrong major version (D-20). Recorded in research.md §7 as a follow-up, not implemented.

## Requirement → Design Traceability

| Spec requirements | Where the design answers them |
|---|---|
| FR-001…FR-005 (lifecycle, config) | `infra/docker-compose.yml`, `contracts/make-targets.md`, `contracts/environment.md`, D-14, D-19 |
| FR-006…FR-009 (health, logging) | `contracts/openapi.yaml`, D-08, D-09 |
| FR-010…FR-015 (schema ownership) | `data-model.md`, `contracts/database-roles.md`, D-02, D-03, D-04, D-05, D-06 |
| FR-016…FR-020 (background work) | `contracts/openapi.yaml` `/v1/diagnostics/*`, D-09, D-10, D-11 |
| FR-021…FR-024 (control panel) | D-07, D-13, D-14, D-15; `users` table in `data-model.md` |
| FR-025…FR-030 (quality gate, test safety) | D-21, D-22, `contracts/environment.md` test section, `contracts/make-targets.md` |
| FR-031…FR-034 (repo, boundaries, docs) | Project Structure above, D-14 (`.gitignore`), `quickstart.md`, `docs/runbooks/m0-foundation.md` |

Every FR is claimed by at least one design artifact; no design artifact exists without an FR.

## Phase Status

- [x] Phase 0 — research complete (22 decisions, 0 unresolved NEEDS CLARIFICATION)
- [x] Phase 1 — data model, 4 contracts, quickstart, agent context updated
- [x] Constitution Check — pre-design PASS, post-design PASS
- [ ] Phase 2 — task breakdown (`/speckit-tasks`, not produced by this command)
