# Implementation Plan: TG-M4 — Policy Incidents

**Branch**: `m4/policy-incidents` *(operator-created; Principle IV)* | **Date**: 2026-09-24
**Spec**: [`spec.md`](./spec.md) · **Research**: [`research.md`](./research.md) ·
**Data model**: [`data-model.md`](./data-model.md) ·
**Contracts**: [`incident-lifecycle.md`](./contracts/incident-lifecycle.md) ·
[`incident-metrics.md`](./contracts/incident-metrics.md) ·
[`control-panel-incidents.md`](./contracts/control-panel-incidents.md) ·
**Quickstart**: [`quickstart.md`](./quickstart.md)
**Milestone**: TG-M4 of `docs/plan/telegram/telegram-moderation-intelligence.md` §25

## Summary

An operator flags a message; the incident is dated both when it was posted and when it was flagged, and
attributed to whoever owned the group at the flag. From then on the platform's own attributable facts —
a moderator's reaction or direct reply, and the ban, expulsion or restriction of the sender — decide
what happened, and **seeing is never acting**: acknowledgement cannot resolve anything. The operator can
confirm what the platform cannot see and withdraw a false flag. Three timings, handled versus missed,
and the system's own latency are computed from stored facts, reproducible by hand.

The design's central choice, forced by research Finding 3: **an incident stores only what was decided
when it was flagged.** Its status, moments and timings are a pure function of append-only evidence,
defined once as two SQL views that Python and PHP both read. That is the only arrangement in which
FR-043/FR-044's "one matcher, including for evidence recorded before the flag" holds when the opener is
the PHP panel, and in which FR-045's order-independence holds without a column that is rewritten. Human
acts are guarded inserts under one advisory lock shared by both languages.

Four measured facts shaped the design (`research.md` §0): the platform puts a fake `from` on every
message sent on behalf of a chat and TG-M2's constraint rejects that row, so channel spam is never
stored; the running panel's percentile floor is zero because of an empty environment variable, a trap
the new incident ceiling would fall into too; the panel cannot run the Python matcher, and TG-M3's own
hand-open already shows the resulting disagreement; and no membership change or reaction has ever been
captured, so every payload shape is pinned by tests against the reference. Two further probes ran the
views and the figure SQL exactly as written against a scripted scenario and matched hand computation.

## Technical Context

**Language/Version**: Python 3.12 (`apps/ai-api`), PHP 8.3 / Laravel 12.69.1 (`apps/ai-control`)
**Primary Dependencies**: SQLAlchemy 2 Core (async), Alembic, Dramatiq 2.2.1 + Redis broker,
Filament v5.7.8. **No new dependency on either side.**
**Storage**: PostgreSQL 16.15 — revision `0006_moderation_incidents`, down-revision `0005` (head in both
databases): 2 tables, 2 views, no alter
**Testing**: pytest against `injaz_ai_test` via `TEST_DATABASE_URL`; PHPUnit with `DatabaseTransactions`
against the same database. No credential, no network, no model runtime in any of it
**Target Platform**: the existing local Docker stack. No new service, no new actor, no tick change
**Project Type**: two applications in one repository — Python service plus PHP control panel
**Performance Goals**: not a throughput milestone. Incidents are hand-opened (dozens per pilot); evidence
is every membership change plus moderators' reactions in measured groups (hundreds). The state view is
five `LATERAL … LIMIT 1` lookups per incident over indexed branches; the source plan's §31 forbids
materialising before a query is measured slow
**Constraints**: no model call, no outbound message, no inbound endpoint, no bot action, no message text
in any log line or in either new table; the panel computes no state
**Scale/Scope**: ~5 moderators, a handful of groups. Small enough that each timing's p90 floor (10
samples) will bite routinely — suppression is per timing, on its own count

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 below.*

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested** — every row protects a business rule, an idempotency guarantee, or metric arithmetic:

