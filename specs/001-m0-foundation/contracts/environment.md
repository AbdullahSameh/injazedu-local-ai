# Contract: Environment Configuration

**Serves**: FR-004, FR-005, FR-033 · **Rationale**: research [D-14](../research.md), [D-18](../research.md)

Every setting is read from `.env` at the repository root, which is **gitignored**. `.env.example` is
committed, documents every variable, and contains **no real value** — placeholders only.

Configuration is validated once at startup by `infrastructure/config.py`. A missing or invalid
required value makes the process **exit immediately with a message naming the variable** (FR-005) —
never a stack trace, never a silent default that works locally and surprises somebody later.

---

## Required variables

| Variable | Consumed by | Example (placeholder) | If missing |
|---|---|---|---|
| `POSTGRES_DB` | postgres | `injaz_ai` | Container refuses to start |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | postgres | `postgres` / `CHANGE_ME` | Container refuses to start |
| `AI_MIGRATOR_PASSWORD` | postgres init, `migrate` | `CHANGE_ME_MIGRATOR` | Roles not created; migrations cannot run |
| `AI_APP_PASSWORD` | postgres init, api, worker | `CHANGE_ME_APP` | Startup exits naming the variable |
| `AI_CONTROL_PASSWORD` | postgres init, control panel | `CHANGE_ME_CONTROL` | Panel cannot connect |
| `DATABASE_URL` | api, worker | `postgresql+psycopg://ai_app:…@postgres:5432/injaz_ai` | Startup exits naming the variable |
| `MIGRATOR_DATABASE_URL` | `migrate` service **only** | `postgresql+psycopg://ai_migrator:…@postgres:5432/injaz_ai` | Migrations exit naming the variable |
| `REDIS_URL` | api, worker | `redis://redis:6379/0` | Startup exits naming the variable |
| `APP_KEY` | control panel | (generated once, per Laravel) | Panel refuses to boot |

## Required for the test environment (`.env.testing`)

| Variable | Example | Rule |
|---|---|---|
| `TEST_DATABASE_URL` | `postgresql+psycopg://ai_migrator:…@localhost:5432/injaz_ai_test` | **Database name must contain `_test`**, must differ from `DATABASE_URL`, and must be a local host — otherwise the test session aborts before collection finishes (FR-028, SC-010) |

This is the mechanical form of Constitution Principle II. The predicate is a plain function with its
own unit tests covering both the accepted and the rejected shapes.

## Optional, with documented defaults

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Health probe target only. M0 makes no model call |
| `API_PORT` | `8000` | |
| `CONTROL_PORT` | `8080` | |
| `LOG_LEVEL` | `INFO` | |
| `WORKER_PROCESSES` / `WORKER_THREADS` | `2` / `4` | §16.4 caps for a 16 GB machine (FR-020) |
| `WORKER_HEARTBEAT_INTERVAL_S` / `_TTL_S` | `5` / `15` | TTL must exceed the interval, or the worker reads as down while alive — validated at startup |

## Host-level settings the operator sets outside this repository

These are not `.env` values; they belong to the machine. `make doctor` reports each and names what
is wrong.

| Setting | Required value | Status measured 2026-09-02 |
|---|---|---|
| Docker Desktop memory | **5 GB** | **7.8 GiB — must be reduced** (SC-004) |
| `OLLAMA_NUM_PARALLEL` | `1` | **unset** |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | **unset** |
| `OLLAMA_KEEP_ALIVE` | `30m` | **unset** |
| `OLLAMA_FLASH_ATTENTION` | `1` | **unset** |

Ollama reads these at launch, so they take effect only after Ollama is quit and relaunched. The
check script reads the login session's environment — it reports what a *relaunched* Ollama will
inherit, and says so, rather than claiming to have inspected the running process (research D-17).

---

## Secret handling

- `.gitignore` covers `.env`, `.env.*`, and `!.env.example` / `!.env.testing.example`.
- No committed file contains a working credential (FR-033, SC-011), verified by a scan in the
  quality gate.
- The initial panel password is supplied to the account-creation command through the environment or
  an interactive prompt and is stored only as a bcrypt hash. No default account ships.
