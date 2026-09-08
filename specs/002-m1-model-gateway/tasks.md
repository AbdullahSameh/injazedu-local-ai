---
description: "Task list for M1 — Model Gateway"
---

# Tasks: M1 — Model Gateway

**Input**: Design documents from `specs/002-m1-model-gateway/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts, retry
safety, security boundaries and data integrity — and `plan.md`'s Constitution Check enumerates the
ten behaviours that earn one, each mapped to an FR/SC. Behaviours named exempt there (Filament
scaffolding, Make plumbing, `.env.example`, logging format) get **no** test task here.

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US6, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, control panel at
`apps/ai-control/`, operator scripts at `scripts/`, `Makefile` at the root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration, package skeletons, and the offline-by-default test posture — before any
gateway code exists.

- [X] T001 Add the `llm` pytest marker and `addopts = "-m 'not llm'"` under `[tool.pytest.ini_options]` in `apps/ai-api/pyproject.toml` so a bare `uv run pytest` is offline (research D-40, FR-026)
- [X] T002 [P] Add the nine `GATEWAY_*` variables with their documented defaults to `.env.example`, per `specs/002-m1-model-gateway/contracts/environment.md`
- [X] T003 [P] Create package skeletons: `apps/ai-api/app/application/gateway/__init__.py`, `apps/ai-api/app/providers/llm/__init__.py`, `apps/ai-api/app/providers/embeddings/__init__.py`, `apps/ai-api/app/scripts/__init__.py`, `apps/ai-api/tests/gateway/__init__.py`; delete `apps/ai-api/app/providers/README.md`
- [X] T004 [P] Write failing unit tests for the new config validators (renew < lease TTL, positive timeout, non-negative retries) in `apps/ai-api/tests/unit/test_config_gateway.py`
- [X] T005 Extend `Settings` with the nine `GATEWAY_*` fields and their validators in `apps/ai-api/app/infrastructure/config.py`, following M0's fail-fast pattern (T004 goes green)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema, the error taxonomy, profile resolution, the Protocols, and minimal fakes.

**⚠️ CRITICAL**: No user story can begin until this phase completes.

**Note on the fakes (T015–T016)**: they live here, not in US4, because every story's tests run
through them. US4 then owns their *guarantees* — determinism, failure injection for every category,
and the offline proof.

- [X] T006 Write the failing migration test (upgrade → downgrade → upgrade; the partial unique index refuses a second active profile for one role; `ck_model_profiles_dim` refuses an embedding profile with a null `dim`) in `apps/ai-api/tests/integration/test_migration_0002.py`
- [X] T007 Create Alembic revision `0002_model_gateway` adding `model_profiles` and `model_runs` with every constraint and index in `data-model.md` §1–§2 — including the partial unique index `uq_model_profiles_one_active_per_role` — in `apps/ai-api/alembic/versions/0002_model_gateway.py` (T006 goes green)
- [X] T008 Define SQLAlchemy table metadata for both tables in `apps/ai-api/app/infrastructure/models.py`
- [X] T009 [P] Define the frozen `ModelProfile` dataclass (no ORM import — `domain/` is mypy-strict) in `apps/ai-api/app/domain/model_profile.py`
- [X] T010 [P] Define the closed error taxonomy — ten classes, each carrying `retryable`, `profile_name`, `category` — per `contracts/gateway-interface.md` §5, in `apps/ai-api/app/application/gateway/errors.py`
- [X] T011 [P] Define `LLMProvider` Protocol and the `TextRequest` / `StructuredRequest` / `TextResponse` / `StructuredResponse` / `Usage` models per `contracts/gateway-interface.md` §1–§2, in `apps/ai-api/app/providers/llm/base.py`
- [X] T012 [P] Define `EmbeddingProvider` Protocol, `TextKind`, `EmbeddingResult` and `BatchEmbeddingResult` in `apps/ai-api/app/providers/embeddings/base.py`
- [X] T013 Write failing registry tests (resolves the one active profile per role, `NoActiveProfileError` names the role, a change is visible after the TTL and not before) in `apps/ai-api/tests/gateway/test_registry.py`
- [X] T014 Implement the profile registry with a 30 s TTL cache (research D-37) in `apps/ai-api/app/application/gateway/registry.py` (T013 goes green)
- [X] T015 [P] Implement a minimal `FakeLLMProvider` — schema-valid synthesis from the caller's model — in `apps/ai-api/app/providers/llm/fake.py`
- [X] T016 [P] Implement a minimal `FakeEmbeddingProvider` — deterministic hash-derived vectors — in `apps/ai-api/app/providers/embeddings/fake.py`
- [X] T017 Implement the profile seed (`INSERT … ON CONFLICT (name) DO NOTHING`, the five rows in `data-model.md` §1) in `apps/ai-api/app/scripts/seed_profiles.py`, and add the `seed-profiles` target to `Makefile`
- [X] T018 Add shared gateway test fixtures (per-run-namespaced, TTL-bounded Redis keys; a session-scoped seeded-profile fixture) in `apps/ai-api/tests/gateway/conftest.py`

**Checkpoint**: Schema, errors, Protocols, registry and fakes exist — user stories can begin.

---

## Phase 3: User Story 1 — Structured results (Priority: P1) 🎯 MVP

**Goal**: A caller declares an output shape and receives a validated object of that shape, or a typed
failure naming the cause. Never free text to parse.

**Independent Test**: Request a structured result through `FakeLLMProvider` and confirm the object
matches the requested shape; configure the fake to violate it and confirm a typed failure with no
partial object. Runs with no model.

### Tests for User Story 1

- [X] T019 [P] [US1] Test the structured round-trip: a Pydantic model in, a validated instance out, `usage` and `latency_ms` populated — in `apps/ai-api/tests/gateway/test_structured.py`
- [X] T020 [P] [US1] ⚠ Test that `finish_reason: "length"` with empty content raises `ModelTruncatedError` and **never** a JSON parse error — the measured silent-failure mode (research D-26) — in `apps/ai-api/tests/gateway/test_structured.py`
- [X] T021 [P] [US1] Test that unparseable JSON and schema-invalid JSON both raise `StructuredOutputInvalidError`, and that no partial object reaches the caller, in `apps/ai-api/tests/gateway/test_structured.py`
- [X] T022 [P] [US1] Test `generate_text` returns text with token counts, in `apps/ai-api/tests/gateway/test_text.py`
- [X] T023 [P] [US1] Test the transport failure map: connection refused → `ProviderUnreachableError`; HTTP 404 `not_found_error` → `ModelNotAvailableError` naming the model; 400/422 → `ProviderRejectedError`; 401/403 → `ProviderAuthError` — in `apps/ai-api/tests/gateway/test_errors.py`

### Implementation for User Story 1

- [X] T024 [US1] Implement `OpenAICompatibleLLMProvider` — `POST {base_url}/chat/completions`, Pydantic `model_json_schema()` sent verbatim as `response_format.json_schema` with `strict: true`, and the HTTP-status → error mapping — in `apps/ai-api/app/providers/llm/openai_compatible.py`
- [X] T025 [US1] Implement the four-step structured validation in that provider, in order: assert `finish_reason == "stop"` **before parsing**, then `json.loads`, then `model_validate` (`contracts/gateway-interface.md` §3)
- [X] T026 [US1] Implement the gateway facade's generation path — resolve active profile → select provider → call → return — in `apps/ai-api/app/application/gateway/gateway.py`, leaving explicit seams for the breaker, lane and accounting added in US5/US6
- [X] T027 [US1] Apply per-call generation bounds (`num_ctx`, `num_predict`, `temperature`) from the active profile's `params`, with per-request overrides, in `apps/ai-api/app/providers/llm/openai_compatible.py` (FR-036, research D-34)

**Checkpoint**: Structured generation works end to end against the fake. MVP.

---

## Phase 4: User Story 2 — Embeddings (Priority: P2)

**Goal**: Fixed-width vectors, correct task framing applied internally, batched, in input order.

**Independent Test**: Embed a batch of passages and a query through the fake; confirm one vector per
input in input order at the profile's width; force a wrong width and confirm a loud failure.

### Tests for User Story 2

- [X] T028 [P] [US2] Test that document and query kinds apply different prefixes taken from the profile's `params`, and that a profile with no prefix keys embeds raw text (research D-29), in `apps/ai-api/tests/gateway/test_embeddings.py`
- [X] T029 [P] [US2] Test batch order preservation — results reordered by the response's `index`, never by arrival — in `apps/ai-api/tests/gateway/test_embeddings.py`
- [X] T030 [P] [US2] Test that a vector whose width ≠ the profile's `dim` raises `EmbeddingDimensionMismatchError` and nothing reaches the caller, in `apps/ai-api/tests/gateway/test_embeddings.py`
- [X] T031 [P] [US2] Test that a batch larger than `batch_size` is split internally and reassembled into one correctly ordered result set, in `apps/ai-api/tests/gateway/test_embeddings.py`
- [X] T032 [P] [US2] ⚠ Test that empty and whitespace-only input raises `ProviderRejectedError` naming the index — the runtime returns a full 768-dim vector for an empty string and will not object (research D-30) — in `apps/ai-api/tests/gateway/test_embeddings.py`

### Implementation for User Story 2

- [X] T033 [US2] Implement `OpenAICompatibleEmbeddingProvider` — `POST {base_url}/embeddings`, prefix templates from `params` with `{text}` substitution, internal batching at `params.batch_size` (default 32), reorder by `index`, width assertion — in `apps/ai-api/app/providers/embeddings/openai_compatible.py`
- [X] T034 [US2] Add `embed` and `embed_many` to the gateway facade in `apps/ai-api/app/application/gateway/gateway.py`, rejecting degenerate input before any transport call

**Checkpoint**: Both model capabilities work through one gateway.

---

## Phase 5: User Story 3 — Swap the model without changing code (Priority: P3)

**Goal**: Endpoint, model and parameters are operator-editable data. The headline acceptance criterion.

**Independent Test**: Re-point the active profile at a different endpoint and model in the Control
Center, re-run the unchanged suite and smoke command, and confirm `git status --short` is empty.

### Tests for User Story 3

- [X] T035 [P] [US3] Test seed idempotency: running the seed twice produces the same rows with no duplicates, and an operator's edit to a `base_url` survives a re-seed (research D-36, SC-013), in `apps/ai-api/tests/gateway/test_seed.py`
- [X] T036 [P] [US3] Test that a `vllm` profile and an `ollama` profile produce the correct wire shape for the same `StructuredRequest`, so caller code is identical against both (FR-014), in `apps/ai-api/tests/gateway/test_dialects.py`
- [X] T037 [P] [US3] Test `api_key_env` resolution: the value is read from the environment at call time, and an unset variable raises `ProviderAuthError` naming **the variable** (research D-38), in `apps/ai-api/tests/gateway/test_credentials.py`
- [X] T038 [P] [US3] Write the Filament feature test for the activation invariant — activating a second profile for a role deactivates the incumbent in one transaction, and the panel is refused a schema change — in `apps/ai-control/tests/Feature/ModelProfileResourceTest.php`

### Implementation for User Story 3

- [X] T039 [US3] Add provider-dialect selection (`ollama` | `vllm` | `fake`) driven by `model_profiles.provider` in `apps/ai-api/app/providers/llm/openai_compatible.py` and `apps/ai-api/app/providers/embeddings/openai_compatible.py`
- [X] T040 [US3] Implement `api_key_env` resolution from the process environment in both `openai_compatible.py` providers — the profile stores a variable name, never a value
- [X] T041 [US3] Build the Filament `ModelProfileResource` with full CRUD in `apps/ai-control/app/Filament/Resources/ModelProfileResource.php` (FR-042)
- [X] T042 [US3] Add the save-time guards — refuse leaving a role with no active profile, deactivate the incumbent in the same transaction on activate, refuse editing `dim` on an existing row, never display a credential value — in `apps/ai-control/app/Filament/Resources/ModelProfileResource.php` (FR-043, FR-044; T038 goes green)
- [X] T043 [P] [US3] Add the `profiles` target printing name, role, model, endpoint, dim and active state to `Makefile`

**Checkpoint**: The model swap is an operator action requiring zero code changes.

---

## Phase 6: User Story 4 — Run everything with no model (Priority: P4)

**Goal**: Deterministic fakes and a marked, excluded live-model path, so every later milestone's tests
run offline.

**Independent Test**: Quit the model runtime, run the quality gate, confirm it passes; repeat a
fake-backed run 10 times and confirm identical results; confirm the live-model tests were skipped and
are runnable on demand.

### Tests for User Story 4

- [X] T044 [P] [US4] Test fake determinism: identical inputs produce identical outputs across repeated runs, and the embedding fake gives same-text-same-vector / different-text-different-vector (research D-39), in `apps/ai-api/tests/gateway/test_fakes.py`
- [X] T045 [P] [US4] Test that the fake's default structured answer is synthesised from the caller's own model and therefore always schema-valid, in `apps/ai-api/tests/gateway/test_fakes.py`
- [X] T046 [P] [US4] Test failure injection: `fail_with` raises each of the ten error categories, so every gateway branch is reachable offline, in `apps/ai-api/tests/gateway/test_fakes.py`

### Implementation for User Story 4

- [X] T047 [US4] Extend `FakeLLMProvider` with the scripted-response queue, `fail_with` injection and simulated latency in `apps/ai-api/app/providers/llm/fake.py`
- [X] T048 [US4] Extend `FakeEmbeddingProvider` with configurable `dim` and `fail_with` injection in `apps/ai-api/app/providers/embeddings/fake.py`
- [X] T049 [US4] Implement the real round-trip smoke script — one structured generation and one embedding, printing shape, token counts and latency; reports an unreachable runtime immediately rather than waiting out the deadline — in `apps/ai-api/app/scripts/smoke_llm.py`
- [X] T050 [US4] Add the `smoke-llm` and `test-llm` targets to `Makefile`, and mark every live-model test `@pytest.mark.llm`

**Checkpoint**: The whole pipeline runs, and is tested, with no model present.

---

## Phase 7: User Story 5 — Survive concurrent demand (Priority: P5)

**Goal**: One generation and one embedding in flight **per machine**, bounded waits, bounded retries,
and a breaker that recovers on its own.

**Independent Test**: Issue several simultaneous requests and confirm at most one is in flight; force
a timeout and confirm the lane frees; kill a holder and confirm the lane recovers; force consecutive
failures and confirm fail-fast then automatic recovery.

⚠ **Why this is not an `asyncio.Semaphore`**: measured this session, the runtime did *not* serialise
two simultaneous generations, and M0 runs two worker processes plus the API — an in-process semaphore
would admit three concurrent generations while reporting itself compliant (research D-33).

### Tests for User Story 5

- [X] T051 [P] [US5] Test single occupancy **across processes**: concurrent acquirers from separate processes never overlap, and waiting is FIFO, in `apps/ai-api/tests/gateway/test_lanes.py`
- [X] T052 [P] [US5] Test lane release on every exit path — success, failure, timeout, cancellation — and that a long run leaves capacity identical to its starting value, in `apps/ai-api/tests/gateway/test_lanes.py`
- [X] T053 [P] [US5] Test orphan recovery: a holder killed mid-call frees the lane within `GATEWAY_LANE_LEASE_TTL_S`, in `apps/ai-api/tests/gateway/test_lanes.py`
- [X] T054 [P] [US5] Test retry policy: at most `GATEWAY_MAX_RETRIES` extra attempts, jittered spacing, and that a non-retryable error is never retried, in `apps/ai-api/tests/gateway/test_resilience.py`
- [X] T055 [P] [US5] Test that the deadline bounds the **whole call** including retries and lane wait, not each attempt (research D-31), in `apps/ai-api/tests/gateway/test_resilience.py`
- [X] T056 [P] [US5] Test the breaker: opens after `GATEWAY_BREAKER_THRESHOLD` consecutive retryable failures, then fails in under 1 second; caller errors never count toward the trip; half-open trial closes it (research D-32), in `apps/ai-api/tests/gateway/test_resilience.py`

### Implementation for User Story 5

- [X] T057 [US5] Implement the machine-wide lane — `BLPOP` acquire, lease `SET … PX`, 10 s watchdog renewal, `LPUSH` release, orphan detection and lazy token seeding, per `data-model.md` §3 — in `apps/ai-api/app/application/gateway/lanes.py`
- [X] T058 [P] [US5] Implement the Redis-backed circuit breaker keyed by profile, with half-open recovery, in `apps/ai-api/app/application/gateway/breaker.py`
- [X] T059 [US5] Wire breaker → lane → retry into the gateway's execution order in `apps/ai-api/app/application/gateway/gateway.py` (`contracts/gateway-interface.md` §6), releasing the lane on every exit path
- [X] T060 [US5] Implement the concurrent-lane proof script — fires simultaneous generations from the API and both workers, reporting maximum observed in-flight — in `apps/ai-api/app/scripts/check_lane.py`, and add the `check-lane` target to `Makefile`

**Checkpoint**: The 16 GB machine cannot be queue-stormed by any later milestone.

---

## Phase 8: User Story 6 — Know what every call cost (Priority: P6)

**Goal**: A record per call, carrying a fingerprint rather than copyrighted textbook text.

**Independent Test**: Issue successful and failing calls; confirm a record for each with token counts,
duration and outcome; confirm no record holds request text while capture is off.

### Tests for User Story 6

- [X] T061 [P] [US6] Test that every call — successful and failed — writes exactly one `model_runs` row with profile, operation, token counts, duration, attempts and outcome, in `apps/ai-api/tests/gateway/test_accounting.py`
- [X] T062 [P] [US6] Test redaction: with `GATEWAY_CAPTURE_PAYLOADS=false`, no row holds request or response text; with it true, both are written (FR-039), in `apps/ai-api/tests/gateway/test_accounting.py`
- [X] T063 [P] [US6] Test that identical requests produce identical `request_digest` values and different requests do not, in `apps/ai-api/tests/gateway/test_accounting.py`
- [X] T064 [P] [US6] Test that a recording failure is logged and swallowed, leaving the model call's own result unaffected (FR-040), in `apps/ai-api/tests/gateway/test_accounting.py`

### Implementation for User Story 6

- [X] T065 [US6] Implement the accounting writer — its own session, canonical sorted-key JSON SHA-256 digest, redaction by default, failures logged and swallowed — in `apps/ai-api/app/application/gateway/accounting.py`
- [X] T066 [US6] Wire accounting into the gateway after the caller's result is determined, for both success and failure paths, in `apps/ai-api/app/application/gateway/gateway.py`
- [X] T067 [US6] Add the `gateway` block — active profile names and `capture_payloads` state — to the health report's `model_runtime` component in `apps/ai-api/app/application/probes/model_runtime.py`, keeping the component informational (M0 FR-008, `contracts/gateway-interface.md` §8)

**Checkpoint**: Every model call is accounted for, with no copyrighted text stored.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T068 Add the architecture check to `scripts/check.sh`: fail the gate on any `httpx` / `ollama` / `openai` import outside `apps/ai-api/app/providers/`, and on any task-prefix string outside that directory (SC-001, SC-005)
- [X] T069 [P] Extend `make doctor` in `Makefile` to report the active profiles and whether their models are actually present in the runtime — the check that catches an activated-but-unpulled model
- [X] T070 [P] Write the operator runbook — commands, the swap procedure, and every known limitation from `quickstart.md` §5 — in `docs/runbooks/m1-model-gateway.md`
- [X] T071 Verify `mypy` strict still passes for `apps/ai-api/app/domain/` and `apps/ai-api/app/application/` under M0's existing overrides in `apps/ai-api/pyproject.toml`, fixing annotations rather than relaxing the config
- [X] T072 Measure SC-007 — batch-32 embedding through the gateway against a direct call, confirming ≤ 10 % overhead (session baseline: 15.32 chunks/s) — with a benchmark in `apps/ai-api/app/scripts/bench_embed.py`
- [X] T073 Run the full `quickstart.md` walkthrough end to end and record actual figures against SC-001…SC-017

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Setup — **blocks every user story**
- **US1 (Phase 3)**: needs Foundational
- **US2 (Phase 4)**: needs Foundational. Independent of US1 — different provider, different files
- **US3 (Phase 5)**: needs Foundational; T036 exercises the LLM provider from US1
- **US4 (Phase 6)**: needs Foundational; T049's smoke script exercises US1 + US2
- **US5 (Phase 7)**: needs Foundational; T059 edits `gateway.py`, created by US1
- **US6 (Phase 8)**: needs Foundational; T066 edits `gateway.py`, so it follows US5's edit
- **Polish (Phase 9)**: needs every story you intend to ship

### The one real serialization

`gateway.py` is touched by **T026 (US1) → T034 (US2) → T059 (US5) → T066 (US6)**. Those four cannot
run in parallel with each other. Everything else in those stories can.

### Within each story

Tests are written first and must fail before the implementation task that turns them green.

### Parallel opportunities

- T002, T003, T004 in Setup
- T009–T012 in Foundational (four independent files), then T015–T016
- Every test task inside a story is `[P]` — different assertions, and within a story they share a file
  only where the file is created by the first of them
- With more than one developer: after Phase 2, US1+US2 in parallel, then US3+US4 in parallel

---

## Parallel Example: Foundational

```bash
# After T008, launch the four independent definition files together:
Task: "Frozen ModelProfile dataclass in apps/ai-api/app/domain/model_profile.py"
Task: "Error taxonomy in apps/ai-api/app/application/gateway/errors.py"
Task: "LLMProvider Protocol and request/response models in apps/ai-api/app/providers/llm/base.py"
Task: "EmbeddingProvider Protocol and result models in apps/ai-api/app/providers/embeddings/base.py"
```

## Parallel Example: User Story 1

```bash
# All five US1 test tasks together, before any US1 implementation:
Task: "Structured round-trip test in apps/ai-api/tests/gateway/test_structured.py"
Task: "finish_reason=length -> ModelTruncatedError test in apps/ai-api/tests/gateway/test_structured.py"
Task: "Invalid/schema-violating JSON test in apps/ai-api/tests/gateway/test_structured.py"
Task: "generate_text token-count test in apps/ai-api/tests/gateway/test_text.py"
Task: "Transport failure map test in apps/ai-api/tests/gateway/test_errors.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 → Phase 2 → Phase 3.
2. **Stop and validate**: `make migrate && make seed-profiles && make smoke-llm` returns a
   schema-valid object with token counts.
