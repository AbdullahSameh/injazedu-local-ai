# Runbook: M1 — Model Gateway

**Audience**: the operator, on this MacBook. This is the day-to-day reference once the gateway is
up; for the first-time walkthrough and the full success-criteria checklist see
[`specs/002-m1-model-gateway/quickstart.md`](../../specs/002-m1-model-gateway/quickstart.md).

Builds on [`m0-foundation.md`](m0-foundation.md) — `make up` and the four M0 components still apply.
This is where the AI starts: one facade (`app/application/gateway`), two protocols
(`LLMProvider`, `EmbeddingProvider`), operator-editable model profiles, and a call accounting trail.

---

## Two measured facts that shape this milestone

1. **A truncated structured call returns HTTP 200 with empty content** (`finish_reason: "length"`).
   The gateway checks `finish_reason` before parsing anything — skip that check and the caller sees
   "invalid JSON" and debugs the wrong thing (research D-26). Reproduced live this session:
   `smoke-llm --max-output-tokens 8` raised `ModelTruncatedError`, not a parse error.
2. **Ollama does not serialise concurrent generations.** Two simultaneous calls overlapped in the
   session that measured it (research D-33). The execution lane is therefore a Redis lease,
   machine-wide across the API and both worker processes — not an in-process semaphore.

---

## Prerequisites

Same as M0, plus:

| Prerequisite | Required | Action |
|---|---|---|
| Migration `0002` applied | `model_profiles`, `model_runs` exist | `make migrate` |
| Profiles seeded | 5 rows, 2 active | `make seed-profiles` |
| The two active models pulled | `gemma4:e2b-it-qat`, `embeddinggemma:300m-qat-q4_0` | `ollama list` |

`qwen3:8b` and `bge-m3` are seeded but **inactive** and **not pulled** — activating either before
`ollama pull` produces `ModelNotAvailableError` naming the model. `make doctor`'s "Model profiles"
section catches this before the first real call does.

---

## Commands

| Command | Effect |
|---|---|
| `make doctor` | M0's checks, plus: active profiles and whether their models are actually pulled (T069) |
| `make migrate` | Alembic to head — adds `model_profiles`, `model_runs` (additive, no M0 table touched) |
| `make seed-profiles` | Idempotent roster seed — `ON CONFLICT (name) DO NOTHING`, never overwrites an operator edit |
| `make profiles` | Prints the roster: name, role, model, endpoint, dim, active state |
| `make smoke-llm` | One real structured generation + one real embedding, printing shape, tokens, latency |
| `make smoke-llm -- --max-output-tokens 8` | Forces D-26's truncation path — expect `ModelTruncatedError`, not a parse error |
| `make check-lane` | Fires simulated concurrent callers from the API-shaped and both worker-shaped processes; reports max observed in-flight (expect 1) |
| `make test-llm` | Runs only `@pytest.mark.llm` — the real-runtime tests `make check` excludes |
| `make check` | Now includes the architecture grep (SC-001, SC-005) ahead of mypy |

`app/scripts/bench_embed.py` (T072) has no Make target — run it via the same one-shot container
the targets above use:

```bash
docker compose -f infra/docker-compose.yml --env-file .env --profile tools run --rm migrate \
  python -m app.scripts.bench_embed
```

---

## Scripts (`apps/ai-api/app/scripts/`)

| Script | Called by | Does |
|---|---|---|
| `seed_profiles.py` | `make seed-profiles` | Idempotent roster insert (research D-36) |
| `print_profiles.py` | `make profiles` | Read-only roster listing (FR-049) |
| `check_profiles_pulled.py` | `make doctor` | For each **active** `ollama` profile, checks its model against `/api/tags`; the pre-flight version of the 404 a missed pull would otherwise produce mid-call (T069) |
| `smoke_llm.py` | `make smoke-llm` | One real structured generation + one real embedding through the gateway; a short reachability pre-check fails fast rather than waiting out the full deadline (T049) |
| `check_lane.py` | `make check-lane` | Empirical proof the `llm` lane admits at most one caller at a time, machine-wide (T060) |
| `bench_embed.py` | — (run directly) | SC-007: direct-call vs. through-gateway embedding throughput at batch 32, on synthetic textbook-sized passages (T072) |

