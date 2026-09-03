# Phase 1 Data Model: M0 — Local AI Service Foundation

**Date**: 2026-09-02 · **Plan**: [plan.md](./plan.md) · **Spec**: [spec.md](./spec.md)

M0's data model is intentionally tiny: **one table**. The plan's §8 domain schema (documents,
chunks, embeddings, book questions, drafts, jobs, model profiles, prompts) is created by the
milestones that read it — see FR-015 and research D-06.

---

## 1. Relational schema (PostgreSQL 16 + pgvector, owned by Alembic)

### `alembic_version` — schema version record

Created and maintained by Alembic itself. It is the stored answer to "what structural state is this
database in?" and the thing that makes rollback unambiguous.

| Column | Type | Notes |
|---|---|---|
| `version_num` | `varchar(32)` PK | The current head revision |

**Rules**
- Only the `ai_migrator` identity may write it.
- Applying migrations against an already-current database is a no-op (FR-012).
- `downgrade()` of the baseline revision is implemented and exercised by a test (SC-006).

### `users` — Control Center account

The panel's authentication store, shaped so Laravel's and Filament's conventions work unmodified
while **Alembic** — not `php artisan migrate` — creates it.

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | `bigserial` | PK | Identity |
| `name` | `varchar(255)` | NOT NULL | Display name in the panel |
| `email` | `varchar(255)` | NOT NULL, UNIQUE | Sign-in identifier |
| `email_verified_at` | `timestamptz` | NULL | Laravel convention; unused in M0 |
| `password` | `varchar(255)` | NOT NULL | Bcrypt hash. Never a plaintext value, never a default |
| `is_panel_operator` | `boolean` | NOT NULL DEFAULT true | Read by `canAccessPanel()` (research D-14) |
| `remember_token` | `varchar(100)` | NULL | Laravel "remember me" |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() | |

**Validation rules** (enforced at the creation command, not by the database alone)
- `email` must be a syntactically valid address and unique — a duplicate is a clear error, not a crash.
- `password` is supplied through the environment or an interactive prompt and is stored only as a
  bcrypt hash. **No default or hard-coded credential ships in any file** (FR-022, FR-033).
- Creating an account is idempotent by email: re-running the command updates the existing account's
  password rather than failing halfway.

**Deliberately absent in M0** (research D-07): `sessions`, `cache`, `jobs`, `password_reset_tokens`,
`notifications`. The panel runs with file-backed sessions and cache and a synchronous queue, so none
are needed. Consequence: no in-app password reset and no database notifications until a later
milestone adds them. Documented in the runbook as a known limitation.

**No state machine.** A `users` row has no lifecycle in M0 beyond existing; `is_panel_operator` is a
flag, not a status. The plan's role model (moderator vs. trainer) arrives with the review queue at M5.

---

## 2. Database identities and privileges

The privilege model *is* part of the data model here, because FR-013 is enforced by PostgreSQL
rather than by application code. Full statements live in
[`contracts/database-roles.md`](./contracts/database-roles.md).

| Identity | Holder | May do DDL | Granted |
|---|---|---|---|
| `ai_migrator` | the one-shot `migrate` container only | **yes** | Owns every object; `ALTER DEFAULT PRIVILEGES` propagates DML rights to the others |
| `ai_app` | `ai-api`, `ai-worker` | no | `SELECT, INSERT, UPDATE, DELETE` on tables; `USAGE, SELECT` on sequences |
| `ai_control` | Filament panel | no | Same as `ai_app` |

`CREATE ON SCHEMA public` is revoked from `PUBLIC` explicitly, so the guarantee does not rest on a
PostgreSQL version default. **Verification**: an integration test connects as `ai_control`, issues
`CREATE TABLE`, and asserts the server refuses it (SC-005).

---

## 3. Databases

| Database | Purpose | Created by |
|---|---|---|
| `injaz_ai` | The working database | Postgres image entrypoint (`POSTGRES_DB`) |
| `injaz_ai_test` | The disposable test database — **note the `_test` marker** | `infra/postgres/initdb/02-test-database.sql` |

`injaz_ai_test` is reproducible from migrations plus fixtures with no manual step (FR-029), and is
the **only** database any test may touch. The guard in `tests/conftest.py` aborts the run before
collection finishes if the resolved test URL names anything else (FR-028, SC-010).

---

## 4. Redis keyspace (ephemeral state — no tables)

M0 keeps its two pieces of runtime state in Redis so that the milestone genuinely creates one table.

| Key | Written by | TTL | Shape | Serves |
|---|---|---|---|---|
| `ai:worker:heartbeat:{host}:{pid}` | worker heartbeat middleware, every 5 s | 15 s | `{"pid", "host", "ts"}` | Worker component of the health check (FR-006) |
| `ai:diag:{nonce}` | the `ping` actor | 300 s | `{"status": "completed"\|"failed", "result"?, "error_type"?, "error_message"?, "finished_at"}` | Task-outcome observability (FR-017, FR-018) |
| Dramatiq's own queue keys | Dramatiq | — | internal | Enqueue/consume; treated as private to the library |

A heartbeat key that expires *is* the signal that a worker died — nothing has to clean up after it.
A `ai:diag:{nonce}` key that never appears means the task is still `pending`; the API reports exactly
that rather than guessing.

---

## 5. Entity mapping back to the spec

| Spec entity | Where it lives in M0 |
|---|---|
| Environment configuration | `.env` (gitignored) validated by `infrastructure/config.py`; contract in [`contracts/environment.md`](./contracts/environment.md) |
| Schema version record | `alembic_version` table |
| Control Center account | `users` table |
| Health report | Response body of `GET /health` — [`contracts/openapi.yaml`](./contracts/openapi.yaml). Computed, never stored |
| Background task record | `ai:diag:{nonce}` in Redis, surfaced by `GET /v1/diagnostics/ping/{nonce}` |