| Area | Test | Why it earns one |
|---|---|---|
| Membership classifier | every documented status pair × performed-by-self/other → kind, strength or nothing | **Finding 4**: no live payload has ever been seen; the table is the only proof |
| Reaction delta | added vs removed vs unchanged; `actor_chat` only; custom and paid reactions | V7–V8 |
| Evidence recording | moderator reaction → row with `actor_moderator_id`; non-moderator → none; unmeasured group → none; later promotion leaves the row unchanged | FR-011, FR-013, FR-015 |
| Evidence idempotency | same captured event ×3 → one row | FR-019, replay |
| Channel messages | a real payload with fake `from` + `sender_chat` → stored, no personal sender | **Finding 1** |
| Anchor | two chats, same message number → two incidents; same anchor twice → one; service message refused | FR-002, FR-007 |
| Opening | `opened_at` = `sent_at`, `detected_at` = now, labels required, operator provenance | FR-003…FR-006 |
| Attribution | owner at **detection**; reassign after → unmoved; no owner → NULL, visible | FR-046…FR-048 |
| Lifecycle | every permitted transition via evidence; every forbidden one changes nothing | SC-003 |
| Acknowledgement never resolves | all combinations of replies, reactions and panel acks, up to 20 rows | **the milestone's acceptance** |
| Direct resolution | ban with no prior ack → resolved; ack time absent | FR-028, SC-004 |
| Linkage | wrong member, wrong group, before posting, sender's own evidence → nothing; one ban → three incidents | FR-016, FR-025, FR-030, FR-031 |
| Lineage | incident in the old chat, ban in the promoted chat → resolved | FR-082, probe 8 |
| Pre-flag evidence | reaction/ban before the flag → state moves, "acted before flagging", no negative | the first clarification |
| Order independence | same evidence inserted in three orders → identical state and timings | FR-045 |
| Closure precedence | closure after resolution is impossible through the guard; a ban captured after a closure leaves it closed | FR-041, H5, probe 8 |
| Non-moderator performer | unmapped admin / bot / anonymous → resolved, nobody credited | FR-032 |
| Metric arithmetic | fixed fixture, hand-computed outcomes and three timings; per-timing suppression; late resolution stays missed; FP excluded; latency never per moderator; NULL ≠ 0 | FR-051…FR-066 |
| Panel guards | acknowledge only from open; resolve/close only from open or acknowledged; double submit inserts once; stale page inserts nothing | FR-034…FR-041 |
| Append-only | `ModerationAction` update/delete throw | FR-018 |
| Wording | rendered list and view contain the standing sentence and no other `delet`/`remov` | FR-020, SC-013 |
| No average / no score | rendered page contains neither | FR-065 |
| Config | blank env value reads the default, both keys | **Finding 2** |
| Re-derivation | `--with-evidence` ×2 → identical, reports counts, touches no human act | FR-084, FR-085 |
| TG-M3 unaffected | attention figures identical with evidence present; a reaction still closes no question | FR-086 |
| Silence | no outbound call; provider exposes no ban/restrict/delete/react method | FR-078, FR-079 |
| Migration `0006` | up and down | data-transforming migration |

**Exempt under Principle I**: Filament resource, infolist, table and action wiring; Eloquent casting;
Dramatiq delivery semantics; column-type assertions; JSON serialisation of `detail`.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

Yes, most of them. Python tests reach Postgres only through `TEST_DATABASE_URL`; `tests/conftest.py`'s
session guard is untouched. PHP feature tests use `DatabaseTransactions` against `injaz_ai_test` —
never `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh`. Research probes against the
development database were read-only and selected payload *shape* only; every schema probe ran inside
`BEGIN … ROLLBACK` in `injaz_ai_test`. The advisory lock is transaction-scoped, so a failing test
releases it on rollback.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** No course mapping, no MySQL access, no InjazEdu-side change.

### 4. Are there Git actions in the task list? (Principle IV)

**No.** The branch `m4/policy-incidents` exists and was created by the operator; the agent created
none. The `before_specify` / `before_plan` / `after_plan` hooks are surfaced and left to the operator.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

Yes — see **Requirement → Design Traceability**. Three design choices depart from approved text or
touch a merged milestone and are escalated rather than taken quietly (**⚠ Three Items for the
Operator**); one defect in a merged milestone is recorded and deliberately **not** fixed. Deliberately
not built: automatic opening, alerts, the dashboard, label review, any bot action, any deletion
inference, any new actor or sweep.

