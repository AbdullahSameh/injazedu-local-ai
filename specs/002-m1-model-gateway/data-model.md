# Phase 1 Data Model: M1 — Model Gateway

**Feature**: `specs/002-m1-model-gateway/` · **Date**: 2026-09-03
**Owner of this schema**: Alembic, revision `0002_model_gateway` (M0 D-02, research D-35)

M1 adds **two tables** and **one Redis keyspace**. Nothing else in the plan's §8 schema is created —
`chunks`, `embeddings_768`, `book_questions`, `prompt_versions` and the rest belong to the milestones
that consume them.

---

## 1. `model_profiles`

One row = one model, at one endpoint, for one role. Activating a different row is the whole of
FR-012 and SC-002.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` PK | no | identity |
| `name` | `VARCHAR(100)` | no | **UNIQUE** — the seed's conflict target (D-36) |
| `provider` | `VARCHAR(30)` | no | `ollama` \| `vllm` \| `fake` |
| `base_url` | `VARCHAR(500)` | no | must end `/v1` (D-24); null only for `fake` |
| `model` | `VARCHAR(200)` | no | runtime's model id, e.g. `gemma4:e2b-it-qat` |
| `role` | `VARCHAR(20)` | no | `llm` \| `embedding` |
| `params` | `JSONB` | no | default `'{}'` — see below |
| `dim` | `INTEGER` | yes | **required when `role='embedding'`**, else must be null |
| `api_key_env` | `VARCHAR(100)` | yes | a variable *name*, never a value (D-38, FR-015) |
| `is_active` | `BOOLEAN` | no | default `false` |
| `notes` | `TEXT` | yes | operator free text |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | no | `now()`; `updated_at` drives the cache (D-37) |

### Constraints

| Name | Rule | Requirement |
|---|---|---|
| `uq_model_profiles_name` | `UNIQUE (name)` | D-36's idempotent seed |
| `ck_model_profiles_role` | `role IN ('llm','embedding')` | FR-009 |
| `ck_model_profiles_provider` | `provider IN ('ollama','vllm','fake')` | FR-014 |
| `ck_model_profiles_dim` | `(role='embedding') = (dim IS NOT NULL)` and `dim > 0` | FR-021 — an embedding profile without a width is unusable |
| `uq_model_profiles_one_active_per_role` | `UNIQUE (role) WHERE is_active` — a **partial unique index** | **FR-011.** The database, not application code, makes "two active profiles for one role" impossible |

`uq_model_profiles_one_active_per_role` is the load-bearing one. It turns the spec's "resolve exactly
one active profile per role, deterministically" from a rule someone must remember into a state the
database will not hold. Filament's activate action must therefore deactivate the incumbent in the
same transaction (FR-043).

### `params` by role

```jsonc
// role = 'llm'
{ "num_ctx": 8192, "num_predict": 1024, "temperature": 0.6 }

// role = 'embedding'   (prefix templates are per-model — research D-29)
{ "batch_size": 32,
  "prefix_document": "title: none | text: {text}",
  "prefix_query":    "task: search result | query: {text}" }
```

`{text}` is the only placeholder. A profile with no prefix keys (the `bge-m3` challenger) embeds raw
text — which is why the templates live here and not in the provider class.

### `dim` immutability (FR-017)

Enforced in two places, deliberately:

1. **Filament** refuses to edit `dim` on an existing row (FR-043) — the operator sees why.
2. **The gateway** raises `EmbeddingDimensionMismatchError` when a returned vector's width ≠ `dim`
   (D-27) — so a hand-edited row cannot poison stored vectors either.

M1 stores no vectors, so this is prophylactic for M4. It is cheap now and expensive to retrofit after
a corpus exists.

### Seeded rows (D-36)

Inserted by `make seed-profiles`, `ON CONFLICT (name) DO NOTHING`, **not** by the migration.

| `name` | `role` | `model` | `dim` | `is_active` |
|---|---|---|---|---|
| `ollama-gemma4-e2b` | llm | `gemma4:e2b-it-qat` | — | **true** |
| `ollama-qwen3-8b` | llm | `qwen3:8b` | — | false |
| `ollama-gemma3-4b` | llm | `gemma3:4b-it-qat` | — | false |
| `ollama-embeddinggemma-300m` | embedding | `embeddinggemma:300m-qat-q4_0` | 768 | **true** |
| `ollama-bge-m3` | embedding | `bge-m3` | 1024 | false |

Only the two installed models are active, per the operator's decision recorded in `spec.md`.
`fake` profiles are constructed in test fixtures, not seeded — a fake row in the operator's database
is a foot-gun with no upside.

---

## 2. `model_runs`

One row per model call, successful or failed (FR-037). Written by the gateway, read by nothing in M1
— §17's metrics are M10's.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` PK | no | |
| `model_profile_id` | `BIGINT` FK → `model_profiles.id` | no | `ON DELETE RESTRICT` |
| `job_id` | `BIGINT` | yes | **no FK** until `generation_jobs` exists (D-35, FR-041) |
| `prompt_version_id` | `BIGINT` | yes | **no FK** until `prompt_versions` exists |
| `operation` | `VARCHAR(30)` | no | `generate_text` \| `generate_structured` \| `embed` \| `embed_many` |
| `prompt_tokens` | `INTEGER` | yes | from `usage`; null when the call failed before a response |
| `completion_tokens` | `INTEGER` | yes | always null for embeddings — the runtime returns none (probe 6) |
| `latency_ms` | `INTEGER` | no | wall time including retries and lane wait |
| `attempts` | `SMALLINT` | no | default 1 — how many tries it took (D-31) |
| `ok` | `BOOLEAN` | no | |
| `error_type` | `VARCHAR(60)` | yes | a D-27 category name, e.g. `ModelTruncatedError` |
| `error_detail` | `TEXT` | yes | message only; never request content |
| `request_digest` | `CHAR(64)` | no | SHA-256, see below |
| `request_payload` | `JSONB` | yes | **null unless debug capture is on** (FR-039) |
| `response_payload` | `JSONB` | yes | same |
| `created_at` | `TIMESTAMPTZ` | no | `now()` |

