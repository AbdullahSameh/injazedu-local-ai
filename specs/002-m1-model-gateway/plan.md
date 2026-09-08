# Implementation Plan: M1 — Model Gateway

**Branch**: `m1/model-gateway` *(operator-created — Constitution IV)* | **Date**: 2026-09-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-m1-model-gateway/spec.md`
**Source plan**: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md` (M1 row, §5.1–§5.2, §10.3, §16.1–§16.5, §17, §18.6, §19, §22)

## Summary

M1 builds the single doorway between this project and any AI model: two protocols
(`generate_text` / `generate_structured`, `embed` / `embed_many`), one facade that owns everything
cross-cutting, and providers behind it that are the only code allowed to speak HTTP to a model.

The approach is thin and almost entirely additive. Two Alembic tables (`model_profiles`,
`model_runs`), one new package (`app/application/gateway/`), three provider modules per role
(`base` / `openai_compatible` / `fake`), a Filament resource, four Make targets, and one new check in
the quality gate. No new service, no new HTTP endpoint, no new infrastructure dependency — the
Redis that M0 already runs carries the lanes and the breaker.

**Two measurements this session changed the design rather than confirming it**, and both are the kind
of thing that stays invisible until it corrupts work at scale:

1. ⚠ **A truncated structured call is an HTTP 200 with empty content.** `finish_reason: "length"`,
   `content: ""`. Naive code reports "invalid JSON" and sends the operator to debug prompts when the
   fix is a larger token ceiling. The gateway checks `finish_reason` before parsing (D-26).
2. ⚠ **Ollama does not serialise.** Two simultaneous generations *overlapped* — 3.5 s wall against
   5.3 s of work. The approved plan's §16.4 premise is false as configured, which inverts the lane's
   role: it is not belt-and-braces over a runtime that already serialises, it is the only thing
   preventing fan-out. And because M0 runs two worker processes plus the API, an in-process semaphore
   would admit three concurrent generations. The lane is a Redis lease, machine-wide (D-33).

Everything else measured as the plan predicted or better: the OpenAI-compatible endpoint handles
JSON-schema output including Pydantic's `$defs`/`$ref`, returns `usage`, and embeds at
**15.32 chunks/s at batch 32** against the plan's 10.2.

## Technical Context

**Language/Version**: Python 3.12 (unchanged from M0) · PHP 8.2.27 for the Control Center
**Primary Dependencies**: no new runtime dependency. `httpx` (already present, M0), `pydantic` +
`pydantic-settings` (present), `redis` (present), SQLAlchemy 2.0 async (present), Alembic (present),
Filament 5 (present). ⚠ The `openai` SDK is deliberately **not** added — see Complexity Tracking.
**Storage**: PostgreSQL 16 — two new tables on revision `0002_model_gateway`. Redis — six new keys,
all TTL-bounded.
**Testing**: pytest + pytest-asyncio, offline by default (`addopts = -m 'not llm'`); live-model tests
behind `@pytest.mark.llm`; one Pest/PHPUnit feature test for the profile-activation invariant
**Target Platform**: macOS 26.6 on Apple Silicon (M1 Pro, 16 GB), local-only, no inbound network
**Project Type**: Multi-service local application — Python service (API + worker) + PHP control panel
**Performance Goals**: gateway overhead ≤ 10 % of a direct call at batch 32 (SC-007, baseline
measured 15.32 chunks/s) · open breaker fails in < 1 s (SC-009) · profile change visible in < 60 s
(SC-014) · quality gate < 5 min (SC-010)
**Constraints**: exactly one generation and one embedding in flight **per machine, not per process** ·
every test offline and model-free · no model-runtime import outside `app/providers/` · no prompt text
in `model_runs` by default · zero writes inside `injazedu/`
**Scale/Scope**: 2 tables, 5 seeded profiles, ~10 new modules, 4 new Make targets, ~35 focused tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution's Development Workflow requires every plan to answer five questions.

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested — these are public contracts, safety mechanisms, or data integrity:**