## Project Structure

### Documentation (this feature)

```text
specs/007-tg-m4-policy-incidents/
├── spec.md                              # FR-001…FR-087, SC-001…SC-025, 3 clarifications
├── plan.md                              # this file
├── research.md                          # 4 findings, 9 probes, D-TG-98…D-TG-128
├── data-model.md                        # revision 0006: 2 tables, 2 views, the derived state machine
├── quickstart.md                        # walkthrough, evidence check, smoke test, 13 limitations
├── contracts/
│   ├── incident-lifecycle.md            # THE contract: opening, evidence, linkage, state, guard, never
│   ├── incident-metrics.md              # the exact SQL behind every incident figure
│   └── control-panel-incidents.md       # the resource, its actions, wording, config
├── checklists/requirements.md           # all items passing
└── tasks.md                             # NOT created here — /speckit-tasks
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── domain/moderation/
│   │   └── incident.py                      # NEW — PURE: membership classifier (V1–V3), reaction delta
│   │                                        #       (V7), label vocabularies. No I/O, no clock
│   ├── application/moderation/
│   │   ├── evidence.py                      # NEW — derive_membership_evidence / derive_reaction_evidence:
│   │   │                                    #       measured-gate, identity upsert, ON CONFLICT insert
│   │   ├── incidents.py                     # NEW — open_incident (tests, TG-M5), incident_state reader
│   │   ├── locks.py                         # EDIT — incident_lock: the shared literal (H4)
│   │   ├── metrics.py                       # EDIT — the three statements of incident-metrics.md, quoted
│   │   ├── messages.py                      # EDIT — sender_chat ⇒ ignore the fake `from` (Finding 1) ⚠2
│   │   └── assignments.py                   # EDIT — docstring: incidents not re-pointed (D-TG-107)
│   ├── workers/tasks/moderation/
│   │   └── process_update.py                # EDIT — dispatch chat_member / message_reaction
│   ├── scripts/rederive_chat.py             # EDIT — --with-evidence, default off (D-TG-128)
│   └── infrastructure/
│       ├── models_moderation.py             # EDIT — 2 tables + 2 read-only view Table objects
│       └── config.py                        # EDIT — MODERATION_INCIDENT_MAX_AGE_S, validated positive
├── alembic/versions/
│   └── 0006_moderation_incidents.py         # NEW — 2 tables, 2 views, 6 indexes, up and down
└── tests/moderation/
    ├── incidents/                           # NEW test package
    │   ├── conftest.py                      # incident/evidence factories; reuses TG-M2's message factories
    │   ├── test_membership_classifier.py    test_reaction_delta.py         # pure
    │   ├── test_membership_evidence.py      test_reaction_evidence.py
    │   ├── test_db_invariants.py
    │   ├── test_open_incident.py            test_anchor_unique.py          test_attribution.py
    │   ├── test_acknowledgement.py          test_ack_never_resolves.py
    │   ├── test_linkage.py                  test_lineage.py
    │   ├── test_pre_flag_evidence.py        test_order_independence.py
    │   ├── test_closure_precedence.py
    │   ├── test_metrics.py                                                  # hand-computed fixture
    │   ├── test_rederive_evidence.py        test_attention_unaffected.py
    │   ├── test_config_incident.py
    │   └── test_migration_0006.py
    ├── actors/test_sender_chat_payload.py   # NEW — Finding 1, the payload shape the platform really sends
    └── ingest/test_no_outbound.py           # EDIT — provider exposes no moderation-act method

apps/ai-control/
├── app/Models/
│   ├── ModerationIncident.php               # NEW — openOn(); acknowledge/resolve/closeAsFalsePositive:
│   │                                        #       lock → read view → guarded insert (H2–H4)
│   └── ModerationAction.php                 # NEW — append-only: update/delete throw
├── app/Filament/Resources/Incidents/
│   ├── IncidentResource.php                 # NEW — list + view, no create/edit/delete page
│   ├── Pages/ListIncidents.php  Pages/ViewIncident.php
│   ├── Schemas/IncidentInfolist.php         # the six questions, trail, notices
│   ├── Tables/IncidentsTable.php            # columns, filters, header action
│   ├── Actions/OpenIncidentAction.php       # shared by the resource and the queue (§2)
│   └── Concerns/IncidentMetrics.php         # the SQL of incident-metrics.md, quoted once
├── app/Filament/Pages/LiveAttentionQueue.php  # EDIT — one row action, nothing else
├── config/moderation.php                    # EDIT — blank-safe reads, incident_max_age_s
├── resources/views/filament/resources/incidents/  # NEW — figures table, standing sentence
└── tests/Feature/
    ├── IncidentResourceTest.php             # list, filters, unassigned, text removed, notices
    ├── IncidentOpenTest.php                 # picker exclusions, labels required, owner at detection, queue action
    ├── IncidentActionsTest.php              # guards, double submit, terminal, stale page
    ├── ModerationActionImmutabilityTest.php
    ├── IncidentMetricsTest.php              # figures, suppression, no data, no avg, no per-moderator latency
    ├── IncidentWordingTest.php              # the standing sentence; no other delet/remov
    └── ModerationConfigTest.php             # blank env → default, both keys

infra/docker-compose.yml                     # EDIT — ${KEY:-default} for both panel keys ⚠3
.env.example                                 # EDIT — MODERATION_INCIDENT_MAX_AGE_S=86400
CLAUDE.md / AGENTS.md                        # EDIT — active-feature pointer (identical files)
```

