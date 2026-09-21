# Implementation Plan: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Branch**: `m2/moderator-ownership` *(operator-created — Constitution IV)* | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-tg-m2-groups-and-ownership/spec.md`
**Source plan**: `docs/plan/telegram/telegram-moderation-intelligence.md` (§9, §10.3–10.6, §12, §13.4, §15.4, §17, §19.2, §20.2, §22, §23, §24, §25 TG-M2)
**Operator runbook**: `docs/runbooks/tg-operator-prerequisites.md` (§C TG-M2 row; §B still holding from TG-M1)

## Summary

TG-M2 turns TG-M1's captured stream into **facts a person can be held to**. It ships **four tables in
one migration, two derivation modules, one worker body, one operator command, two screens** — and
judges nothing.

The approach is narrow in one direction and uncompromising in another. Narrow: only `message`,
`edited_message` and `my_chat_member` are interpreted; reactions and membership changes stay stored for
TG-M4. Uncompromising: **every attribution is a snapshot and every snapshot is write-once.** Ownership
is an interval, not a current value; the moderator flag is written at insert and never recomputed;
derivation is insert-only so a replay cannot rewrite either. That is not caution — a current-owner
column, once overwritten, has destroyed the only record of who to ask, and a live moderator lookup
silently improves every historical number in the direction nobody would question.

**Four probes changed the design rather than confirming it.** Each would have shipped as a silent
failure — no exception, no failing test, a screen that looks right:

1. ⚠ **Per-navigation-group text direction does not exist in this framework, so FR-051 cannot be
   implemented as written.** Filament v5.7.8 writes `dir` once onto `<html>` from a single
   locale-driven translation key. Switching to `ar` turns the *whole* panel RTL and translates its
   chrome — which FR-051's second half forbids. Resolution: per-field `dir="auto"`, locale untouched
   (D-TG-56). **This narrows an approved requirement's mechanism; see the operator note below.**
2. ⚠ **Two timestamps in one reassignment open a hole in ownership history that nothing detects.**
   Measured: two clock readings leave a ~10 ms window with **zero** owners. No constraint fires;
   `responsible_at` reports "nobody responsible", which a later milestone renders as a coverage problem
   that never existed. It is a PHP-side hazard — the panel is the writer, and Laravel's `now()` is
   evaluated per call, so the natural Filament code has the bug (D-TG-47).
3. ⚠ **TG-M1's supergroup migration leaves the new chat row unmeasured, so a group silently stops being
   measured when it is promoted.** `apply_chat_migration_if_any` writes only the two linking columns, so
   the surviving row is created at `is_monitored = false`. Capture stays green and derivation correctly
   stops. TG-M1 could not have caught this — it derives nothing. Resolution: the re-point carries the
   opt-in and course reference forward (D-TG-54).
4. ⚠ **A re-derivation of older events would overwrite a sender's current display name with a stale
   one**, and drag `last_seen_at` backwards, which a coverage read reports as a group having gone quiet.
   Also a hazard TG-M1 could not have had: it never replayed anything. Resolution: `LEAST`/`GREATEST`
   on the timestamps and a guarded name write, in one statement (D-TG-51).

Two further probes narrowed the work rather than redirecting it. A partial unique index **cannot be
deferred** (`ERROR: syntax error at or near "DEFERRABLE"`), which is what forces close-before-open in
every handover. And `ALTER DEFAULT PRIVILEGES` already grants the panel's role DML on anything the
migrator creates, in both databases — so the revision adds no `GRANT`, and this is the first milestone
where that mattered, since TG-M1 shipped no screens.

## Technical Context