| Behavior | Why it earns a test | Covers |
|---|---|---|
| Structured output: schema round-trip, parse failure, validation failure, **and `finish_reason != "stop"`** | The gateway's central contract. D-26 is a measured silent-failure mode — untested, it returns empty answers as successes | FR-004, FR-008, SC-003 |
| The failure taxonomy: every category raised for its condition, with the right `retryable` | FR-032 is unimplementable without it; a wrong `retryable` either hammers a dead runtime or gives up on a transient blip | FR-008, SC-016 |
| Embedding: prefix by kind, input order preserved, width enforced, oversized batch split, empty input rejected | Retrieval quality at M4 depends on all five; a missed prefix or a stray empty-text vector degrades the corpus with no visible error | FR-018–FR-022, SC-004, SC-005 |
| Lane: single occupancy **across processes**, released on every exit path, orphan recovered after a kill | The 16 GB machine's survival, and ⚠ measured to be the only thing preventing fan-out | FR-029, FR-034, SC-006, SC-008 |
| Retry and breaker: bounded attempts, jitter, non-retryable never retried, breaker opens/half-opens/closes | Idempotency and retry safety — a named Principle I category | FR-031–FR-033, SC-009 |
| Profile resolution: exactly one active per role, cache TTL bound, `NoActiveProfileError` | The portability guarantee; ambiguity here silently picks the wrong model for an entire run | FR-011, FR-013, SC-002 |
| `dim` immutability and mismatch rejection | Data integrity for M4's vectors; cheap now, expensive after a corpus exists | FR-017, FR-021, SC-004 |
| Accounting: a row per call incl. failures, no payload while capture is off, stable digest, write failure swallowed | Security/privacy (§18.6 — copyrighted text) and the M10 audit trail | FR-037–FR-040, SC-012 |
| Seed idempotency: re-running preserves operator edits | FR-010's two halves pull opposite ways; only a test proves both hold | FR-010, SC-013 |
| Control Center: activation invariant enforced in one transaction | Authorization-adjacent state integrity; the DB index backstops it, the test proves the UI honours it | FR-043, SC-014 |

**Explicitly exempt under Principle I — no tests written:**
Filament resource scaffolding, form rendering and table columns (framework behavior) · Make target
plumbing · `.env.example` contents · the `profiles` pretty-printer · logging format · Alembic's own
up/down mechanics (M0 already tests the migration harness). These are simple wiring or framework
behavior.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

**Yes.** The `model_profiles` / `model_runs` tests and the Filament activation test are
database-backed. **No new wiring is introduced** — M1 inherits M0's mechanism unchanged:

- `TEST_DATABASE_URL` in `.env.testing`, database `injaz_ai_test`, read only by `tests/conftest.py`.
- M0's session-scoped autouse guard still aborts before collection unless the resolved name contains
  `_test` and differs from `DATABASE_URL`.
- `DB::prohibitDestructiveCommands()` still blocks `migrate:fresh` and friends on the PHP side.
- M1 adds **no** database beyond `injaz_ai_test` and drops none.
- The Redis keys the lane tests use are namespaced per test run and TTL-bounded, so a failed test
  cannot leave a lane held.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** M1 has no InjazEdu integration at all — the first is M6. Nothing inside `injazedu/` is
created, modified, or read. **Operator/InjazEdu-team work in M1: none.**

### 4. Are there Git actions in the task list? (Principle IV)

**Yes, and every one is an operator step:**

- The `m1/model-gateway` branch — **already created by the operator**; the agent did not create it,
  and the mandatory `before_specify` hook was not executed.
- The `before_plan` / `after_plan` auto-commit hooks in `.specify/extensions.yml` — surfaced by the
  agent, executed only by the operator.
- Committing M1's implementation — operator.

The agent inspects Git state (`status`, `diff`, `log`) and nothing more.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

**Yes.** Every design element maps to a numbered requirement in `spec.md`, which maps to the M1 row
and the sections listed under **Source plan**. Four boundary calls worth naming:

- **Vectors are produced, not stored.** No `embeddings_768` table, no HNSW index, no backfill — those
  are M4's, even though M1 pins the width they will use.
- **No prompt text anywhere.** `prompt_versions` and every Arabic template are M5/M7.
- **`model_runs` is written and never read.** The §17 metrics and dashboards are M10's.
- **One migration, two tables.** The rest of §8's schema belongs to the milestones that consume it.

Three scope questions the M1 milestone row left open were **put to the operator rather than guessed**,
per Principle V's "STOPS and presents the decision" clause; the answers are recorded in `spec.md`
Assumptions and in `checklists/requirements.md`.

Out-of-scope observations found while planning are recorded in `research.md` §6 as notes, not built.