**Structure Decision.** No new top-level tree. Four placements are load-bearing:

- **The lifecycle lives in the database, not in either application.** `moderation_incident_evidence` and
  `moderation_incident_state` are the only definitions of linkage and state; `incidents.py` and
  `ModerationIncident.php` *read* them. A helper that computes a status in either language is a
  violation (lifecycle contract N6), and the tests read the view rather than re-deriving an expectation
  with code.
- **`app/domain/moderation/incident.py` holds only pure classification.** The membership table and the
  reaction delta are functions over dicts and strings — the second inhabitant of the domain package after
  TG-M3's rule set, testable exhaustively without a database, which Finding 4 makes the only available
  proof.
- **Evidence rides `process_update`.** No new actor and no sweep: the actor that marks a captured event
  handled derives its evidence first, so TG-M1's pending-updates work list is the durability mechanism,
  exactly as for messages.
- **The guard is on `ModerationIncident`, and it is load-bearing.** Probe 8 showed that a closure inserted
  without it changes a resolved incident's status. Mirroring `AttentionItem::closeIfOpen()` and
  `ModeratorGroupAssignment::handover()`, it holds from `tinker` too.

## ⚠ Three Items for the Operator

**All three approved by the operator on 2026-09-24.** Each either corrects the plan of record or touches a
merged milestone; each is now in scope for `tasks.md`.

### 1. ✅ Approved — Incident state is derived from evidence, not stored — a correction to source plan §10.8.

§10.8 gives `moderation_incidents` a `status` and `acknowledged_*` / `resolved_*` / `closed_*` columns set
by transitions. Two approved requirements cannot both hold with them: FR-045 (same state *and timings*
whatever the processing order — a first-processed column is wrong whenever earlier evidence arrives
later) and FR-043/FR-044 (one evaluation, including evidence from before the flag, when the opener is the
PHP panel that cannot call the Python matcher). TG-M3's own hand-open shows the second failure is not
hypothetical (research Finding 3).

The design stores no state; two views compute it (`data-model.md` §3), validated exactly as written by
probes 8 and 9. **§10.8's column list needs a note** that these fields are view columns, not table
columns. The plan's `moderation_actions` table, strengths and three timings are kept as designed.

### 2. ✅ Approved — TG-M2 cannot store a message sent on behalf of a channel or the group — this milestone fixes it in `messages.py`.

The platform puts a fake `from` on every such message; `derive_message` stores it as the sender *and*
stores `sender_chat_id`; `ck_telegram_messages_sender` rejects the row (probe 3). In production the
update fails, is retried, and is re-enqueued on every restart; the message never exists. TG-M2's test
used a payload the platform never sends.