**Language/Version**: Python 3.12 (unchanged) · PHP 8.2 / Laravel 12 / **Filament v5.7.8** — the panel's
first substantial change since M1
**Primary Dependencies**: **none added, either side.** SQLAlchemy Core, Alembic, Dramatiq,
`pydantic-settings`; Eloquent and Filament as installed. ⚠ **No Telegram SDK, no new PHP package**
**Storage**: Postgres — 4 new tables in revision **`0004_moderation_actors`** (head confirmed `0003`,
probe 10); **0 altered tables, 0 grants**. Redis — untouched by this milestone
**Testing**: pytest offline by default, new package `tests/moderation/actors/` reusing TG-M1's
`FakeTelegramTransport` fixtures for update shapes; PHPUnit Feature tests with `DatabaseTransactions`
against `injaz_ai_test`, as `ModelProfileResourceTest` already does
**Target Platform**: macOS 26.6 on Apple Silicon (M1 Pro, 16 GB), local-only, still **no inbound port**
**Project Type**: Multi-service local application — Python service (API + worker + poller) + PHP control
panel. This is the first milestone to change both sides in one change set
**Performance Goals**: none of consequence for live derivation — low hundreds of messages per day. The
one volume-sensitive path is re-derivation, bounded at 500 captured events per batch
**Constraints**: no question recognised, no item opened, no duration computed, no model call · no
message sent, reaction set, message deleted, member removed or restricted · no inbound port · every
test offline and credential-free · no import across the moderation/assessment boundary · no message
text on a logging line · no schema change from the panel · zero writes inside `injazedu/`
**Scale/Scope**: 4 tables, 1 migration, ~6 new Python modules, 1 operator command, 2 Filament resources
+ 1 relation manager, 1 one-line edit to existing panel code, 1 new setting, ~55 focused tests, 0 model
calls

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested — the invariants, the write-once guarantees, and the four measured failure modes:**

| Behavior | Why it earns a test | Covers |
|---|---|---|
| Same captured event derived 3× → one row, identical values | Idempotency, named in Principle I | FR-002, SC-001 |
| ⚠ Moderator flag unchanged by a later mapping, unmapping **and** deactivation | Silent retroactive rewrite, in the flattering direction | FR-033, SC-011 |
| ⚠ Re-derivation is insert-only: an existing row is untouched | Same mechanism as above; an upsert would break it invisibly | D-TG-49, SC-006 |
| Edit updates text + `edited_at` only; `sent_at` and the flag survive | FR-010 and FR-033 must not fight | FR-010, SC-005 |
| ⚠ Reassign leaves exactly **one** owner **at the exact handover instant** | Finding 2 — a gap fires no constraint and looks correct | FR-037, SC-013 |
| Reassign with a failure induced partway → incumbent still current, no successor open | Atomicity is the point of the transaction | FR-037, SC-013 |
| Second current primary → constraint failure, no partial rows | The partial unique index, attempted directly | FR-036, SC-012 |
| `responsible_at` at the **4 boundary positions**, not near them | An off-by-one here is a plausible wrong answer at the disputed moment | FR-044, SC-014 |
| `responsible_at` returns nothing for an uncovered instant; never the current owner | Attributing a past miss to someone absent | FR-042, SC-015 |
| A past answer is unchanged after 2 later handovers | O5 — the contract's whole purpose | FR-043, SC-016 |
| Closed intervals never deleted or rewritten across 3 handovers | The history is the product | FR-038, SC-018 |
| ⚠ Migration re-point carries `is_monitored` forward; closes/opens 0 intervals | Finding 3 — measurement stops silently without it | FR-052, SC-019 |
| Re-point into a destination with a current primary → refuses | Probe 8; guessing a winner discards a fact | D-TG-54 |
| ⚠ Identity upsert: stale replay does not clobber the name or reverse `last_seen_at` | Finding 4 — wrong row, no error, until they post again | FR-015, SC-010 |
| Placeholder created, then filled by first observation, 0 second identities | The runbook's normal path | FR-027, FR-028, SC-009 |
| Unmeasured chat → 0 messages, 0 identities, event still marked handled | The opt-in would otherwise be advisory | FR-019, SC-003 |
| Re-derivation: refuses unmeasured, reports 3 counts, purged → skipped, 2nd run derives 0 | FR-020…FR-023 | SC-006, SC-007, SC-008 |
| `is_from_moderator` false for a bot and for a senderless message, enforced by the database | The flattering guess on the least certain data | FR-017, D-TG-60 |
| The 6 message shapes each stored correctly, 0 discarded | An unmodelled shape must never lose a message | FR-005…FR-009, SC-004 |
| Backlog handed over in order, 0 duplicates | Retry safety after a worker outage | FR-013, SC-024 |
| Migration up **and down** | Principle I names migrations explicitly | FR-068, SC-030 |
| The 4 database invariants, each violated directly | FR-069 is a claim about the store, not the app | SC-031 |
| Panel: no platform call, no schema change, no job started by the toggle | Standing prohibitions, cheap to assert | FR-050, SC-022 |
| Retention markers present; removing a name/text leaves timings intact; moderator names exempt | Shape now, job later — the shape must be right | FR-055…FR-057, SC-025 |