The last three talk to Ollama directly (`smoke_llm.py`'s reachability pre-check,
`check_profiles_pulled.py`'s `/api/tags` listing) or need it running for a real measurement
(`bench_embed.py`) — none of them run under `make check`, and `scripts/check.sh`'s architecture
grep allowlists exactly these two files' direct `httpx` import (neither is a model or embedding
*call* — see the grep's own comment in `scripts/check.sh`).

---

## Swapping the model — the procedure this milestone exists to make boring

1. Control Center → Model Profiles → **New** (or edit an existing row): set `provider`, `base_url`
   (must end `/v1`), `model`, `role`, and `params` for the profile.
2. For a non-Ollama endpoint needing auth: add the **variable name** to `api_key_env`, and the
   actual secret as `.env`'s value under that name — the value never goes in the profile (D-38).
3. **Activate** it. The incumbent for that role deactivates in the same transaction — the database's
   partial unique index makes "two active profiles for one role" impossible, not just discouraged.
4. Within `GATEWAY_PROFILE_CACHE_TTL_S` (30 s default), the next call uses the new profile. Calls
   already in flight finish on the old one.
5. `make smoke-llm` to confirm. `git status --short` stays empty — zero code changed.

Verified this session by editing `ollama-gemma4-e2b`'s `base_url` directly (standing in for the
Control Center form, which performs the same `UPDATE`) to an unreachable port: the very next
`smoke-llm` run — a fresh process, so not even riding out the cache TTL — failed with
`ProviderUnreachableError` naming the new URL; reverting the edit made the next run succeed again.
No file changed in either direction.

---

## Known limitations of M1 (`quickstart.md` §5)

- **Vectors are produced, not stored.** No `embeddings_768` table, no index, no backfill — M4.
- **No prompts.** M1 carries no prompt text or `prompt_versions` table — M5/M7.
- **No token pre-estimate.** `usage` gives exact counts *after* a call; M4's chunker needs a
  *pre-flight* estimate, a different function added with its consumer.
- **`model_runs` is written, never read.** The §17 dashboards are M10's. It is also **not written by
  default** — see below.
- **Profile changes take up to 30 s** to take effect (D-37), and in-flight calls finish on the old
  profile.
- **The breaker is per profile, not per model.** Two profiles pointing at the same unreachable
  endpoint trip independently.
- **`qwen3:8b` and `bge-m3` are seeded but not pulled.** Activating either before `ollama pull` gives
  `ModelNotAvailableError`.
- **The four Ollama environment variables are still unset** on this machine (M0 D-17 carried
  forward). M1 is correct without them, but `OLLAMA_MAX_LOADED_MODELS=2` and
  `OLLAMA_KEEP_ALIVE=30m` matter for the memory budget once a second model is pulled.

**One more, specific to this milestone's design** — not in `quickstart.md` §5:

- **`Gateway`'s call accounting is off unless something explicitly wires an `AccountingWriter`.**
  A bare `Gateway(registry)` — what `smoke_llm.py`, `bench_embed.py`, and every earlier story's
  test construct — records nothing (`NullAccountingWriter`). This is deliberate: unlike the
  lane/breaker's live-Redis defaults, a default that opens a database session would risk a test
  or diagnostic script writing to whatever `DATABASE_URL` happens to resolve to, which the
  constitution's "no test touches a non-`_test` database" rule exists specifically to prevent.
  Confirmed this session: `SELECT count(*) FROM model_runs` on the dev database is `0` after
  several `smoke-llm` and `bench-embed` runs. SC-012's accounting guarantees are proven by
  `tests/gateway/test_accounting.py` against `injaz_ai_test`, not by querying the dev database
  out of the box — a future milestone's production wiring is what turns this on for real.

---

## Verification log — 2026-09-08

Results of running the M1 acceptance walkthrough end to end against this checkout (Ollama 0.33.3,
two models pulled: `gemma4:e2b-it-qat`, `embeddinggemma:300m-qat-q4_0`), informing the state above.

- **SC-001** (nothing bypasses the gateway): `make check`'s new architecture step passed —
  `apps/ai-api/app/` carries no `httpx`/`ollama`/`openai` import outside `app/providers/`, with two
  narrow, documented exceptions (`probes/model_runtime.py`'s liveness ping, `smoke_llm.py`'s
  reachability pre-check) that are not model or embedding calls. Confirmed the check actually
  catches a violation by temporarily appending `import httpx` to `gateway.py` and re-running it.