**Indexes**: `(model_profile_id, created_at DESC)` for M10's per-profile slicing;
`(created_at DESC)` for recent-activity reads; `(request_digest)` for FR-038's identical-request
comparison.

### `request_digest` (FR-038, SC-012)

`SHA-256` over a canonical JSON serialisation (sorted keys, no whitespace) of
`{model, operation, messages | input, params, schema}`. Identical requests produce identical digests;
the digest reveals nothing about the textbook text.

**Why a digest at all** — §18.6: the prompts contain copyrighted book content, so storing them by
default would put the corpus in a second place, in the clear, in every backup. The digest still
answers the questions that matter operationally: *did we make this exact call before*, and *how many
distinct calls did this job make*.

### Debug capture (FR-039)

`GATEWAY_CAPTURE_PAYLOADS=false` in `.env` by default. When true, `request_payload` and
`response_payload` are filled. The health report echoes the flag's state so "it was left on" is
visible without reading configuration (FR-039's visibility half).

### Write path (FR-040)

The gateway writes the record on its own session, **after** the caller's result is determined, and a
write failure is logged and swallowed — never propagated. Accounting must not be able to fail a model
call that already succeeded.

---

## 3. Redis keyspace

Additive to M0's `ai:worker:heartbeat:*`. All keys carry a TTL, so a crash cannot leave permanent
state.

| Key | Type | TTL | Purpose |
|---|---|---|---|
| `ai:gw:lane:llm:lease` | string | 30 s, renewed every 10 s | Occupancy itself: `SET … NX` claims it, so exactly one holder can ever exist (D-33, implementation note below) |
| `ai:gw:lane:llm:tokens` | list | — | Wakeup channel only, not a token pool: `BLPOP` to wait, `LPUSH` to nudge a waiter to retry the claim |
| `ai:gw:lane:embed:lease` | string | 30 s | Same, for the embedding lane |
| `ai:gw:lane:embed:tokens` | list | — | Same |
| `ai:gw:breaker:{profile_id}:failures` | integer | 120 s | Consecutive retryable failures (D-32) |
| `ai:gw:breaker:{profile_id}:open_until` | string | 30 s | Epoch seconds; while set, calls fail fast |

**Implementation note (post-implementation correction).** The design above this table originally
called for a *pool* of lease-carrying tokens (`BLPOP` to pop one, then `SET` its own
`lease:{token}` key) with lazy reseeding when neither a token nor a live lease was found. Building
it exposed a real race: popping a token and then setting its lease were two separate round trips,
and a concurrent acquirer's "is anything live?" check could land in the gap between them and seed
a second token — observed directly as two simultaneous holders under `app/scripts/check_lane.py`.
The implementation instead claims a single, fixed lease key with one atomic `SET … PX … NX`, which
Redis guarantees cannot double-admit. A holder's TTL expiring *is* orphan recovery — no separate
"is the token missing and is there no live lease?" check is needed. The `tokens` list survives
only as a `BLPOP` wakeup channel so waiters block instead of polling; it no longer holds the token
itself. A fencing value (the holder id, compared before every renew and release) stops a delayed
watchdog or release from touching a lease a different holder has since reclaimed after expiry.

---

## 4. State transitions

`model_profiles` has one meaningful transition — activation — and the partial unique index makes it
atomic-or-nothing:

```
inactive ──activate (same txn: deactivate incumbent for this role)──▶ active
active   ──activate another profile of the same role──────────────▶ inactive
```

There is no delete transition for a profile referenced by `model_runs`: `ON DELETE RESTRICT` keeps the
accounting history readable. Filament offers deactivate, not delete, for such rows.

`model_runs` rows are **immutable** — written once, never updated. That is what makes them usable as
an audit trail at M10.

---

## 5. Entity → requirement traceability

| Spec entity | Realised as | Requirements |
|---|---|---|
| Model profile | `model_profiles` table + partial unique index | FR-009…FR-017, FR-042…FR-046 |
| Call record | `model_runs` table | FR-037…FR-041 |
| Execution lane | `ai:gw:lane:*` Redis keys | FR-029, FR-034 |
| Structured result contract | Caller's Pydantic model (no persistence) | FR-004, FR-008 |
| Text kind | `kind: Literal["document","query"]` argument (no persistence) | FR-018 |
| Stand-in provider | Test fixtures (no persistence) | FR-023…FR-025 |
