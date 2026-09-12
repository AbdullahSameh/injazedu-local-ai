# Implementation Plan: TG-M1 — Telegram Event Ingestion

**Branch**: `tg-m1/telegram-ingestion` *(operator-created — Constitution IV)* | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-tg-m1-telegram-ingestion/spec.md`
**Source plan**: `docs/plan/telegram/telegram-moderation-intelligence.md` (§5, §7.1, §9, §10.1–10.3, §20, §21, §22, §25 TG-M1, §26.1, §30)
**Operator runbook**: `docs/runbooks/tg-operator-prerequisites.md` (§B, §C TG-M1 row, §D, §F)

## Summary

TG-M1 makes the domain start listening. It ships **one new container, four tables in one migration,
one provider, one capture loop, one interpreting stub, one health block and one diagnostic command** —
and interprets nothing. The bot sends nothing and the machine opens no port.

The approach is deliberately narrow: the capture process durably stores and advances the offset, and
*all* interpretation happens in the worker (§7.3). That split is what makes every later milestone's
bugs replayable, because Telegram will not hand these events over a second time.

**Three probes changed the design rather than confirming it.** Each would have produced a silent
failure — the class of bug this milestone exists to prevent:

1. ⚠ **After a week of total silence, Telegram picks a random next `update_id` — and the spec's
   FR-019 ("the position never moves backwards"), taken literally, then stalls capture forever.** The
   new identifier can be *lower* than the last stored one; `getUpdates(offset=last+1)` never returns
   it; polls succeed, return nothing, raise nothing, and every health signal stays green. The recovery
   is to **omit `offset` entirely** — documented as "updates starting with the earliest unconfirmed
   update" — never a negative offset, which the docs say forgets the whole backlog. FR-019 gains one
   documented exception (D-TG-33). **This corrects an approved requirement; see the operator note
   below.**
2. ⚠ **The natural place for the health probe fails `make check`.** Planting the files exactly where
   the source plan's §25 row puts them makes the gate's reverse boundary rule fire — correctly, since
   `app/application/probes/` is assessment-side and may not read moderation tables. The fix is to
   compose the probe at the **composition root**, which the gate already exempts and which makes the
   block conditional on composition — matching FR-007 exactly (D-TG-31).
3. ⚠ **`ComponentReport` silently discards an ingestion block passed as an ad-hoc keyword.** It is
   `frozen=True` but not `extra="forbid"`, so pydantic v2 accepts the unknown field and drops it. A
   probe written the obvious way produces a health payload with no ingestion data, and every
   `status == "ok"` assertion passes. The block must be a **declared field** (D-TG-32).

Two further probes narrowed the work. `ON CONFLICT DO NOTHING … RETURNING` returns **only** genuinely
inserted rows, so FR-010 and FR-011 are one statement rather than a read-then-write with a race in it
(D-TG-30). And the Bot API's `limit` maximum is **100** — the operator's clarified batch ceiling and
the platform's own ceiling are the same number, so there is no tuning question (D-TG-40).

## Technical Context

**Language/Version**: Python 3.12 (unchanged) · no change to the PHP control panel — TG-M1 has no UI
**Primary Dependencies**: **none added.** `httpx` (present, and `app/providers/telegram/` sits inside
the existing exemption — TG-M0's D-TG-19), SQLAlchemy Core, Alembic, Dramatiq, `redis.asyncio`,
`pydantic-settings`. ⚠ **No Telegram SDK** — the provider speaks the Bot API over `httpx`
**Storage**: Postgres — 4 new tables in revision **`0003_moderation_ingest`** (head confirmed `0002`,
probe 10). Redis — one key, `ai:tg:poll:lease`, **a lock, never a fact**
**Testing**: pytest, offline by default. New package `tests/moderation/ingest/` driven by
`FakeTelegramTransport` (an `httpx.MockTransport`, mirroring the gateway's injected transport);
database tests through `injaz_ai_test` under M0's existing session guard
**Target Platform**: macOS 26.6 on Apple Silicon (M1 Pro, 16 GB), local-only, **no inbound port**
**Project Type**: Multi-service local application — Python service (API + worker + **new poller**) + PHP control panel
**Performance Goals**: none of consequence. 100 events per poll (the API maximum), a 30 s long poll,
low hundreds of events/day. A weekend backlog drains in seconds, far inside the 24 h retention window
**Constraints**: no message sent to any chat · no reaction, deletion, ban or restriction · no inbound
port · no webhook · every test offline and credential-free · `make check` green with no credential ·
no import across the moderation/assessment boundary · no message text in any log line · zero writes
inside `injazedu/`
**Scale/Scope**: 1 new container, 4 tables, 1 migration, ~8 new modules, 1 health block, 1 make
target, ~45 focused tests, 0 screens, 0 model calls

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested — contracts, idempotency, data-safety mechanisms, and measured failure modes:**

| Behavior | Why it earns a test | Covers |
|---|---|---|
| Duplicate `update_id` → one row, one job | Idempotency and retry safety, named in Principle I | FR-010, FR-011, SC-002 |
| Position never ahead of what is stored, across partial-failure interleavings | The only failure that loses events *silently* | FR-016, SC-004 |
| Restart resumes from the stored position | Downtime is the normal case on a laptop | FR-017, SC-003 |
| Store unavailable → position does not advance | Data integrity under a dependency outage | FR-018 |
| Backlog drain, in order, no duplicates | Retry safety after a worker outage | FR-020, SC-021 |
| Each of the 5 gap reasons, with correct bounds | The honesty of every later report depends on it | FR-021…FR-025, SC-006, SC-007 |
| ⚠ Jump **under** a week = loss; jump **after** a week = renumbering | Same observable, opposite meaning. Conflating them invents losses or hides them | D-TG-33, SC-008 |
| ⚠ Identifier reset: position moves **backwards**, gap is `unrecoverable=false` | The stall in Finding 1 is invisible without it | FR-019 exception |
| 409 × 5 → stand down, gap row, health shows it; 409 then success → counter resets | Operator's clarified rule; retrying forever loses events on both sides | FR-004a, FR-004b, SC-022 |
| 429 `retry_after` honoured in the provider | Contract at an external boundary | FR-005 |
| Identity unresolvable → stays up, retries, 3 states distinct | Total failure mode; must not read as "no credential" | FR-007a…d, SC-023 |
| Chat discovery, 4 standing changes, `unknown` not guessed | Coverage loss is "the failure most likely to go unnoticed" | FR-026…FR-028, SC-010 |
| Supergroup migration links both directions | The classic Telegram footgun | FR-029, SC-011 |
| ⚠ Health block **contents**, not just status | Probe 3: a status-only assertion cannot detect an empty block | FR-034, SC-013 |
| Readiness identical with and without a credential | The offline gate depends on it | FR-035, SC-016 |
| `tg-doctor` distinguishes 5 setup states; exits 0 with no credential | Operator-facing contract | FR-036, SC-014 |
| No outbound send exists in the change set; no inbound port | The two non-negotiable guarantees | FR-038, SC-015 |
| Migration up **and down** | Principle I names migrations explicitly | FR-044, SC-019 |
| Unknown update kind and no-chat update both stored | Silent discard would be unrecoverable | FR-012 |

**Exempt under Principle I** — recorded so the omissions are deliberate: the poller's sleep loop;
JSON serialisation of the health block; the exact prose of `tg-doctor`'s output; migration
column-type assertions; Dramatiq's own delivery semantics; `httpx`'s own retry behaviour; SQLAlchemy
Core wiring.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

**Yes, and yes.** Unlike TG-M0, this milestone is database-heavy — four tables and every idempotency
guarantee lives in them.

All database tests run against `injaz_ai_test` through `TEST_DATABASE_URL` from `.env.testing`. The
session guard in `tests/conftest.py`, added at M0, already aborts the run if the name lacks `_test`;
this milestone adds no test that bypasses it and changes nothing about it. `tests/moderation/ingest/`
follows `tests/gateway/conftest.py`'s pattern — an async session factory against the test database,
assuming it is already at head, with `make test-db-reset` remaining the operator's step.

No test touches development or imported data. Nothing here runs `migrate:fresh`, and the PHP side is
untouched.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** The source plan's §24 states it for the whole track: *"For v1: none. Nothing in TG-M0…TG-M10
requires a change inside `injazedu/`."* This milestone neither reads nor writes there. The
`injaz_course_id` column is a manual field with **no foreign key** precisely because MySQL is on
another host; it is unused until TG-M2.

### 4. Are there Git actions in the task list? (Principle IV)

**None for the agent.** Branch creation, commits, the pull request and the merge are all operator
steps. `.specify/extensions.yml`'s hooks are surfaced, never executed — the `before_plan` hook was
surfaced and left to the operator, and `setup-plan.sh` was run only for its paths.

Note: `.specify/scripts/bash/check-prerequisites.sh` aborts with *"Not on a feature branch. Current
branch: main"*, because Principle IV means the agent never created one. Paths were resolved from
`.specify/feature.json` instead — the same fallback `/speckit-specify` wrote them to. This is the
constitution winning over a Spec Kit convention, exactly as the Governance clause provides.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

**Yes.** Every artifact traces to an FR (see Requirement → Design Traceability). The source plan's
§25 TG-M1 row is the scope boundary, and research §5 records eight things deliberately **not** built.

One item needs the operator's explicit agreement rather than the agent's judgement, and is escalated
below rather than decided quietly: the **residual data-integrity risk in D-TG-34**.

## Project Structure

### Documentation (this feature)

```text
specs/004-tg-m1-telegram-ingestion/
├── plan.md                        # This file
├── spec.md                        # FR-001…FR-045, SC-001…SC-024, 4 clarifications
├── research.md                    # Phase 0 — 17 decisions D-TG-29…D-TG-45, 10 probes, 3 findings
├── data-model.md                  # Phase 1 — 4 tables, revision 0003, retention shape
├── quickstart.md                  # Phase 1 — operator walkthrough, smoke test, limitations
├── contracts/
│   ├── telegram-provider.md       # THE durable contract: protocol, capability table, error taxonomy, the reset protocol
│   ├── ingestion-guarantees.md    # G1–G6 and the explicit non-promises
│   └── health-ingestion.md        # the health block, its composition-root wiring, tg-doctor
├── checklists/requirements.md     # spec quality checklist (16/16)
└── tasks.md                       # Phase 2 (/speckit-tasks — NOT created by this command)
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── telegram_main.py                     # NEW — poller entrypoint. Composition root: exempt from
│   │                                        #       the reverse boundary check by directory (probe 4)
│   ├── main.py                              # EDIT — composes the ingestion probe onto app.state (D-TG-31)
│   ├── providers/telegram/
│   │   ├── __init__.py                      # exists (TG-M0 skeleton)
│   │   ├── client.py                        # NEW — the only Telegram HTTP calls in the repo
│   │   ├── models.py                        # NEW — TelegramUpdate, BotIdentity, WebhookInfo
│   │   └── errors.py                        # NEW — closed taxonomy, `retryable` flag
│   ├── application/moderation/
│   │   ├── ingest.py                        # NEW — the capture loop: lease, batch, gaps, stand-down
│   │   └── ingestion_probe.py               # NEW — health block; INSIDE the boundary, by necessity
│   ├── workers/tasks/moderation/
│   │   ├── process_update.py                # NEW — the stub: marks processed_at, nothing else
│   │   └── drain_pending_updates.py         # NEW — reconciles the pending index
│   ├── api/v1/health.py                     # EDIT — conditional ProbeSpec from app.state;
│   │                                        #        imports NOTHING from moderation
│   ├── application/health_service.py        # EDIT — `ingestion` as a DECLARED field (probe 3)
│   ├── infrastructure/
│   │   ├── models_moderation.py             # NEW — 4 tables on the shared metadata
│   │   └── config.py                        # EDIT — ~6 settings, additive
│   └── scripts/tg_doctor.py                 # NEW — composition root, exempt by directory
├── alembic/versions/
│   └── 0003_moderation_ingest.py            # NEW — 4 tables, up and down
└── tests/moderation/ingest/                 # NEW test package
    ├── conftest.py                          # FakeTelegramTransport + injaz_ai_test session factory
    ├── test_idempotency.py  test_offset.py  test_gaps.py  test_reset.py
    ├── test_conflict_standdown.py  test_identity.py
    ├── test_chats.py  test_migration_supergroup.py
    ├── test_drain.py  test_health_block.py  test_tg_doctor.py
    └── test_no_outbound.py                  # asserts no send/react/delete/ban method exists

