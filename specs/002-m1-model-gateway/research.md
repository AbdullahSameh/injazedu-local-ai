# Phase 0 Research: M1 — Model Gateway

**Feature**: `specs/002-m1-model-gateway/` · **Date**: 2026-09-03
**Source plan**: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`
(§5.1 rules 3 & 8, §5.2, §10.3, §16.1–§16.5, §17, §18.6, §19, §20 M1 row, §22)

18 decisions, D-23 … D-40, continuing M0's numbering so a decision id is unique across the project.
Every "measured" line below was run against the live stack on this machine on 2026-09-03; the
commands are in `quickstart.md` so the operator can reproduce them.

---

## 0. Ground truth measured this session

The M0 stack was up (`ai-api`, `ai-worker`, `ai-control`, `postgres`, `redis` — all healthy) and
Ollama **0.33.2** was serving `gemma4:e2b-it-qat` (4.34 GB) and `embeddinggemma:300m-qat-q4_0`
(0.24 GB). Six probes were run against `http://localhost:11434/v1`.

| # | Probe | Result | Consequence |
|---|---|---|---|
| 1 | `POST /v1/chat/completions` with `response_format: {type: json_schema, strict: true}` | **200**, content `{"chosen_key":"أ","confidence":1.0}`, `usage` present (148 prompt / 22 completion) | The OpenAI-compatible endpoint is sufficient. No native `/api/chat` path is needed → D-24 |
| 2 | Same, with a `$defs` / `$ref` schema (what Pydantic emits for nested models) | **200**, correct nested object, twice | No schema flattening needed → D-25 |
| 3 | **Truncation**: `max_tokens: 8` on a structured request | **200**, `finish_reason: "length"`, `content: ""` | ⚠ **A truncated structured call is an HTTP success with empty content.** Silent data loss unless the gateway checks `finish_reason` → **D-26** |
| 4 | Unknown model `qwen3:8b` | **404** `{"error":{"message":"model 'qwen3:8b' not found","type":"not_found_error"}}` | A missing model is distinguishable from a transport failure → D-31 |
| 5 | **Two simultaneous generations** | wall **3.5 s** vs. sum-of-calls **5.3 s** → **they overlapped** | ⚠ **Ollama did *not* serialise.** The approved plan's premise is wrong for the current configuration → **D-33** |
| 6 | `POST /v1/embeddings`, batch 8 and 32, on 1,944-char Arabic chunks | 768 dims both; **11.24 chunks/s @ 8**, **15.32 chunks/s @ 32**; `usage.prompt_tokens` present, `index` order preserved; empty strings return a full-width vector | Batch 32 confirmed as the default; the plan's 7.1/10.2 figures are conservative on this machine → D-28, D-30 |

Two of these change the design rather than confirm it. They are D-26 and D-33.

