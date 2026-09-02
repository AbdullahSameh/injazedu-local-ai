# Contract: Operator Command Surface

**Serves**: FR-001, FR-002, FR-003, FR-022, FR-025, FR-034

Every command an operator needs is one `make` target run from the repository root. The names are the
contract; the implementations may change.

| Target | Does | Serves |
|---|---|---|
| `make doctor` | Checks prerequisites before anything starts: Docker running, Docker memory ≤ 5 GB, Ollama reachable, the four Ollama variables, `.env` present and complete. Reports every problem with the command that fixes it | FR-034, SC-001 |
| `make up` | Starts the five default services. **The single documented start command** | FR-001 |
| `make down` | Stops everything, keeps volumes — data survives (FR-002, SC-013) | FR-002 |
| `make down-hard` | Stops and **deletes the volume**. Prompts for confirmation, and names the database it is about to destroy | FR-002 |
| `make logs` | Tails all services' logs | FR-009 |
| `make health` | Calls `GET /health` and pretty-prints the per-component report | FR-006 |
| `make migrate` | Runs Alembic to head in the one-shot `migrate` container — the only place migrator credentials exist | FR-011 |
| `make migrate-down` | Rolls back one revision | FR-011, SC-006 |
| `make seed-admin` | Creates or updates the panel account from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Idempotent by email; no default credential | FR-022 |
| `make psql` | Opens `psql` **inside the postgres container** — the host client is 14 against a server 16 (research D-20) | FR-034 |
| `make check` | The quality gate: ruff, mypy, pytest, the PHP feature test, and a secret scan. Offline, no model | FR-025, SC-009 |
| `make test-db-reset` | Drops and recreates `injaz_ai_test` from migrations. Refuses any database whose name lacks `_test` | FR-029 |
| `make mem-report` | `docker stats` against the 5 GB budget, per service and total | SC-004 |
| `make automation-up` | Starts n8n deliberately (`--profile automation`). Not part of `make up` | FR-003 |

## Behavioral requirements on these commands

- `make up` twice is safe: the second run reports the existing environment rather than creating a
  conflicting duplicate.
- `make up` with an incomplete `.env` fails fast, naming the missing variable — it does not leave a
  half-started environment.
- `make down-hard` and `make test-db-reset` are the only destructive targets. Both name their target
  before acting, and `test-db-reset` refuses anything without the `_test` marker.
- `make check` must pass with **no AI model running and no network access** (FR-026).