**Exempt under Principle I** — recorded so the omissions are deliberate: Filament table rendering,
pagination, sorting, filtering and form validation messages; navigation-group placement; help-text
wording; Eloquent attribute casting; migration column-type assertions; Dramatiq delivery semantics;
SQLAlchemy Core wiring; the normaliser itself (tested at TG-M0).

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

**Yes, on both sides, and yes.** This is the most database-heavy milestone so far and the first where
the PHP side writes moderation tables.

Python: `tests/moderation/actors/` against `injaz_ai_test` via `TEST_DATABASE_URL` from `.env.testing`,
under M0's session guard in `tests/conftest.py`, which aborts the run if the name lacks `_test`. No new
test bypasses it and nothing about it changes.

PHP: `DatabaseTransactions` against `injaz_ai_test`, exactly as `ModelProfileResourceTest` does —
never `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh` (FR-070, SC-034). `phpunit.xml`
deliberately takes the connection from `.env.testing` rather than sqlite, so the guard is real rather
than bypassed by an in-memory database.

Research probes touched only `injaz_ai_test`, every one inside `BEGIN … ROLLBACK`, leaving no schema
behind. No development or imported data was read or written.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** The source plan's §24 states it for the whole track. This milestone is the first consumer of
`telegram_chats.injaz_course_id` and `moderators.injaz_user_id`, and **both are deliberately
FK-less, unvalidated, operator-entered values** — precisely because the system they name is on another
host and is read-only. Nothing reads across the boundary and nothing writes into that directory.

### 4. Are there Git actions in the task list? (Principle IV)

**None for the agent.** The branch `m2/moderator-ownership` was created by the operator; commits, the
pull request and the merge are operator steps. `.specify/extensions.yml`'s `before_plan` hook was
**surfaced and left unexecuted**, and `setup-plan.sh` was run only for its paths.

Note that `setup-plan.sh` reported `BRANCH: m2/moderator-ownership` without objection this time,
because the operator had already created a branch — unlike TG-M1, where the prerequisite script's
"Not on a feature branch" abort was itself evidence the agent had created none.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

**Yes.** Every artifact traces to an FR (see Requirement → Design Traceability), and research §4
records ten things deliberately **not** built.

One item needs the operator's explicit agreement rather than the agent's judgement and is escalated
below rather than decided quietly: **FR-051's mechanism is changed, because the approved one does not
exist in the installed framework.**

## Project Structure

### Documentation (this feature)