**Operator prerequisite still outstanding** (carried from M0's D-17): all four Ollama environment
variables remain **unset**, verified by `scripts/check_ollama_env.sh`. That is the direct cause of
probe 5 — see D-33.

---

## 1. The gateway boundary

### D-23 — Two protocols, one gateway facade, providers behind it

**Decision.** `app/providers/` holds transport; `app/application/gateway/` holds the facade. Callers
import only the facade and the request/response models.

```
app/providers/llm/          base.py (LLMProvider Protocol) · openai_compatible.py · fake.py
app/providers/embeddings/   base.py (EmbeddingProvider Protocol) · openai_compatible.py · fake.py
app/application/gateway/    gateway.py (lane + retry + breaker + accounting) · registry.py · errors.py
```

The Protocol shapes are §16.3's, unchanged: `generate_text`, `generate_structured`, `embed`,
`embed_many`.

**Rationale.** §5.1 rule 3 is "no `import ollama` outside `providers/`". Splitting *transport* from
*policy* is what makes that rule checkable: the provider modules are the only ones allowed to touch
`httpx`, and everything cross-cutting (lanes, retries, breaker, accounting) lives in one place
instead of being re-implemented per provider.

**Alternatives rejected.** One class per provider carrying its own retry/lane logic — every new
provider would re-implement the safety rules and could get them wrong. A single `ModelClient` god
class — mixes transport and policy, and makes the fake provider a mock of an HTTP client rather
than a substitute for a model.

### D-24 — The OpenAI-compatible endpoint only; no native Ollama API

**Decision.** All traffic goes to `{base_url}/chat/completions` and `{base_url}/embeddings` with
`base_url` ending in `/v1`. The native `/api/chat` and `/api/embed` endpoints are never used.

**Rationale.** Measured (probe 1, 2, 6): the compat endpoint handles JSON-schema-constrained output,
returns `usage`, and preserves batch order. It is also what vLLM speaks, so the portability
guarantee (FR-012, SC-002) costs nothing. Using the native API would buy nothing and would create a
dialect the vLLM provider could not satisfy.

**Consequence.** `model_profiles.base_url` for the local runtime is
`http://host.docker.internal:11434/v1` (M0's D-18 established that hostname for containers).

### D-25 — Schemas come from Pydantic models, sent verbatim

**Decision.** A caller declares its output shape as a Pydantic model. The provider sends
`model_json_schema()` as `response_format.json_schema.schema` with `strict: true`, and validates the
returned JSON back through the same model.

**Rationale.** Measured (probe 2): Ollama accepts `$defs`/`$ref` — the exact structure Pydantic emits
for nested models — and returned a correct nested object on both attempts. No dereferencing or
flattening layer is needed. Using one model for both the request schema and the response validation
means the two can never drift.

**Alternatives rejected.** Hand-written JSON Schema dicts — two sources of truth for one shape.
A flattening pre-pass — measured to be unnecessary; would have been dead code carrying a real risk of
altering semantics.

### D-26 — `finish_reason` is part of validation; truncation is a failure, not an empty answer

**Decision.** For every structured call the gateway asserts `finish_reason == "stop"` **before**
attempting to parse. Anything else — `length` above all — raises `ModelTruncatedError`, which is
retryable.

**Rationale.** ⚠ Measured (probe 3): a structured request that hits the token ceiling returns
**HTTP 200** with `finish_reason: "length"` and `content: ""`. Naive code does
`json.loads(content)`, gets a `JSONDecodeError`, and reports "the model produced invalid JSON" —
sending the operator to debug prompts when the real fix is a larger `num_predict`. Worse, a partial
but coincidentally parseable object would validate and be silently accepted.

This is the single most valuable finding of Phase 0, because it is invisible until it corrupts
M5's answers at scale.

**Consequence.** `ModelTruncatedError` names the token ceiling that was hit, so the operator's fix is
obvious. FR-036's per-call output bound is what makes the ceiling explicit and tunable per profile.

### D-27 — A closed set of failure categories, not messages

**Decision.** One exception hierarchy in `app/application/gateway/errors.py`, each with
`retryable: bool`:

| Error | Raised when | Retryable |
|---|---|---|
| `ProviderUnreachableError` | connect/read failure, DNS, refused | ✅ |
| `ModelNotAvailableError` | HTTP 404 `not_found_error` (probe 4) | ❌ |
| `ProviderRejectedError` | HTTP 400/422 — bad request shape | ❌ |
| `ProviderAuthError` | HTTP 401/403 | ❌ |
| `ModelTruncatedError` | `finish_reason != "stop"` (D-26) | ✅ |
| `StructuredOutputInvalidError` | JSON parse or Pydantic validation failure | ✅ |
| `EmbeddingDimensionMismatchError` | vector width ≠ profile `dim` | ❌ |
| `ModelTimeoutError` | per-call deadline exceeded | ✅ |
| `CircuitOpenError` | breaker open for this profile | ❌ (fails fast) |
| `NoActiveProfileError` | no active profile for the role | ❌ |

**Rationale.** FR-008 and SC-016. FR-032 ("never retry the caller's own mistake") is unimplementable
without this — the retry decision reads `retryable`, never a message string. It also lets M5 branch on
`ModelTruncatedError` (raise the ceiling) versus `StructuredOutputInvalidError` (change the prompt),
which are opposite fixes.

**Alternatives rejected.** A single `GatewayError` with a `code` string — every call site would
string-match, and a typo would silently disable a retry rule.

---

## 2. Embeddings

### D-28 — Batch 32, split internally, order preserved

**Decision.** `embed_many` default `batch_size=32`, configurable per profile; oversized caller lists
are chunked internally and reassembled in input order.

**Rationale.** Measured (probe 6) on real 1,944-char Arabic chunks: **15.32 chunks/s at batch 32** vs
**11.24 at batch 8** — a 36 % gain, same direction as the plan's 10.2 vs 7.1. The response's `index`
field was in order, but the gateway reorders by `index` explicitly rather than trusting arrival order,
because that ordering is not a documented guarantee of either runtime.

**Note for M4.** This machine is now measurably faster than the plan's §3.2 figures. A book of ~500
chunks embeds in **~33 s**, and 40 books in **~22 min** — better than the plan's ~35 min budget.

### D-29 — Task prefixes live on the profile, applied by the provider

**Decision.** `model_profiles.params` carries `prefix_document` and `prefix_query` templates. The
embedding provider applies them; nothing above the provider ever sees a prefix.

```json
{ "prefix_document": "title: none | text: {text}",
  "prefix_query":    "task: search result | query: {text}",
  "batch_size": 32 }
```

**Rationale.** FR-018 requires the framing be internal, and §10.3 verified it widens the
relevant-vs-irrelevant margin from +0.4611 to +0.4867. But the *strings* are model-specific —
`embeddinggemma` uses these; `bge-m3` (the §16.1 challenger) uses none. Hard-coding them in the
provider class would mean the bge-m3 A/B at M10 needs a code change, breaking FR-012. Putting them on
the profile keeps the swap a data edit while still keeping business code ignorant of them.

**Alternatives rejected.** Constants in the provider module — fails FR-012 for the challenger model.
Prefixes chosen by the caller — the exact failure mode FR-018 exists to prevent.

### D-30 — Empty input is rejected at the gateway, not passed through

**Decision.** Empty or whitespace-only text raises `ProviderRejectedError` naming the offending index.

**Rationale.** ⚠ Measured (probe 6): Ollama returns a **full 768-dim vector for an empty string** —
HTTP 200, no warning. That vector is meaningless but indistinguishable from a real one downstream; it
would sit in the M4 index and match queries. Since the runtime will not complain, the gateway must.
Rejecting is safer than substituting a zero vector, which would be equally invisible.

Satisfies FR-022. The alternative — returning `None` for those positions — was rejected because it
makes every caller handle a nullable vector for a case that indicates a bug upstream.

---

## 3. Concurrency, resilience, and the machine

### D-31 — Retry: 2 attempts, exponential backoff with full jitter, retryable errors only

**Decision.** `retries=2` (3 attempts total), backoff `0.5 · 2^n` seconds with full jitter, gated on
`error.retryable`. Per-call deadline **180 s** covering all attempts, not each attempt.

**Rationale.** §16.4's values. The deadline spans the whole call because FR-030's promise to the
caller is a bound on *its* wait; a per-attempt deadline would let three 180 s attempts run 9 minutes.
Full jitter rather than fixed backoff because two worker processes retrying a recovering runtime in
lockstep is how a thundering herd starts.

### D-32 — Circuit breaker in Redis, keyed by profile

**Decision.** Consecutive-failure counter and open-until timestamp in Redis at
`ai:gw:breaker:{profile_id}`. Opens after **5** consecutive failures, stays open **30 s**, then
half-open — one trial call decides. Only retryable errors count toward the trip.

**Rationale.** FR-033. The state must be shared: the resource being protected is one model runtime on
one machine, so the API process discovering it is down should spare the two worker processes from
each learning it independently — three processes × 5 failures × 180 s is 45 minutes of pointless
waiting. Redis is already required, so this adds a key, not a dependency. Caller errors are excluded
from the count because a malformed request says nothing about the runtime's health.

### D-33 — The lane is a Redis lease, machine-wide ⚠ *(supersedes the plan's premise)*

**Decision.** Two single-occupancy lanes, `llm` and `embed`, held as Redis leases shared by every
process. Acquire, hold, release:

```
acquire   BLPOP ai:gw:lane:{name}:tokens  (blocks, FIFO, bounded by the acquire timeout)
          → SET ai:gw:lane:{name}:lease:{token} {holder} PX 30000
hold      a watchdog re-SETs the lease PX 30000 every 10 s while the call runs
release   DEL lease ; LPUSH the token back
orphan    BLPOP times out AND no lease key is alive → the holder died →
          LPUSH the token back and retry the acquire
```

**Rationale.** ⚠ **The approved plan's §16.4 premise — "Ollama serialises on one Metal context" — is
false as currently configured.** Measured (probe 5): two simultaneous generations *overlapped*
(3.5 s wall against 5.3 s of work). `OLLAMA_NUM_PARALLEL` is unset, so the runtime fans out by
default. The plan's conclusion is right for the wrong reason: the lane is not belt-and-braces over a
runtime that already serialises, it is **the only thing preventing fan-out**, and it must not depend
on an operator having exported an environment variable.

The lane must also be machine-wide, not per process. M0 runs 2 worker processes plus the API process;
an in-process semaphore would admit **3** concurrent generations and each would still report itself
compliant. That is FR-029, and it is why an `asyncio.Semaphore` is insufficient.

BLPOP gives blocking FIFO waiting for free — no polling. The lease with a watchdog gives crash
recovery, satisfying FR-034: a process killed mid-call loses its lease within 30 s and the next
waiter restores the token. Because concurrency is 1, "is the token missing and is there no live
lease?" is an unambiguous orphan test.

**Alternatives rejected.** `asyncio.Semaphore` — per process, fails FR-029 as shown above.
BLPOP tokens with no lease — a crash loses the token permanently and capacity never returns
(fails FR-034). `SET NX PX` spin-lock — works, but polls and gives no fairness, risking starvation of
a worker behind a stream of API calls. Redlock — designed for multiple independent Redis nodes;
there is one, so it is ceremony.

**Consequence.** `OLLAMA_NUM_PARALLEL=1` stays an operator prerequisite (defence in depth, and it
stops Ollama reserving memory for parallel slots), but M1's correctness does not rely on it.

### D-34 — Generation parameters are bounded per operation, from the profile

**Decision.** `model_profiles.params` carries `num_ctx`, `num_predict`, `temperature`. §16.2's values
are the seeded defaults: `num_ctx` 8192 for generation, `num_predict` bounded per call.

**Rationale.** FR-036 and §16.6's memory budget — context size is the dominant per-call memory term on
a 16 GB machine. Making it a profile field rather than a constant means the M5 answering pass can run
at `num_ctx` 4096 (§16.2) by activating a profile, not by editing code. D-26 makes an unbounded
`num_predict` actively dangerous, since hitting the ceiling is a silent truncation.

---

## 4. Profiles and persistence

### D-35 — `model_profiles` and `model_runs` in one Alembic revision `0002`

**Decision.** One migration adds both tables. `model_runs.job_id` and `prompt_version_id` are nullable
`BIGINT` with **no foreign key** until `generation_jobs` and `prompt_versions` exist.

**Rationale.** §8's schema, narrowed to what M1 uses. FR-041 requires the columns exist now so later
milestones add a constraint rather than a column plus a backfill. M0's D-04 default privileges mean
`ai_app` and `ai_control` receive DML on both tables automatically — no follow-up `GRANT`, and the
"Filament cannot do DDL" guarantee is untouched (FR-046).

### D-36 — Idempotent seeding by unique name, never overwriting operator edits

**Decision.** Profiles are seeded by a `make seed-profiles` target running an `INSERT … ON CONFLICT
(name) DO NOTHING`. Seeding is **not** part of the migration.

**Rationale.** FR-010's two halves pull in opposite directions: seed the roster, but do not clobber
what the operator changed. `DO NOTHING` on the unique `name` satisfies both — re-running is a no-op
even after the operator has re-pointed a profile's `base_url` (which FR-042's CRUD explicitly invites).
Keeping it out of the migration matters because a migration re-run on a fresh database must not
resurrect a profile the operator deliberately deleted.

**Seeded roster** (§16.1), with the operator's decision that the installed model stays active:

| name | role | model | active | note |
|---|---|---|---|---|
| `ollama-gemma4-e2b` | llm | `gemma4:e2b-it-qat` | **✅** | installed; the speed baseline |
| `ollama-qwen3-8b` | llm | `qwen3:8b` | — | §16.1 primary; **not pulled** (probe 4) |
| `ollama-gemma3-4b` | llm | `gemma3:4b-it-qat` | — | §16.1 fast lane; not pulled |
| `ollama-embeddinggemma-300m` | embedding | `embeddinggemma:300m-qat-q4_0` | **✅** | `dim=768`, prefixes per D-29 |
| `ollama-bge-m3` | embedding | `bge-m3` | — | `dim=1024`; M10 challenger; not pulled |
| `fake-llm` / `fake-embedding` | llm / embedding | — | — | test profiles, never active in `.env` |

### D-37 — Active profile resolved by a 30-second TTL cache

**Decision.** The registry caches the active profile per role for **30 s**. A `updated_at` bump by
Filament takes effect on the next cache miss.

**Rationale.** FR-013 wants a bounded window; SC-014 sets it at under a minute. 30 s clears that with
margin while removing a database round-trip from every model call. The alternative — a pub/sub
invalidation channel — would couple the PHP panel to a Python cache protocol across a language
boundary, to save at most 30 s on an action the operator takes a handful of times a year.

**Consequence documented for the operator:** after flipping a profile in Filament, calls already in
flight finish on the old profile and the change is visible within 30 s. `quickstart.md` says so.

### D-38 — Credentials are an environment key reference, never a value

**Decision.** `model_profiles.api_key_env` stores a *variable name* (e.g. `VLLM_API_KEY`). The
provider resolves it from the process environment at call time. Ollama needs none; the column is
nullable and the local profiles leave it null.

**Rationale.** FR-015, FR-044 and the constitution's "secrets stay out of the repo". It also keeps
FR-044 trivially true: Filament edits a variable *name*, so there is no secret in the panel, in the
database, or in a `pg_dump`. A missing variable is a startup-shaped failure naming the variable, in
the style M0's `config.py` already established.

---

## 5. Testing and the quality gate

### D-39 — Fakes are scripted, deterministic, and fail on demand

**Decision.** `FakeLLMProvider` and `FakeEmbeddingProvider` satisfy the same Protocols and offer:
a default that synthesises a schema-valid instance from the requested Pydantic model; a scripted queue
of canned responses; and an injectable failure mode for each of D-27's error categories. Embeddings
are a deterministic hash of the normalised text, so identical text always yields an identical vector
and cosine comparisons in tests are stable.

**Rationale.** FR-023–FR-025, §19. Deriving the default answer from the caller's own model means a
fake never goes stale when a schema changes. Hash-derived vectors give M4's retrieval tests something
with real structure — same text, same vector; different text, different vector — without a model.

### D-40 — `@pytest.mark.llm` excluded by default; one smoke script for the real round-trip

**Decision.** Register the `llm` marker and add `addopts = "-m 'not llm'"` to `pyproject.toml`.
`make check` therefore stays offline (FR-026). `python -m app.scripts.smoke_llm` (§22's name) does one
real structured round-trip plus one real embedding, printing shape, token counts and latency.

**Rationale.** FR-027, FR-028, §19, §22. Exclusion-by-default in configuration rather than in
`check.sh` means an unqualified `uv run pytest` is also safe — the guarantee does not depend on the
operator using the wrapper.

**Architecture check.** `check.sh` gains a grep asserting no `httpx`/`ollama`/`openai` import outside
`app/providers/` (SC-001), joining the existing secret scan. §5.1 rule 3 becomes mechanical.

---

## 6. Out-of-scope observations (recorded, not built — Principle V)

1. **`num_predict` ceilings are per-prompt, not per-profile.** D-34 puts a default on the profile, but
   M5's answering and M7's generation will want different ceilings for the same model. The per-call
   override exists in the request model; choosing the values is those milestones' work.
2. **`bge-m3` and `qwen3:8b` are not pulled.** Probe 4 confirms a missing model 404s cleanly. Their
   profiles are seeded inactive, so nothing breaks; pulling them is an M4/M10 prerequisite, not M1's.
3. **Token counting for chunking (§10.2) is deferred to M4** per the spec's Out of Scope. The
   `usage` block measured in probes 1 and 6 already gives exact post-hoc counts, so M4's need is a
   *pre-flight estimate* — a different function, best added when its consumer exists.
4. **The plan's §3.2 performance figures are stale in the project's favour**: embedding measured
   15.32 chunks/s at batch 32 against the plan's 10.2. M4's ingestion budget can be revised down.
5. **Ollama's four environment variables are still unset** (M0 D-17 carried forward). D-33 removes
   M1's *correctness* dependency on them, but `OLLAMA_MAX_LOADED_MODELS=2` and `OLLAMA_KEEP_ALIVE=30m`
   still matter for the §16.6 memory budget once a second model is pulled.
