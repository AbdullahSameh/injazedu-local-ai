# Contract: Database Identities and Privileges

**Serves**: FR-013, FR-014, SC-005 · **Rationale**: research [D-04](../research.md), [D-05](../research.md)

FR-013 says the control panel "CANNOT create, alter, or drop schema objects." In M0 that is a
**PostgreSQL privilege**, not a coding convention — which is what makes it testable and what makes
it survive somebody typing `php artisan migrate` at 1 a.m.

---

## The three identities

| Identity | Credential lives in | Holder | DDL |
|---|---|---|---|
| `ai_migrator` | `MIGRATOR_DATABASE_URL`, injected **only** into the one-shot `migrate` service | Alembic | **yes** — owns every object |
| `ai_app` | `DATABASE_URL` in `ai-api` and `ai-worker` | FastAPI, Dramatiq | no |
| `ai_control` | `DB_*` in `ai-control` | Laravel / Filament | no |

The API and worker images never receive the migrator password. That is the point: the privilege
boundary is enforced by what each container is given, not by what its code chooses to do.

---

## Init SQL (runs once, as the image superuser, on first boot)

`infra/postgres/initdb/01-roles.sql`:

```sql
-- Identities. Passwords come from the environment; none is hard-coded in this file.
CREATE ROLE ai_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE ai_app      LOGIN PASSWORD :'app_password';
CREATE ROLE ai_control  LOGIN PASSWORD :'control_password';

-- Nobody but the migrator may create objects. PostgreSQL 15+ already revokes this from PUBLIC;
-- stating it explicitly means the guarantee does not depend on a version default.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  USAGE  ON SCHEMA public TO ai_app, ai_control;
GRANT  CREATE ON SCHEMA public TO ai_migrator;

-- Objects the migrator creates from now on are automatically readable/writable by the others,
-- so a future migration never needs a follow-up GRANT.
ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO ai_app, ai_control;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO ai_app, ai_control;
```

---

## The guarantees, and how each is verified

| # | Guarantee | Verification |
|---|---|---|
| 1 | `ai_control` cannot create a table | Integration test connects as `ai_control`, runs `CREATE TABLE t (id int)`, asserts `InsufficientPrivilege` |
| 2 | `ai_control` cannot drop or alter `users` | Same test, `DROP TABLE users` and `ALTER TABLE users ADD COLUMN x int` — both refused |
| 3 | `ai_app` cannot create a table | Same test, same assertion, different identity |
| 4 | `ai_control` **can** read and write `users` | `SELECT` then `UPDATE` succeed — the panel must still work |
| 5 | `ai_migrator` can do DDL | Migration tests pass, which is the same statement |
| 6 | Laravel never migrates this database | `apps/ai-control/database/migrations/` is empty, `DB::prohibitDestructiveCommands()` is on for non-testing environments, and guarantee 1 makes `migrate` fail at its first `CREATE` regardless |

Guarantee 6 is belt, braces, and a third thing on purpose: this is the failure that silently
destroys the corpus, and the constitution names it non-negotiable.

---

## Where passwords come from

Three distinct passwords, supplied via `.env` (gitignored) and passed to the init script as
psql variables. `.env.example` ships placeholder text, never a working value (FR-033).

Rotating any of them means changing `.env` and restarting the affected service. Because the roles
are separate, rotating the migrator password does not touch the running API or panel.

---

## What M0 deliberately does not do

- **No row-level security.** One operator, one panel. RLS becomes worth its complexity when the
  panel has multiple reviewer roles — that conversation belongs to M5.
- **No read-only reporting identity.** Nothing reports yet; M10's evaluation dashboards are the
  first plausible consumer.
- **No per-table grants.** `ALTER DEFAULT PRIVILEGES` covers every future table uniformly. If a
  later milestone needs a table the panel must not read, that is the moment to narrow it — and the
  moment there will be a real reason to.