```text
specs/005-tg-m2-groups-and-ownership/
├── plan.md                             # This file
├── spec.md                             # FR-001…FR-070, SC-001…SC-035, 3 clarifications
├── research.md                         # Phase 0 — 24 decisions D-TG-46…D-TG-69, 10 probes, 4 findings
├── data-model.md                       # Phase 1 — 4 tables, revision 0004, the handover SQL, retention shape
├── quickstart.md                       # Phase 1 — operator walkthrough, smoke test, 10 known limitations
├── contracts/
│   ├── moderator-ownership.md          # THE durable contract: interval algebra, handover protocol,
│   │                                   #   responsible_at with O1–O5, attribution rules, non-promises
│   ├── message-derivation.md           # the two write modes, the snapshot and its limits, re-derivation, G-D1–G-D7
│   └── control-panel-moderation.md     # the two screens, navigation, the RTL finding, what the panel may not do
├── checklists/requirements.md          # spec quality checklist (16/16)
└── tasks.md                            # Phase 2 (/speckit-tasks — NOT created by this command)
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── application/moderation/
│   │   ├── messages.py                      # NEW — derivation: the two write modes, per-field rules
│   │   ├── identities.py                    # NEW — the one replay-safe sender upsert (Finding 4)
│   │   ├── assignments.py                   # NEW — responsible_at, the handover, the migration re-point
│   │   └── ingest.py                        # EDIT — re-point hook after apply_chat_migration_if_any
│   ├── workers/tasks/moderation/
│   │   └── process_update.py                # EDIT — the stub's body filled in; its contract unchanged
│   ├── scripts/rederive_chat.py             # NEW — the operator command. Composition root: exempt from
│   │                                        #       the boundary checks by directory, as tg_doctor.py is
│   ├── infrastructure/
│   │   ├── models_moderation.py             # EDIT — 4 tables appended to the same metadata
│   │   └── config.py                        # EDIT — 1 setting, additive
├── alembic/versions/
│   └── 0004_moderation_actors.py            # NEW — 4 tables, 4 indexes, up and down
└── tests/moderation/actors/                 # NEW test package
    ├── conftest.py                          # reuses TG-M1's update fixtures + the injaz_ai_test factory
    ├── test_derivation.py     test_idempotency.py    test_edits.py
    ├── test_identities.py     test_placeholders.py
    ├── test_assignments.py    test_responsible_at.py test_handover_atomicity.py
    ├── test_migration_repoint.py             # Finding 3
    ├── test_unmonitored.py    test_rederive.py
    ├── test_retention_shape.py
    └── test_migration_0004.py                # up and down

apps/ai-control/
├── app/Models/
│   ├── TelegramChat.php                     # NEW
│   ├── Moderator.php                        # NEW
│   └── ModeratorGroupAssignment.php         # NEW — the handover lives HERE, not in the action (D-TG-58)
├── app/Filament/Resources/
│   ├── ModelProfiles/ModelProfileResource.php   # EDIT — one line: $navigationGroup = 'Platform'
│   ├── TelegramChats/{TelegramChatResource,Pages,Schemas,Tables}
│   └── Moderators/{ModeratorResource,Pages,Schemas,Tables,RelationManagers}
└── tests/Feature/
    ├── TelegramChatResourceTest.php
    ├── ModeratorResourceTest.php
    └── AssignmentHandoverTest.php            # Finding 2 — asserts owners AT the handover instant

.env.example                                 # EDIT — the one new setting with its default
CLAUDE.md / AGENTS.md                        # EDIT — active-feature pointer (identical files)
```

**Structure Decision.** No new top-level tree on either side. Three placements are load-bearing rather
than stylistic:

- **`assignments.py` in `app/application/moderation/`**, holding `responsible_at` as the single Python
  definition. The Eloquent scope mirrors it; both are boundary-tested. A database view was rejected
  (D-TG-48): it would need re-creating in a later revision the first time a metric query wanted a
  different shape, and the predicate is four tokens.
- **`rederive_chat.py` in `app/scripts/`**, not in the moderation package. It must import both
  moderation modules and shared infrastructure, which is exactly the composition-root standing
  `app/scripts/` already has: check.sh's forward allowlist does not scan that directory and its reverse
  rule exempts it. Same standing as `tg_doctor.py`.
- **The handover on `ModeratorGroupAssignment`, not in the Filament action.** Directly mirroring
  `ModelProfile::save()`, which enforces its invariant at the model layer *"so they hold regardless of
  entry point (panel, tinker, a future artisan command) — not only when a Filament form happens to be
  in front of them."* Finding 2's hole is reachable from `tinker` otherwise.

## ⚠ One Item for the Operator

Does not block starting work; should be agreed before merge.

**FR-051's mechanism is changed, because the approved one does not exist.** The spec says the new
navigation group's reading direction must suit the operator's language **and must not alter the rest of
the panel**. Filament v5.7.8 writes `dir` once onto `<html>` from a single locale-driven translation key
(`base.blade.php:16`), so there is no per-group direction: satisfying the first half by switching the
locale to `ar` violates the second half, turning the whole panel RTL and translating its chrome
including the model-roster screen.