infra/docker-compose.yml                     # EDIT — one `ai-telegram` service, mem_limit: 256m, no ports:
Makefile                                     # EDIT — `tg-doctor`
.env.example                                 # EDIT — the new settings with defaults
CLAUDE.md / AGENTS.md                        # EDIT — active-feature pointer (identical files)
```

**Structure Decision.** The four moderation package directories TG-M0 created are filled in, with no
new top-level tree. Three placements are load-bearing rather than stylistic:

- **`app/telegram_main.py` at the `app/` root**, beside `app/main.py`. Probe 4 confirms `app/` root is
  outside the reverse check's scope, so the entrypoint may wire moderation and shared infrastructure
  together exactly as `app/main.py` and `app/workers/` already do.
- **`ingestion_probe.py` inside `app/application/moderation/`**, not in `app/application/probes/`.
  The natural placement fails the gate (Finding 2). See `contracts/health-ingestion.md` §0.
- **`models_moderation.py` in `app/infrastructure/`**, on the shared metadata. That directory is
  outside the reverse check's scope, and `app.infrastructure` is one of the seven prefixes moderation
  may import — so it is shared infrastructure by both the gate's definition and the contract's, the
  same status `models.py` has.

## ⚠ Two Items for the Operator

Neither blocks starting work; both should be agreed before merge.

**1. FR-019 is corrected, not merely implemented.** The approved spec says the confirmed position
*"MUST never move backwards."* Telegram's documented behaviour makes that requirement, read literally,
cause permanent silent capture failure after a week of quiet (research Finding 1). The design gives it
**one** documented exception, gated behind stall detection and recorded as its own gap reason. The
spec text stands; `contracts/telegram-provider.md` §5 and `contracts/ingestion-guarantees.md` G2 carry
the exception. Flagged because an agent narrowing an approved requirement on its own would be a
Principle V violation — this widens it, for a measured reason, and the operator should say so
explicitly.

**2. D-TG-34 accepts a small, permanent data-integrity risk.** After an identifier reset, a genuinely
new event whose randomly chosen `update_id` collides with one already stored is **silently dropped**
by `ON CONFLICT DO NOTHING` (probe 9 confirms the mechanism). The obvious fix — an `id_epoch` column
in the uniqueness key — was rejected because it makes G1, the milestone's most important guarantee,
depend on that counter never advancing spuriously: a detection bug would then turn every redelivered
update into a duplicate row and corrupt every count downstream. Trading a rare failure for a likelier
one is the wrong trade, but it *is* a trade, and it concerns data integrity — so Principle V says
present it rather than decide it. Requires a full week of total silence **and** a random landing inside
an already-used range.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

**No violations.** All five gate questions pass.

Five choices that *look* like added complexity, recorded because a reviewer will ask:

| Choice | Why it is not gratuitous |
|---|---|
| A fifth container | §7.3 requires the offset's holder to be separate from anything that interprets. Sharing the `ai-api` image means no new build, and 256 MB against a 5 GB budget. Folding it into `ai-worker` would put a 30 s blocking poll in a worker slot and let Dramatiq's retries fight the offset's own recovery |
| Two layers of single-consumer enforcement | They catch different things. The Redis lease stops a stray second container on **this** machine before one event is lost; Telegram's `409` is the only authority **across** machines and only fires after a poll has already been terminated. Neither substitutes for the other |
| Five gap reasons where the plan named four | `update_id_reset` is a renumbering, not a loss. Folding it into `update_id_jump` would mark a complete window "incomplete" — dishonest in the opposite direction from the one this domain guards against |
| A `process_update` actor that does almost nothing | It proves the handoff, the ordering and the drain end-to-end **now**, while there is nothing else to blame. TG-M2 fills in the body against an already-verified pipeline |
| A test asserting the absence of methods | Ordinarily untestable-by-absence is a smell. Here silence is a headline guarantee (FR-038) whose violation is a visible incident in a real student group, and the assertion is cheap |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 (research.md, data-model.md, contracts/, quickstart.md).*

**RESULT: PASS — strengthened, with one escalation.**

| Gate | Pre-design | After design | Change |
|---|---|---|---|
| I — Risk-proportional testing | 14 tested behaviors | 19, after probes 3, 4 and 7 exposed three silent-failure modes no obvious test would have caught | **Strengthened** |
| II — Test DB isolation | Inherits M0's `_test` guard | Confirmed: this milestone is database-heavy, and every new test routes through `TEST_DATABASE_URL`. Surface is larger than TG-M0's, and the existing guard covers all of it unchanged | Unchanged, larger surface |
| III — `injazedu/` read-only | No writes | Confirmed: neither read nor written. §24 states it for the whole track | Unchanged |
| IV — Git operator-owned | Branch and commits are operator steps | Unchanged — and the prerequisite script's branch-name abort is itself evidence the agent created none | Unchanged |
| V — Approved scope | Traceable to the §25 TG-M1 row | Research §5 declines eight items. **One escalation**: D-TG-33 widens FR-019, and D-TG-34 accepts a data-integrity risk — both surfaced above rather than absorbed | **Escalated, per Principle V** |

**Three things a reviewer should look at deliberately:**

1. **Finding 1 is a correction to the approved spec, not an implementation detail.** FR-019 as
   written guarantees a permanent, silent, green-looking capture failure after a week of quiet. The
   correction is small and documented, but it is the kind of change Principle V says to present.
2. **Finding 2 means the source plan's own "Repo areas" row is not buildable as written.** §25 TG-M1
   lists the health work without noting that the natural placement violates TG-M0's boundary. The
   design routes around it through the composition root; the reviewer should confirm that is
   preferable to widening the gate's allowlist, because the alternative was available and was refused.
3. **Probe 3's failure mode will recur.** `ComponentReport` accepts and drops unknown fields, so any
   future milestone adding a health block the obvious way gets a silently empty one. Declaring
   `ingestion` fixes this instance; `contracts/health-ingestion.md` §1 records the trap so TG-M6's
   alerting block does not rediscover it.

## Requirement → Design Traceability

| Spec requirements | Where the design answers them |
|---|---|
| FR-001…FR-003 (outbound-only, separate process, local exclusion) | `contracts/ingestion-guarantees.md` G5; D-TG-29, D-TG-37; Project Structure |
| FR-004…FR-004b (conflict stand-down) | `contracts/telegram-provider.md` §4, §6; D-TG-37; `data-model.md` §2 |
| FR-005…FR-005b (rate limit, batch ceiling, drain) | `contracts/telegram-provider.md` §4, §6; D-TG-40 |
| FR-006, FR-041 (subscription set, settings) | `contracts/telegram-provider.md` §3; D-TG-41; `data-model.md` §2 |
| FR-007…FR-007d (optional credential, identity resolution) | `contracts/ingestion-guarantees.md` G6; `contracts/health-ingestion.md` §1; D-TG-42 |
| FR-008…FR-014 (the event record) | `data-model.md` §1; D-TG-30, D-TG-35 |
| FR-015…FR-020 (position, ordering, recovery) | `contracts/ingestion-guarantees.md` G1–G3; `data-model.md` §2; D-TG-33, D-TG-36 |
| FR-021…FR-025 (unobserved windows) | `contracts/ingestion-guarantees.md` G4; `data-model.md` §3; D-TG-33, D-TG-38 |
| FR-026…FR-031 (chats, coverage, migration) | `data-model.md` §4; D-TG-43, D-TG-44 |
| FR-032…FR-033 (interpretation stub) | `data-model.md` §1 `processed_at`; D-TG-36 |
| FR-034…FR-037 (observability) | `contracts/health-ingestion.md` §1–§3; D-TG-31, D-TG-32 |
| FR-038…FR-040, FR-042…FR-043 (safety, boundary, offline gate) | `contracts/telegram-provider.md` §0, §8; `contracts/ingestion-guarantees.md` G5 |
| FR-044…FR-045 (migration, DB-enforced idempotency) | `data-model.md` §1, §7; probes 1 and 10 |

Every FR is claimed by at least one design artifact; no design artifact exists without an FR.

## Phase Status

- [x] Phase 0 — research complete (17 decisions D-TG-29…D-TG-45, 10 probes, **3 findings**, 0 unresolved NEEDS CLARIFICATION)
- [x] Phase 1 — data model, 3 contracts, quickstart, agent context updated
- [x] Constitution Check — pre-design PASS, post-design PASS (strengthened)
- [ ] Phase 2 — task breakdown (`/speckit-tasks`, not produced by this command)
- [ ] ⚠ **Operator agreement outstanding** — the two items above: FR-019's documented exception, and
      D-TG-34's accepted residual risk.
- [ ] ⚠ **Operator prerequisite outstanding** — runbook §B in full (both bots created with privacy
      disabled *before* the first group add, dev group with two extra accounts, bot promoted to
      administrator, dev credential in `.env`). Development and every automated test proceed without
      it; only the smoke test blocks.
