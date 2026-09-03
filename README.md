# InjazEdu Local AI

A local-first AI service for InjazEdu: a Python API + worker (FastAPI/Dramatiq) and a Laravel/Filament
control panel, backed by Postgres (pgvector) and Redis, all run via Docker Compose on a single
operator's machine. `injazedu/` (the existing LMS) is read-only — this project never writes to it.

This milestone (**M0 — Local AI Service Foundation**) ships no AI yet: just the environment, health
checks, database ownership, background job processing, and panel sign-in. See
[`specs/001-m0-foundation/spec.md`](specs/001-m0-foundation/spec.md) for the full requirements and
[`docs/runbooks/m0-foundation.md`](docs/runbooks/m0-foundation.md) for day-to-day operation.

## Prerequisites

| Prerequisite | Required |
|---|---|
| Docker Desktop | running, memory ≤ 5 GB (Settings → Resources → Memory) |
| Ollama | running natively (not in Docker), reachable on `:11434` |
| Ollama env vars | `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_FLASH_ATTENTION=1` — set via `launchctl setenv`, then relaunch Ollama |
| `uv` | any recent version |
| PHP | ≥ 8.2 |
| Python | 3.12 (`uv python install 3.12`) |

Run `make doctor` to check all of the above.

## Run it

```bash
cp .env.example .env        # fill in every CHANGE_ME... placeholder (5 passwords)
make doctor                  # must be all green
make up                      # starts postgres, redis, ai-api, ai-worker, ai-control
make migrate                 # Alembic → head
make seed-admin               # creates your panel account from ADMIN_EMAIL / ADMIN_PASSWORD
make health                  # confirm all four components report "ok"
```

Panel: <http://localhost:8080/admin> · API: <http://localhost:8000>

Full first-time walkthrough: [`specs/001-m0-foundation/quickstart.md`](specs/001-m0-foundation/quickstart.md).

## Important commands

| Command | Effect |
|---|---|
| `make up` / `make down` | Start the stack / stop it, keeping data |
| `make down-hard` | Stop and **delete** the database volume (prompts first) |
| `make health` | Pretty-printed `GET /health` — four components: database, broker, worker, model_runtime |
| `make migrate` / `make migrate-down` | Alembic to head / back one revision |
| `make seed-admin` | Create or reset the panel operator account |
| `make psql` | `psql` inside the postgres container (host client is v14 vs server v16) |
| `make check` | Quality gate: ruff, mypy, pytest, PHP tests, secret scan — offline, under 3 min |
| `make mem-report` | Container memory usage vs. the 5 GB budget |
| `make logs` | Tail all service logs |

See [`docs/runbooks/m0-foundation.md`](docs/runbooks/m0-foundation.md) for the complete command
reference, the standalone scripts, and known limitations.