The design instead sets `dir="auto"` on the Arabic-content fields and leaves the locale alone
(D-TG-56). This satisfies what FR-051 was protecting — Arabic titles that read correctly, with
punctuation in the right place — and is arguably better than the requested `rtl` even where `rtl` were
available, because the plan's own §17 example lists *"الرخصة المهنية"* beside *"STEP"* and `auto` picks
per value.

Flagged because the *outcome* is narrower than the approved text: the panel chrome stays English and
left-to-right. An agent quietly reinterpreting an approved requirement would be a Principle V
violation; the alternative — switching the locale — was available and was refused, and the operator
should say which they want. The source plan's §17 will also need a one-line correction, since it
asserts a capability the framework does not have.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

**No violations.** All five gate questions pass.

Five choices that *look* like added complexity, recorded because a reviewer will ask:

| Choice | Why it is not gratuitous |
|---|---|
| Time-versioned ownership from day one, rather than a current-owner column | It is the one thing here that **cannot** be added later: once the current value is overwritten, the previous owner is unrecoverable and every historical report is quietly wrong. It costs two columns and one partial index |
| `is_from_moderator` denormalised onto every message | The source plan's §10.6 calls it deliberate. A live lookup would convert last month's student questions into last month's moderator answers on every promotion — invisibly, and in the flattering direction |
| Two write modes for one table (insert-only, and a targeted edit update) | They are what keep FR-002, FR-010 and FR-033 from fighting. Probes 6 and 7 measured both. Collapsing them into an upsert breaks the write-once guarantee with no error |
| The handover invariant duplicated in Python and Eloquent | The panel is the writer and the worker is the reader; each needs the predicate in its own language. Both are boundary-tested against the same four positions, and the database backstops both |
| An operator command rather than a screen toggle for catching a group up | The operator chose it in this session's clarification. It is also the only action in the milestone with real data volume, and a switch that silently starts a bulk job over retained student messages is the wrong shape for that |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 (research.md, data-model.md, 3 contracts, quickstart.md).*

**RESULT: PASS — strengthened, with one escalation.**

| Gate | Pre-design | After design | Change |
|---|---|---|---|
| I — Risk-proportional testing | 16 tested behaviors | 25, after four probes exposed failure modes no obvious test would have caught — three of them measured against the live stack | **Strengthened** |
| II — Test DB isolation | Inherits M0's `_test` guard | Confirmed on **both** sides: Python through `TEST_DATABASE_URL`, PHP through `DatabaseTransactions` on `injaz_ai_test`. Every research probe ran inside `BEGIN … ROLLBACK` and left no schema | Unchanged, larger surface |
| III — `injazedu/` read-only | No writes | Confirmed, and *strengthened*: this milestone is the first consumer of both cross-system reference columns, and both are deliberately FK-less and unvalidated so no read crosses the host boundary | Unchanged |
| IV — Git operator-owned | Branch and commits are operator steps | Unchanged. The `before_plan` hook was surfaced, not executed | Unchanged |
| V — Approved scope | Traceable to the §25 TG-M2 row | Research §4 declines ten items. **One escalation**: FR-051's mechanism is changed because the approved one does not exist in Filament v5.7.8 | **Escalated, per Principle V** |

**Three things a reviewer should look at deliberately:**

1. **Finding 2 is the one to test adversarially.** A reassignment written the natural way in Filament
   leaves a microsecond hole in ownership history, and nothing in the stack objects: no constraint, no
   exception, and a screen that reads correctly. `AssignmentHandoverTest` must assert owners **at** the
   handover instant, not near it, and must assert that the two timestamps are the *identical value*.
   Every other guarantee in `moderator-ownership.md` §3 rests on this one.
