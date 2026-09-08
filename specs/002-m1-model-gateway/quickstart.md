# Quickstart: M1 — Model Gateway

**Feature**: `specs/002-m1-model-gateway/` · **Date**: 2026-09-03

How the operator brings up M1 and proves each success criterion by hand. Assumes M0 is running
(`make up` → all five services healthy).

---

## 1. Prerequisites

| Check | Command | Expected |
|---|---|---|
| M0 stack healthy | `make health` | `"status": "ok"` |
| Ollama reachable | `curl -s localhost:11434/api/version` | a version — **0.33.2** verified this session |
| The two active models present | `ollama list` | `gemma4:e2b-it-qat`, `embeddinggemma:300m-qat-q4_0` |

**No new download is required.** The §16.1 roster is seeded, but only the two installed models are
active — the operator's decision, recorded in `spec.md`. `qwen3:8b` and `bge-m3` are seeded
**inactive**; activating one before pulling it produces `ModelNotAvailableError` naming the model.

**Still outstanding from M0** (verified unset this session): the four Ollama environment variables.
`scripts/check_ollama_env.sh` prints the `launchctl setenv` line for each. M1 is *correct* without
them (D-33), but set them anyway — see §5.

---

## 2. First run

```bash
make up                 # if not already running
make migrate            # applies 0002_model_gateway → model_profiles, model_runs
make seed-profiles      # idempotent; safe to re-run
make profiles           # what will the next call use?
```

`make profiles` should show `ollama-gemma4-e2b` and `ollama-embeddinggemma-300m` active, the other
three inactive.

```bash
make smoke-llm          # one real structured generation + one real embedding
```

Expect a schema-valid object, `768` dims, and token counts. This is **SC-015**.

---

## 3. Proving the success criteria

### SC-001 — nothing bypasses the gateway

```bash
make check              # the architecture grep is part of the gate now
```

To see it work, temporarily add `import httpx` to `app/application/gateway/gateway.py` and re-run —
`make check` must fail. Remove it.

### SC-002 — swapping the model changes no code

```bash
git stash list                                  # note: nothing to stash
# In the Control Center → Model Profiles: edit ollama-gemma4-e2b's `model` to gemma3:4b-it-qat
make smoke-llm                                  # within 30 s, uses the new model
git status --short                              # MUST be empty — zero code changed
```

The 30 s is the profile cache TTL (D-37). Calls already in flight finish on the old profile.

### SC-003 / SC-016 — structured output and the failure taxonomy

```bash
cd apps/ai-api && uv run pytest tests/gateway -q
```

Covers every error category by injection through `FakeLLMProvider`. To see the truncation case
against the real runtime — the one that returns HTTP 200 with empty content:

```bash
make smoke-llm -- --max-output-tokens 8         # expect ModelTruncatedError, not a JSON parse error
```

⚠ This is the finding worth understanding. A structured call that hits the token ceiling returns
**HTTP 200, `finish_reason: "length"`, `content: ""`**. Without the `finish_reason` check the error
reported is "the model produced invalid JSON", which sends you to debug prompts when the fix is a
larger ceiling.

### SC-004 / SC-005 — embedding width and prefixes

```bash
cd apps/ai-api && uv run pytest tests/gateway/test_embeddings.py -q
grep -rn "task: search result\|title: none" app/ --include=*.py | grep -v providers/
```

The grep must return **nothing** — prefixes exist only on profiles and in the provider (D-29).

### SC-006 — one call at a time, across processes

```bash
make check-lane          # fires 8 concurrent generations from api + both workers
```

Expect: max observed in-flight = **1**, all 8 answered, and `make mem-report` showing ≥ 6 GB free.

⚠ Worth knowing why this matters: measured this session, **Ollama did not serialise** — two
simultaneous generations overlapped (3.5 s wall against 5.3 s of work). The approved plan assumed the
runtime serialises on one Metal context; it does not, with `OLLAMA_NUM_PARALLEL` unset. The gateway's
lane is the only thing preventing fan-out on a 16 GB machine.

### SC-008 / SC-009 — timeouts, lane recovery, breaker

```bash
cd apps/ai-api && uv run pytest tests/gateway/test_resilience.py -q
```

Includes killing a worker mid-call and asserting the lane returns within
`GATEWAY_LANE_LEASE_TTL_S` (30 s), and that an open breaker fails in under 1 second.

### SC-010 / SC-011 — offline and deterministic

```bash
# Quit Ollama from the menu bar first
make check                                       # must pass, under 5 minutes
for i in 1 2 3; do (cd apps/ai-api && uv run pytest tests/gateway -q); done
```

Identical results all three runs. Restart Ollama afterwards.

### SC-012 — accounting without the book

```bash
make psql
```
```sql
SELECT operation, ok, error_type, prompt_tokens, completion_tokens, latency_ms, attempts
FROM model_runs ORDER BY created_at DESC LIMIT 10;

-- must return 0 while GATEWAY_CAPTURE_PAYLOADS=false:
SELECT count(*) FROM model_runs WHERE request_payload IS NOT NULL;

-- identical requests share a digest:
SELECT request_digest, count(*) FROM model_runs GROUP BY 1 HAVING count(*) > 1;
```

### SC-013 — seeding twice is a no-op

```bash
make seed-profiles && make seed-profiles
make psql -- -c "SELECT count(*) FROM model_profiles;"    # unchanged
```

### SC-014 — Control Center guardrails

In the panel → Model Profiles, try each. All three must be refused:

1. Deactivate the only active `llm` profile → refused, naming the role.
2. Activate a second `llm` profile → the incumbent is deactivated in the same transaction; never two.
3. Edit an embedding profile's `dim` → refused (FR-017).

### SC-017 — boundaries

```bash
./scripts/scan_secrets.sh
git status --short -- injazedu/     # MUST be empty
```

---

## 4. Switching to a GPU box later

The whole procedure, for the record — this is what M1 exists to make boring:

1. Control Center → Model Profiles → **New**: `provider = vllm`, `base_url = http://gpu-host:8000/v1`,
   `model =` the HF id, `api_key_env = VLLM_API_KEY`, `role = llm`.
2. Add `VLLM_API_KEY=…` to `.env` — the **value** never goes in the profile (D-38).
3. Activate it. The incumbent deactivates in the same transaction.
4. `make smoke-llm` within 30 s.

No code change, no redeployment of business logic, no migration. The runtimes' differing
JSON-schema dialects are absorbed by the provider (FR-014).

---

## 5. Known limitations of M1

- **Vectors are produced, not stored.** No `embeddings_768` table, no index, no backfill — M4.
- **No prompts.** M1 carries no prompt text or `prompt_versions` table — M5/M7.
- **No token pre-estimate.** `usage` gives exact counts *after* a call; M4's chunker needs a
  *pre-flight* estimate, which is a different function added with its consumer.
- **`model_runs` is written, never read.** The §17 dashboards are M10's.
- **Profile changes take up to 30 s** to take effect (D-37), and in-flight calls finish on the old
  profile.
- **The breaker is per profile, not per model.** Two profiles pointing at the same unreachable
  endpoint trip independently.
- **`qwen3:8b` and `bge-m3` are seeded but not pulled.** Activating either before `ollama pull` gives
  `ModelNotAvailableError`.
- **The four Ollama environment variables are still unset.** M1 is correct without them, but
  `OLLAMA_MAX_LOADED_MODELS=2` and `OLLAMA_KEEP_ALIVE=30m` matter for the §16.6 memory budget as soon
  as a second model is pulled.
