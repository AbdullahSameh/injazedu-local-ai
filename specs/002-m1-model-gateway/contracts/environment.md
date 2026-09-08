# Contract: Environment Configuration — M1 delta

**Serves**: FR-015, FR-035, FR-036, FR-039, FR-049 · **Rationale**: research
[D-31](../research.md), [D-32](../research.md), [D-33](../research.md), [D-37](../research.md),
[D-38](../research.md)

This is a **delta on M0's** [`environment.md`](../../001-m0-foundation/contracts/environment.md).
Every M0 variable still applies unchanged. The same rules hold: `.env` is gitignored, `.env.example`
is committed with placeholders only, and a missing or invalid required value exits the process
naming the variable (M0 FR-005).

M1 adds **no required variable.** Every new setting has a default that is correct for this machine,
so an operator who pulls M1 and runs `make up` gets a working gateway with no `.env` edit.

---

## New optional variables, with documented defaults

| Variable | Default | Notes |
|---|---|---|
| `GATEWAY_CALL_TIMEOUT_S` | `180` | Per-call deadline covering **all** retries and the lane wait — a bound on the caller's total wait, not on each attempt (D-31) |
| `GATEWAY_MAX_RETRIES` | `2` | 3 attempts total. Retryable errors only; a caller's own mistake is never retried (FR-032) |
| `GATEWAY_RETRY_BASE_S` | `0.5` | Backoff `0.5 · 2ⁿ` with full jitter |
| `GATEWAY_BREAKER_THRESHOLD` | `5` | Consecutive retryable failures before the breaker opens (§16.4) |
| `GATEWAY_BREAKER_OPEN_S` | `30` | How long it stays open before one half-open trial call |
| `GATEWAY_LANE_LEASE_TTL_S` | `30` | Lease lifetime; a process killed mid-call frees its lane within this window (D-33, FR-034) |
| `GATEWAY_LANE_RENEW_S` | `10` | Watchdog renewal interval. **Must be < `GATEWAY_LANE_LEASE_TTL_S`** or a long call loses its own lane — validated at startup, in the style of M0's heartbeat check |
| `GATEWAY_PROFILE_CACHE_TTL_S` | `30` | How long an activated profile takes to take effect (D-37). SC-014 requires under 60 s |
| `GATEWAY_CAPTURE_PAYLOADS` | `false` | ⚠ When true, full prompt and response text is written to `model_runs`. **Prompts contain copyrighted textbook content** (§18.6) — debug only, and its state is echoed in `GET /health` (FR-039) |

## Model credentials (FR-015, D-38)

`model_profiles.api_key_env` stores a **variable name**, never a value. The provider resolves it from
the process environment at call time.

- The local runtime needs no credential; the seeded Ollama profiles leave `api_key_env` null.
- A future vLLM profile would set `api_key_env = "VLLM_API_KEY"`, and `VLLM_API_KEY` would be added
  to `.env` — never to the database, never to `.env.example` with a real value.
- A profile naming a variable that is not set fails with `ProviderAuthError` naming **the variable**,
  not the key.

This is what keeps FR-044 trivially true: the Control Center edits a variable *name*, so no secret
exists in the panel, in the database, or in a `pg_dump`.

## Validation added at startup

Joining M0's heartbeat-interval check in `infrastructure/config.py`:

| Rule | Why |
|---|---|
| `GATEWAY_LANE_RENEW_S < GATEWAY_LANE_LEASE_TTL_S` | Otherwise the watchdog renews too late and a call loses its own lane mid-flight |
| `GATEWAY_CALL_TIMEOUT_S > 0`, `GATEWAY_MAX_RETRIES >= 0` | A zero deadline would fail every call at the boundary |

## Test environment

No change. `.env.testing` keeps M0's `TEST_DATABASE_URL` and its `_test` guard (Constitution
Principle II). M1's tests add no database beyond `injaz_ai_test` and **no test reaches a model**:
live-model tests carry `@pytest.mark.llm` and are excluded by `addopts` in `pyproject.toml`, so even a
bare `uv run pytest` stays offline (D-40, FR-026).

## Operator prerequisites (carried, unchanged)

The four Ollama variables from M0's `check_ollama_env.sh` remain **unset** on this machine, verified
this session. M1's correctness no longer depends on them — the machine-wide lane is what enforces
single-occupancy (D-33) — but they still matter:

| Variable | Expected | Why it still matters at M1 |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | Defence in depth, and stops the runtime reserving memory for parallel slots |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | The §16.6 memory budget, once a second model is pulled |
| `OLLAMA_KEEP_ALIVE` | `30m` | Avoids paying model load time on every call |
| `OLLAMA_FLASH_ATTENTION` | `1` | Throughput |