FR-007 and FR-033 require incidents on exactly these messages — channel-posted spam is common. The fix is
four lines: when `sender_chat` is present, ignore `from` (D-TG-99), with a test on the real payload shape.
**It edits a TG-M2 module.** The alternative is to leave TG-M2 alone and narrow FR-007/FR-033 to "not in
this milestone". Recommended: approve the fix.

### 3. ✅ Approved — The panel's moderation settings are read unsafely — the running p90 floor is 0.

`.env` lacks `MODERATION_PERCENTILE_MIN_SAMPLES`; Compose passes an empty string; Laravel's `env()`
returns it instead of the default; `(int) ''` is 0 (probe 5). TG-M3's p90 suppression is therefore
**off** in the running panel today, and TG-M4's new incident ceiling would read 0 by the same path —
every incident "missed" the instant it opens.

The design passes both keys as `${KEY:-default}` and reads them blank-safe (D-TG-122), which **touches one
TG-M3 line** in each of `docker-compose.yml` and `config/moderation.php`. **Operator step either way**: add
both keys to `.env` (quickstart §2).

### Recorded, not fixed — TG-M3's hand-open skips the settle-window lookback.

`LiveAttentionQueue::openByHand` inserts the item and stamps `attention_evaluated_at`, so a moderator's
answer already stored after that message is never matched and the item stays open until expiry — against
TG-M3's own clarification that opening evaluates already-stored answers, and its FR-056 that a hand-opened
item behaves like a rule-opened one. Out of this milestone's scope (Principle V); recommended as a TG-M3
follow-up.

**Also worth knowing before the smoke test** (quickstart §4, §8): no membership change or reaction has
ever been captured in development, so the first live payloads arrive during the smoke test; and how the
platform names an anonymous administrator on a membership change is undocumented and unverified.

## Complexity Tracking

No Constitution violations. Three choices cost more than the obvious alternative, and each buys a
specific requirement:

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| State as two views instead of a `status` column | FR-045's order-independence and FR-043/FR-044's single evaluation across two languages, by construction | A stored status needs an evaluation step the PHP opener cannot run, and first-processed moment columns are wrong under out-of-order capture (Finding 3) |
| One global advisory lock shared by PHP and Python | Keeps `resolved` terminal against a false-positive closure racing an enforcement | Per-chat keys depend on promotion lineage and invite two-key deadlocks; no lock lets an observer see *resolved* then *closed* |
| Upserting identities for performers and subjects | Names on the evidence trail, under TG-M2's existing retention rules | Raw platform ids alone would show numbers where the operator needs names, or tempt a second name store outside retention |

## Post-Design Constitution Re-Check

Re-run after Phase 1. **All five still pass.**

1. **Principle I.** The test table was written from the finished design. Five tests exist *because* of a
   finding or probe (`test_membership_classifier`, `test_sender_chat_payload`, `ModerationConfigTest`,
   `test_closure_precedence`, `test_lineage`). Tests read the views rather than re-computing state, so a
   test cannot quietly become a second definition. The exemption list did not grow.
2. **Principle II.** Unchanged. The lock is transaction-scoped; `DatabaseTransactions` and the pytest
   session guard are untouched.
3. **Principle III.** Still nothing inside `injazedu/`.
4. **Principle IV.** No Git action entered the design.
5. **Principle V.** Three items escalated, one defect recorded and left alone. Nothing added beyond the
   spec: no actor, no sweep, no tick change, no dashboard; the figures table ships on this milestone's own
   page for the same reason TG-M3's did.

## Requirement → Design Traceability