3. At this point the project can already make structured model calls — M2's parser work is unblocked
   even if nothing else in M1 is finished.

### Incremental delivery

| After | You can                                   | Milestone unblocked         |
| ----- | ----------------------------------------- | --------------------------- |
| US1   | Structured generation                     | M5's answering shape        |
| + US2 | Embeddings at a pinned width              | **M4** — the retrieval gate |
| + US3 | Swap model or endpoint from the panel     | M10's A/B                   |
| + US4 | Run every later milestone's tests offline | all of them                 |
| + US5 | Run hundreds of calls overnight safely    | **M5's ~800-question pass** |
| + US6 | Answer "what did that cost?"              | M10's metrics               |

**US5 is the one to not skip.** M5 issues roughly 2,400 generation calls (~800 questions × 3
self-consistency runs). Without the machine-wide lane, three processes will each admit a call to a
runtime that does not serialise, on a machine with 16 GB.

### Suggested MVP scope

Phases 1–3 (T001–T027) — 27 tasks.

---

## Notes

- `[P]` = different files, no dependency on incomplete work
- Every task names its file path; every user-story task carries its `[US#]` label
- Tests are written first within each story and must fail before implementation
- Commit after each task or logical group — **operator action** (Constitution Principle IV)
- Two tasks carry a ⚠ because they encode measured findings that contradict the source plan:
  **T020** (truncation returns HTTP 200 with empty content) and **T051** (the runtime does not
  serialise, so the lane must be machine-wide)