2. **Finding 3 means TG-M1 shipped a latent defect that only acquires consequences here.**
   `apply_chat_migration_if_any` creates the surviving chat row at `is_monitored = false`. That was
   harmless while nothing derived; from this milestone on, a group stops being measured at the moment it
   is promoted, with every health signal green. The fix belongs in this change set, and the reviewer
   should confirm it is the re-point's job rather than a patch to TG-M1's discovery path — it is, because
   only the re-point knows which row survives.
3. **The moderator-flag snapshot will look like a bug to whoever reads the first transcript spanning a
   promotion.** It is the correct record, and the reason is worth internalising before someone "fixes"
   it: the alternative improves every historical number in the direction nobody would question.
   `message-derivation.md` §5 and `quickstart.md` §7 both state it; a reviewer should check that the
   *screens* do not quietly contradict them.

## Requirement → Design Traceability

| Spec requirements | Where the design answers them |
|---|---|
| FR-001…FR-004, FR-013 (typed messages, the platform's time, reply target) | `contracts/message-derivation.md` §3, §8; `data-model.md` §2; D-TG-61 |
| FR-005, FR-006, FR-009, FR-017 (sender forms, service, no text, bots) | `data-model.md` §2 constraints; D-TG-60, D-TG-63 |
| FR-002, FR-007, FR-008, FR-010 (idempotency, flags, normalisation, edits) | `contracts/message-derivation.md` §2; `data-model.md` §2; D-TG-49, D-TG-50 |
| FR-011, FR-012 (which kinds, which process) | `contracts/message-derivation.md` §1; D-TG-61 |
| FR-014…FR-017 (sender identities, pseudonyms) | `data-model.md` §1; D-TG-51 |
| FR-018…FR-024 (measurement, re-derivation) | `contracts/message-derivation.md` §6, §7; D-TG-53, D-TG-64 |
| FR-025…FR-031 (moderators, placeholders, candidates) | `data-model.md` §3; D-TG-52, D-TG-62 |
| FR-032…FR-034 (the snapshot and its limits) | `contracts/message-derivation.md` §5; D-TG-49, D-TG-59, D-TG-60 |
| FR-035…FR-040 (intervals, one current primary, atomic handover) | `contracts/moderator-ownership.md` §1, §2; `data-model.md` §4, §4.1; D-TG-47, D-TG-58 |
| FR-041…FR-044 (responsibility at an instant) | `contracts/moderator-ownership.md` §3 (O1–O5); `data-model.md` §4.2; D-TG-48 |
| FR-045…FR-051 (the screens) | `contracts/control-panel-moderation.md` §0–§3; D-TG-56, D-TG-57, D-TG-66 |
| FR-052…FR-054 (migration continuity, coverage loss) | `contracts/moderator-ownership.md` §6; `data-model.md` §4.3; D-TG-54, D-TG-55, D-TG-65 |
| FR-055…FR-058 (retention shape) | `data-model.md` §1, §2 retention shape |
| FR-059…FR-067 (safety, boundary, offline gate) | `contracts/control-panel-moderation.md` §4; research §4; D-TG-61, D-TG-67, D-TG-68 |
| FR-068…FR-070 (migration, DB-enforced invariants, test isolation) | `data-model.md` §6; D-TG-46, D-TG-69; probes 9 and 10 |

Every FR is claimed by at least one design artifact; no design artifact exists without an FR.

## Phase Status

- [x] Phase 0 — research complete (24 decisions D-TG-46…D-TG-69, 10 probes, **4 findings**, 0 unresolved NEEDS CLARIFICATION)
- [x] Phase 1 — data model, 3 contracts, quickstart, agent context updated
- [x] Constitution Check — pre-design PASS, post-design PASS (strengthened)
- [ ] Phase 2 — task breakdown (`/speckit-tasks`, not produced by this command)
- [ ] ⚠ **Operator agreement outstanding** — FR-051's changed mechanism, and the one-line correction it
      implies for the source plan's §17.
- [ ] ⚠ **Operator prerequisite outstanding** — the runbook's §C TG-M2 row: the operator's own numeric
      Telegram id and those of the two test accounts. Development and every automated test proceed
      without them; only the smoke test blocks. §B from TG-M1 must still hold.