- **SC-002** (swap the model, zero code changed): see "Swapping the model" above — reproduced by
  editing `base_url` directly and back. `git status --short` stayed empty throughout.
- **SC-003 / SC-016** (structured output, failure taxonomy): `tests/gateway/test_structured.py` and
  `test_errors.py` pass (offline, via `FakeLLMProvider`). Live: `smoke-llm --max-output-tokens 8`
  raised `ModelTruncatedError: finish_reason='length' (expected 'stop')` — D-26 confirmed against
  the real runtime, not just the fake.
- **SC-004 / SC-005** (embedding width, task prefixes): `tests/gateway/test_embeddings.py` passes.
  The architecture grep is now SC-005's mechanical check — no framing string
  (`"task: search result"`, `"title: none"`) exists outside `app/providers/`, except the seed
  script's literal data going into the profile's own `params` column.
- **SC-006** (one call at a time, across processes): `make check-lane` — 3 simulated callers (the
  API-shaped process plus both worker-shaped processes, matching M0's actual process count),
  maximum observed in-flight **1**.
- **SC-007** (gateway overhead ≤ 10 % at batch 32): `bench_embed.py` against real
  `ollama-embeddinggemma-300m`, 32 synthetic 1,944-char passages (real textbook passages don't
  exist in M1 — see Known limitations), with an untimed warm-up call so neither path absorbs
  Ollama's one-time model-load cost: **direct 10.69 chunks/s, through the gateway 10.60 chunks/s,
  overhead +0.8 %** — well inside budget. (An earlier run without the warm-up call measured -34.6 %
  — the *gateway* path looked faster only because it ran second, after Ollama had already loaded
  the model; the script now warms up before timing either path.)
- **SC-008 / SC-009** (timeouts, lane recovery, breaker): `tests/gateway/test_resilience.py` and
  `test_lanes.py` pass, including orphan-lease recovery and the breaker's fail-fast-under-1s path.
  Not re-exercised by literally killing a live worker process in this pass — the tests already
  drive that scenario against real Redis.
- **SC-010 / SC-011** (offline, deterministic): `make check` completed in **~23 s** (budget 5 min),
  with Ollama left running — the suite is offline *by construction* (`addopts = -m 'not llm'`,
  `FakeLLMProvider`/mocked-`httpx` fixtures throughout `tests/gateway/`), not by having quit the
  runtime this pass, matching `m0-foundation.md`'s precedent for not disrupting a running session
  to prove an already-structural guarantee. `tests/gateway` run three times back to back: **95
  passed, 1 skipped**, identical every time.
- **SC-012** (accounting without the book): `tests/gateway/test_accounting.py`'s 8 cases prove all
  three claims — a row per call with token counts and duration, 0 rows holding text while capture
  is off, identical requests sharing a digest — against `injaz_ai_test`. The dev database's
  `model_runs` is empty by design; see Known limitations.
- **SC-013** (seeding twice is a no-op): `make seed-profiles` run a second time reported
  `0 row(s) inserted, 5 already present`; `model_profiles` count unchanged at 5.
- **SC-014** (Control Center guardrails): `ModelProfileResourceTest.php`'s 5 assertions pass in
  `make check` — the activation-invariant transaction, the refused `dim` edit, the refused
  zero-active-profile save. Not re-driven through a live browser in this pass.
- **SC-015** (the smoke command): `make smoke-llm` returned a schema-valid `{'greeting', 'confidence'}`
  object (29 prompt / 214 completion tokens, 12.9 s) and a 768-dim embedding vector; 35.2 s total.
- **SC-017** (boundaries): `git status --short -- injazedu/` is empty — untouched by M1. The secret
  scan **fails**, but on two pre-existing false positives unrelated to M1 (`scripts/scan_secrets.sh`
  matching its own regex literals, `scripts/test_db_reset.sh` matching a variable *name*) — both
  predate this milestone (last touched in the M0 commit) and are unmodified by any M1 task; worth
  the operator's attention, not a regression introduced here.

**Full pytest suite** (`./scripts/check.sh`, all of `tests/`, not just `tests/gateway/`): **144
passed, 2 skipped** (pre-existing skips, unrelated to M1) in ~18 s. Combined with the PHP feature
test (5/5) and the (pre-existing) secret-scan finding above, that is `make check`'s complete result
this session.