| FR | Where it is satisfied |
|---|---|
| FR-001…FR-009 | `ModerationIncident::openOn`, `OpenIncidentAction` (resource + queue); `uq_incident_anchor`, `fk_incident_message`, label CHECKs; lifecycle §1; D-TG-100…D-TG-102, D-TG-116 |
| FR-010…FR-020 | `domain/incident.py`, `evidence.py`, `moderation_actions` + its CHECKs and unique key; lifecycle §2; D-TG-108…D-TG-113; Finding 1 fix for FR-007's channel case |
| FR-021…FR-025 | view branches (a), (b), (d); state precedence; lifecycle §3–§4; D-TG-105, D-TG-106 |
| FR-026…FR-033 | view branch (c) with one-hop lineage; lifecycle §3 L5–L7; D-TG-107, D-TG-109, D-TG-127 |
| FR-034…FR-038 | the three guarded methods; lifecycle §5; `control-panel-incidents.md` §3; D-TG-114, D-TG-115, D-TG-117 |
| FR-039…FR-045 | `moderation_incident_state`; `ck_actions_strength`; the lock; data-model §4; D-TG-104 |
| FR-046…FR-050 | `responsibleAt` at `detected_at`, written at open; actor columns; lifecycle §6 |
| FR-051…FR-066 | `contracts/incident-metrics.md`, quoted by `metrics.py` and `IncidentMetrics.php`; D-TG-118…D-TG-122 |
| FR-067…FR-077 | `IncidentResource` list/view, notices, queue row action; `control-panel-incidents.md`; D-TG-123…D-TG-127 |
| FR-078…FR-081 | silence + boundary tests carried forward; `incident_id` already whitelisted; no text in either table |
| FR-082 | view branch (c) lineage; incidents not re-pointed, like items (D-TG-107) |
| FR-083…FR-085 | no automatic backfill; `rederive_chat.py --with-evidence`; re-derivation inserts platform evidence only |
| FR-086…FR-087 | `test_attention_unaffected.py`, TG-M3's suite unchanged; offline `make check` |

| SC | Verified by |
|---|---|
| SC-001 | the operator's smoke run, quickstart §5 (+ `test_linkage.py`) |
| SC-002 | `test_ack_never_resolves.py` |
| SC-003 | `test_linkage.py`, `test_closure_precedence.py`, `IncidentActionsTest.php` |
| SC-004 | `test_linkage.py` |
| SC-005 | `test_order_independence.py` |
| SC-006 | `test_reaction_evidence.py`, `test_membership_evidence.py`, `test_anchor_unique.py` |
| SC-007 | `test_membership_classifier.py`, `test_reaction_delta.py`, `test_linkage.py` |
| SC-008 | `test_linkage.py` |
| SC-009, SC-010, SC-011 | `test_metrics.py`, `IncidentMetricsTest.php` |
| SC-012 | `test_attribution.py` |
| SC-013 | `IncidentWordingTest.php` |
| SC-014 | `IncidentMetricsTest.php` |
| SC-015 | `test_linkage.py` (non-moderator performers) |
| SC-016 | `test_attention_unaffected.py` + TG-M3's `test_reaction_never_closes.py` unchanged |
| SC-017 | `IncidentResourceTest.php` |
| SC-018 | `test_lineage.py` |
| SC-019 | `test_rederive_evidence.py` |
| SC-020, SC-021 | offline `make check`; the existing check 4 |
| SC-022 | `test_no_outbound.py` extended + quickstart §5's last line |
| SC-023 | `test_pre_flag_evidence.py`, `test_metrics.py` |
| SC-024 | `test_metrics.py` (late resolution; recomputed later → identical) |
| SC-025 | `test_open_incident.py`, `IncidentOpenTest.php` |

## Phase Status

| Phase | Status | Output |
|---|---|---|
| Phase 0 — Research | ✅ complete | `research.md` — 4 findings, 9 probes, D-TG-98…D-TG-128, settings, traceability |
| Phase 1 — Design & Contracts | ✅ complete | `data-model.md`, 3 contracts, `quickstart.md`, agent context updated |
| Constitution Check | ✅ passed, re-checked post-design | 3 items escalated and **approved** (2026-09-24), 1 defect recorded, 0 violations |
| Phase 2 — Tasks | ✅ complete | `tasks.md` — 71 tasks, 9 phases, FR-001…FR-087 and SC-001…SC-025 all covered |
| Phase 3 — Implementation | ⏳ not started | `/speckit-implement` |