**GATE RESULT: PASS.** No violations. See Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-m1-model-gateway/
├── plan.md                      # This file
├── spec.md                      # Feature specification (51 FRs, 17 SCs)
├── research.md                  # Phase 0 — 18 decisions (D-23…D-40), 6 live probes
├── data-model.md                # Phase 1 — 2 tables, 6 Redis keys, constraints
├── quickstart.md                # Phase 1 — operator walkthrough, SC-by-SC proof
├── contracts/
│   ├── gateway-interface.md     # THE contract: protocols, models, errors, semantics
│   ├── environment.md           # New variables (all optional, all defaulted)
│   └── make-targets.md          # New and changed operator commands
└── checklists/
    └── requirements.md          # Spec quality checklist (from /speckit-specify)
```

### Source Code (repository root)

Additive to M0's tree. **New** and *changed* marked; everything else is M0's, untouched.

```text
injazedu-local-ai/
├── Makefile                                    # + seed-profiles, profiles, smoke-llm, test-llm
├── .env.example                                # + 9 optional GATEWAY_* variables
├── apps/
│   ├── ai-api/
│   │   ├── pyproject.toml                      # * llm marker + addopts = -m 'not llm'
│   │   ├── alembic/versions/
│   │   │   └── 0002_model_gateway.py           # NEW  model_profiles, model_runs
│   │   └── app/
│   │       ├── domain/
│   │       │   └── model_profile.py            # NEW  frozen dataclass; no ORM in domain
│   │       ├── application/gateway/            # NEW  the facade — policy, not transport
│   │       │   ├── errors.py                   #      the closed taxonomy (D-27)
│   │       │   ├── registry.py                 #      active-profile resolution + 30 s cache
│   │       │   ├── lanes.py                    #      Redis lease, machine-wide (D-33)
│   │       │   ├── breaker.py                  #      Redis-backed, per profile (D-32)
│   │       │   ├── accounting.py               #      model_runs writer, digest, redaction
│   │       │   └── gateway.py                  #      compose: resolve→breaker→lane→retry→record
│   │       ├── providers/                      # * populated (was README-only at M0)
│   │       │   ├── llm/{base,openai_compatible,fake}.py
│   │       │   └── embeddings/{base,openai_compatible,fake}.py
│   │       ├── infrastructure/
│   │       │   ├── config.py                   # * GATEWAY_* settings + lease/renew validation
│   │       │   └── models.py                   # NEW  SQLAlchemy tables for the two new tables
│   │       ├── application/probes/
│   │       │   └── model_runtime.py            # * + gateway block in detail (FR-039)
│   │       └── scripts/
│   │           ├── smoke_llm.py                # NEW  §22's real round-trip
│   │           └── check_lane.py               # NEW  concurrent-lane proof (SC-006)
│   │       └── tests/gateway/                  # NEW  structured, embeddings, resilience,
│   │                                           #      registry, accounting, fakes
│   └── ai-control/
│       └── app/Filament/Resources/ModelProfileResource.php   # NEW  full CRUD (FR-042)
├── infra/                                      # unchanged
└── scripts/
    └── check.sh                                # * + architecture grep (SC-001)
