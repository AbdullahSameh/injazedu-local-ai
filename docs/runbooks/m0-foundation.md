# Runbook: M0 — Local AI Service Foundation

**Audience**: the operator, on this MacBook. This is the day-to-day reference once the environment
is up; for the first-time walkthrough see
[`specs/001-m0-foundation/quickstart.md`](../../specs/001-m0-foundation/quickstart.md).

Nothing here calls a language model. If you are looking for the AI, it starts at M1.

---

## Prerequisites

| Prerequisite | Required | Action |
|---|---|---|
| Docker Desktop | running, **memory ≤ 5 GB** | Settings → Resources → Memory → 5 GB → Apply & Restart |
| Ollama | running natively (not in Docker), reachable on `:11434` | — |
| Ollama environment | 4 variables set (see below) | `launchctl setenv`, then quit and relaunch Ollama |
| `uv` | any recent version | — |
| PHP | ≥ 8.2 | — |
| Python | 3.12 for the local gate | `uv python install 3.12` |

**Why Docker's memory matters**: the budget is Ollama ~6.5 GB + containers ≤5 GB + macOS ~4 GB on a
16 GB machine. Leaving Docker at its default (7.8 GiB on this machine) risks swapping the whole
machine to a halt once an 8B model loads at M5+.

### Ollama environment variables

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_FLASH_ATTENTION 1
# then quit Ollama from the menu bar and relaunch it — it reads these only at launch
```

`make doctor` reports these, but honestly: it reads the *login session's* environment, which is
what a freshly relaunched Ollama inherits. It cannot inspect an already-running process, so a
green check without a relaunch is misleading.

---

## Commands

| Command | Effect |
|---|---|
| `make doctor` | Checks `.env` completeness, Docker memory, Ollama reachability and env vars (FR-034) |
| `make up` | Starts `postgres`, `redis`, `ai-api`, `ai-worker`, `ai-control`. `n8n` stays off (profile-gated) |
| `make down` | Stops everything, **keeps** the data volume |
| `make down-hard` | Stops and **deletes** the data volume — prompts, names the database first |
| `make health` | `GET /health`, pretty-printed — four named components: `database`, `broker`, `worker`, `model_runtime` |
| `make migrate` / `make migrate-down` | Alembic to head / back one revision, via the one-shot `migrate` container |
| `make seed-admin` | Creates or updates the panel account from `ADMIN_EMAIL` / `ADMIN_PASSWORD` (idempotent by email) |
| `make psql` | Opens `psql` **inside** the postgres container — the host client is version 14 against a server 16 |
| `make check` | Quality gate: ruff, mypy, pytest, the PHP feature test, a secret scan — offline, under 3 minutes |
| `make test-db-reset` | Recreates `injaz_ai_test` from migrations; refuses any name lacking `_test` |
| `make mem-report` | `docker stats` per service and total, against the 5 GB budget |
| `make logs` | Tails all service logs |
| `make automation-up` | Starts `n8n` deliberately (off by default) |

A raw `docker compose -f infra/docker-compose.yml ...` call needs `--env-file .env` added
explicitly — compose resolves its default `.env` search relative to the `-f` file's directory
(`infra/`), not your shell's working directory, so omitting the flag silently blanks every
variable. The Makefile's `$(COMPOSE)` already includes it; only add it yourself when you drop to a
raw `docker compose` command, as the quickstart's manual failure-injection steps do.

---

## Scripts (`scripts/`)

Most of these back a `make` target directly rather than being run standalone.

| Script | Called by | Does |
|---|---|---|
| `check.sh` | `make check` | Runs ruff, mypy, pytest, the PHP feature test, and the secret scan in sequence; stops at the first failure |
| `check_ollama_env.sh` | `make doctor` | Reports the 4 Ollama `launchctl` variables and prints the exact `setenv` fix for any unset one |
| `mem_report.sh` | `make mem-report` | `docker stats` per running service plus total, against the 5 GB budget; errors if nothing is running |
| `scan_secrets.sh` | `make check` | Scans git-tracked files for credential-shaped values (`.env` itself is gitignored, so this catches an accidental force-add or a pasted secret) |
| `test_db_reset.sh` | `make test-db-reset` | Recreates `injaz_ai_test` from migrations; refuses to run against any database name lacking `_test` |

`check.sh` and `test_db_reset.sh` read connection variables from `.env`/`.env.testing` but let an
already-exported value win — that's what lets `TEST_DATABASE_URL=... make check` prove the
`_test` guard aborts (SC-010).

---

## Known limitations of M0 — by design, not oversight

- **No AI.** No model call, no prompt, no textbook, no retrieval. M1 onward.
- **No InjazEdu integration.** Nothing reads or writes InjazEdu, and `injazedu/` is untouched by any
  M0 task.
- **The panel is an empty authenticated shell.** Review screens are M5.
- **No password-reset or in-app notification flow.** Those Laravel tables (`sessions` beyond the
  file driver, `password_reset_tokens`, `notifications`) are deliberately not created — every
  Laravel-owned table is a second thing Alembic would have to mirror by hand. Use `make seed-admin`
  to reset your own password (research D-07).
- **Your host `psql`/`pg_dump` is 14.18 against a server 16.** Use `make psql` for interactive
  access. Host `pg_dump` will refuse the version mismatch outright; install a PostgreSQL 16 client
  before backup work begins (research D-20).
- **No backups yet.** The plan's §18 nightly encrypted dump has no milestone assigned. Worth fixing
  before the corpus is large (research §7).
- **Local only.** Everything binds to localhost; no inbound access, no TLS — nothing needs to reach
  this machine.

---

## Verification log — 2026-09-03

Results of running the M0 acceptance walkthrough end to end against this checkout, informing the
state above:

- **US1** (`make up` → `make health`): all four components report `ok`. Stopping `postgres` yields
  `503` with `database: down` and the other three still reported; restarting it returns to `ok`.
  Quitting Ollama was not exercised live in this pass (would disrupt the operator's running
  session) — the probe code and its unit tests (`test_health_aggregation.py`) already assert
  `model_runtime: down` never changes the overall verdict.
- **US2** (migrate lifecycle + privileges): `make migrate` is a no-op on a current head;
  `make migrate-down` then `make migrate` returns to the identical revision with no manual repair.
  As `ai_control`, `CREATE TABLE` and `DROP TABLE users` are both refused by PostgreSQL; `SELECT`
  succeeds.
- **US3** (diagnostics): a normal ping completes with `"result":"pong"`; a `should_fail` ping
  records `"status":"failed"` with `error_type`/`error_message`, and the worker's next heartbeat
  still reads `ok`.
- **US4** (panel sign-in): `make seed-admin` created the operator account from `.env`. Sign-in
  gating is covered by `PanelAccessTest.php` in `make check`; not re-driven through a browser in
  this pass.
- **US5** (quality gate): `make check` passed — ruff, mypy (strict on `domain/`/`application/`),
  39 pytest cases, 2 PHP assertions, and the secret scan — in **~16 seconds**, well under the 3
  minute budget (SC-009), with no test making a real network call. Pointing
  `TEST_DATABASE_URL` at `injaz_ai` (no `_test` marker) aborts the pytest session before any test
  collects, per SC-010.
- **Restart persistence** (`make down` then `make up`): the `users` table and the seeded operator
  account both survived, confirming SC-013.
- **Memory budget**: the running stack (`postgres`, `redis`, `ai-api`, `ai-worker`, `ai-control`)
  measured **0.27 GiB** total via `make mem-report` — well inside the 5 GB container budget.
  Docker Desktop's own VM allocation was still **7.8 GiB** at measurement time (the operator
  prerequisite to reduce it to 5 GB has not yet been applied on this machine) — the containers'
  own footprint does not depend on that setting, but the "≥6 GB free" success criterion (SC-004)
  needs it done to be true machine-wide.
- **`injazedu/` untouched by M0** (Principle III, FR-032): **not currently true.** `git status`
  reports `injazedu` as having modified content, pre-dating this M0 work: `app/Models/Course.php`
  has been reformatted (2-space → 4-space indentation, no logic change) and two `.DS_Store` files
  changed. No M0 task reads or writes anything under `injazedu/`, and this session did not either —
  the dirty state was already present in the working tree. Resolving it (discard vs. commit inside
  that project) is a decision for the operator, per Constitution Principle IV.