```

**Structure Decision**: `providers/` finally gets its content — M0 created it as a README-only
skeleton precisely so M1 would add files without relocating anything (M0 FR-031), and that holds.

The one structural judgement is **splitting `application/gateway/` from `providers/`**. Providers own
transport and nothing else; the gateway owns policy — lane, retry, breaker, accounting, profile
resolution. This is what makes §5.1 rule 3 mechanically checkable (`httpx` may appear only under
`providers/`, and `make check` greps for it), and it means a second provider inherits every safety
rule instead of re-implementing it. `domain/model_profile.py` is a frozen dataclass with no ORM
import, keeping `domain/` under mypy `strict` as M0 configured it.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

**No violations.** All five gate questions pass without exception.

Four choices that *look* like added complexity, recorded because a reviewer will ask:

| Choice | Why it is not gratuitous |
|---|---|
| A Redis lease for the lane instead of `asyncio.Semaphore` | ⚠ Measured: Ollama did **not** serialise two simultaneous generations, and M0 runs 2 worker processes + the API. An in-process semaphore would admit 3 concurrent generations on a 16 GB machine while reporting itself compliant. FR-029 requires machine-wide. Redis is already a required dependency, so this adds keys, not infrastructure (D-33). |
| A separate `application/gateway/` package rather than logic inside the providers | It is what makes SC-001 checkable and stops each new provider re-implementing retry/lane/breaker — the place safety rules go wrong quietly. |
| `model_runs` written but never read in M1 | The operator chose this over an M5 retrofit. Writing from day one means M2–M4's calls accumulate the history §17 needs, and adding the write path later would mean touching the gateway's hot path again. |
| Hand-rolled HTTP over the `openai` SDK | The SDK is a large dependency for two endpoints, and it hides `finish_reason` handling behind convenience layers — exactly the field D-26 shows must be checked explicitly. `httpx` is already present from M0. |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 (research.md, data-model.md, contracts/, quickstart.md). Required by the
constitution's Compliance clause.*

**RESULT: PASS — strengthened.** The design introduced no violation, and three decisions made a gate
stronger than the pre-design plan promised:

| Gate | Pre-design | After design | Change |
|---|---|---|---|
| I — Risk-proportional testing | 10 tested behaviors, exemptions named | Unchanged, plus D-26 added a test for a silent-failure mode that would not have been written without the probe | Strengthened |
| II — Test DB isolation | Inherits M0's `_test` guard | Plus TTL-bounded, per-run-namespaced Redis keys, so a failed lane test cannot leave shared state held | Strengthened |
| III — `injazedu/` read-only | No writes | Confirmed: M1 neither reads nor writes it; `git status -- injazedu/` empty | Unchanged |
| IV — Git operator-owned | Branch + commits are operator steps | Unchanged; the branch already existed, operator-created, and no artifact performs a Git action | Unchanged |
| V — Approved scope | Traceable to the M1 row | D-35 (two tables only), the "vectors produced not stored" line, and research §6 items 1–3 each *declined* to build something a later milestone owns | Strengthened |

**Three things a reviewer should look at deliberately:**

1. **D-33 contradicts the approved plan's stated premise.** §16.4 says "Ollama serialises on one Metal
   context". Measured, it does not — probe 5 overlapped two generations. The plan's *conclusion* (build
   a lane) is right; its *reason* is wrong, and the wrong reason would have justified a per-process
   semaphore. This is a factual correction to the source plan, and the operator should know it applies
   to §16.4's wording, not just to M1.
2. **D-26 is a silent-failure class, not a bug.** HTTP 200 + empty content on truncation will recur in
   every milestone that calls a model. The gateway absorbing it once is the whole argument for having a
   gateway.
3. **The plan's §3.2 performance figures are now conservative** — 15.32 chunks/s measured at batch 32
   against 10.2 recorded. M4's ingestion budget can be revised down; nothing in M1 depends on it.

## Requirement → Design Traceability

| Spec requirements | Where the design answers them |
|---|---|
| FR-001…FR-008 (gateway boundary, failure taxonomy) | `contracts/gateway-interface.md` §1–§3, §5; D-23, D-24, D-26, D-27 |
| FR-009…FR-017 (model profiles) | `data-model.md` §1; D-35, D-36, D-37, D-38 |
| FR-018…FR-022 (embedding behaviour) | `contracts/gateway-interface.md` §4; D-28, D-29, D-30 |
| FR-023…FR-028 (offline determinism) | `contracts/gateway-interface.md` §7; D-39, D-40; `contracts/make-targets.md` |
| FR-029…FR-036 (concurrency, resilience) | `data-model.md` §3; `contracts/gateway-interface.md` §6; D-31, D-32, D-33, D-34 |
| FR-037…FR-041 (call accounting) | `data-model.md` §2; D-35 |
| FR-042…FR-046 (Control Center) | `data-model.md` §1 constraints + §4; `quickstart.md` §3 SC-014 |
| FR-047…FR-051 (boundaries, docs) | Project Structure above; `contracts/environment.md`; `quickstart.md` §5 |

Every FR is claimed by at least one design artifact; no design artifact exists without an FR.

## Phase Status

- [x] Phase 0 — research complete (18 decisions D-23…D-40, 6 live probes, 0 unresolved NEEDS CLARIFICATION)
- [x] Phase 1 — data model, 3 contracts, quickstart, agent context updated
- [x] Constitution Check — pre-design PASS, post-design PASS (strengthened)
- [ ] Phase 2 — task breakdown (`/speckit-tasks`, not produced by this command)
