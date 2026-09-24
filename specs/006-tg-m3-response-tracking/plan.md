# Implementation Plan: TG-M3 — Deterministic Response Tracking

**Branch**: `m3/response-tracking` *(operator-created; Principle IV)* | **Date**: 2026-09-22
**Spec**: [`spec.md`](./spec.md) · **Research**: [`research.md`](./research.md) ·
**Data model**: [`data-model.md`](./data-model.md) ·
**Contracts**: [`attention-rules.md`](./contracts/attention-rules.md) ·
[`attention-metrics.md`](./contracts/attention-metrics.md) ·
[`control-panel-attention.md`](./contracts/control-panel-attention.md) ·
**Quickstart**: [`quickstart.md`](./quickstart.md)
**Milestone**: TG-M3 of `docs/plan/telegram/telegram-moderation-intelligence.md` §25 — 🎯 the first
usable slice

## Summary

A student's question opens one item of work dated from the moment they first spoke; a moderator's
answer closes it; the gap between is a first-response time attributed to whoever owned the group *at
that instant*. Everything is deterministic and re-derivable: no model, no network, no clock reading
that ends up in a stored number.

Six pieces ship. A **burst rule** collapses several messages from one person into one question,
anchored on the earliest. A **hand-written, versioned rule set** — a pure function in the domain layer,
with its literals stored normalised and guarded by a self-check test — decides what deserves an answer.
One **response matcher** with two entry points closes items, including the lookback at open time that
catches a moderator who answered inside the settle window. A **live queue screen** shows what is still
waiting, oldest first. **Operator dismissals and hand-additions** are recorded as human acts and are the
raw material for the rule set's measured precision. An **ageing step** expires abandoned items without
letting them distort the distribution.

Four measured facts shaped the design (`research.md` §0): seven of the source plan's own rule-set
literals never survive the normaliser and would have matched nothing forever; the unique constraint §10.7
specifies collides across groups and the idempotent insert form *swallows* the collision; the delayed
judgement exists only in a Redis that is not durable here; and the stack has no periodic execution at
all, because the "30 s tick" §7.3 assigns to `ai-telegram` was never built.

## Technical Context

**Language/Version**: Python 3.12 (`apps/ai-api`), PHP 8.3 / Laravel 12.69.1 (`apps/ai-control`)
**Primary Dependencies**: SQLAlchemy 2 Core (async), Alembic, Dramatiq 2.2.1 + Redis broker,
Filament v5.7.8, Livewire 4.4.3. **No new dependency on either side.**
**Storage**: PostgreSQL 16.15 — revision `0005_moderation_attention`, down-revision `0004` (head)
**Testing**: pytest against `injaz_ai_test` via `TEST_DATABASE_URL`; PHPUnit with `DatabaseTransactions`
against the same database. No credential, no network, no model runtime in any of it
**Target Platform**: the existing local Docker stack — `ai-api`, `ai-worker`, `ai-telegram`,
`ai-control`, `postgres`, `redis`. No new service
**Project Type**: two applications in one repository — Python service plus PHP control panel. Second
milestone to change both
**Performance Goals**: not a throughput milestone. The queue's ordering index is partial
(`WHERE status='open'`), so it is sized by the live backlog rather than by history; the sweep's index is
partial and empty in steady state
**Constraints**: no model call, no outbound message, no inbound endpoint, no message text in any log
line. Judgement latency is one settle window on the fast path and at most one additional tick when the
queue has lost a delayed message
**Scale/Scope**: ~5 moderators, a handful of measured groups, a two-week pilot. Small enough that the
percentile floor (10 answered items) bites regularly, which is why suppression is a requirement and not
a nicety

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 below.*

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested** — every one protects a business rule, an idempotency guarantee, or metric arithmetic:

| Area | Test | Why it earns one |
|---|---|---|
| Rule-set literals | `normalize(literal) == literal` for all 45 entries | **Finding 1.** Fixes the class, not the seven instances |
| Rule set v1 | Arabic and dialect fixtures with and without `؟`, dialect forms, stoplist, emoji-only, ≤2 chars | Rule precision *is* the v1 product |
| Stoplist precedence | `تمام` replying to a moderator opens nothing | Without it every thanks opens an item |
| Burst grouping | 3 messages in 90 s → one item, `opened_at` = the first; spread beyond → two; two senders → two | The §11 rule |
| Burst scoping | different thread, different sender, `sender_chat` → separate or none | FR-002, FR-013 |
| Anchor uniqueness | two chats, same per-chat message number → **two** items | **Finding 2**, directly |
| Idempotent opening | judge the same messages 3×, shuffled → one item, identical fields | FR-009, the re-derivation premise |
| Response matching | direct reply · plain next message · wrong thread · other chat · non-moderator · bot | Core business rule |
| Oldest-only | 3 waiting, 1 plain message → exactly one closes | One message never clears a backlog |
| Out-of-order | reply stored before its question → closes nothing, in both storage orders | The metric would be silently wrong |
| Settle-window lookback | answer at +20 s → answered item, FRT 20 s | The session's first clarification |
| Reaction | ✅ on a waiting question → closes nothing | The most tempting wrong implementation here |
| Write-once closure | second closer, dismissed item, expired item → zero rows updated | C8 |
| Tie-break | two moderators, same `sent_at` → one deterministic winner | C9 |
| Attribution | question at T attributes to the owner at T; reassign after → unmoved | The reports' integrity, and the runbook's own check |
| Unassigned | no primary at `opened_at` → NULL, item still opens and is visible | Coverage must surface, not hide |
| Ageing | item at ceiling → expired; run twice → unchanged; excluded from FRT and oldest | §13.5 |
| Metric arithmetic | fixed dataset, hand-computed median/p90/max; <10 samples suppressed; 0 rows → NULL not 0 | Metric arithmetic is business logic |
| Window selection | boundary inclusive/exclusive on `opened_at`, never `created_at` | M1, M2 |
| Edits | edit adds a question → item dated from the edit; burst with an item → none; dismissed → not revived | E1–E4 |
| Re-derivation | `--with-attention` twice → identical state; reports three counts | FR-083 |
| Supergroup migration | promotion → items follow the surviving chat | TG-M2's Finding 3, extended |
| Silence | no outbound call anywhere in the milestone | The guarantee, carried forward |
| Boundary | no Telegram/model import outside the provider; no assessment→moderation import | Mirrors the existing gate |
| No average / no score | the panel contains neither | D-TG-92 — the likely well-meaning regression |
| Migration `0005` | up and down | Data-transforming migration |

**Exempt under Principle I**: Filament table rendering and action wiring; Livewire's polling transport;
Eloquent casting; Dramatiq delivery semantics; the poll loop's sleep behaviour; column-type assertions;
JSON serialisation.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

Yes, most of them. Python tests reach Postgres only through `TEST_DATABASE_URL`; `tests/conftest.py:13-18`
already aborts the session when that name is unsafe, and that guard is untouched. PHP feature tests use
`DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase`, `DatabaseMigrations` or
`migrate:fresh`. The research probes themselves ran inside `BEGIN … ROLLBACK` on temporary tables in
`injaz_ai_test`; nothing was left behind and no development data was touched.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** Nothing in this milestone reads or writes that directory. There is no course mapping here, no
MySQL access, and no InjazEdu-side change of any kind.

### 4. Are there Git actions in the task list? (Principle IV)

**No.** The branch `m3/response-tracking` already exists and was created by the operator; the agent
verified it with `git branch --show-current` and created none. No commit, push, merge or tag appears in
any task. `.specify/extensions.yml`'s git hooks are surfaced and left for the operator to run.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

Yes — see **Requirement → Design Traceability** below; every task maps to an FR in `spec.md`, and every
FR maps to at least one task. Two design choices narrow or correct approved text and are escalated
rather than taken quietly (**⚠ Two Items for the Operator**). Deliberately not built: incidents,
actions, reactions-as-evidence, any model call, alerts, the overview and team-performance screens, any
conversation model, any automatic backfill.

## Project Structure

### Documentation (this feature)

```text
specs/006-tg-m3-response-tracking/
├── spec.md                              # FR-001…FR-084, SC-001…SC-025, 3 clarifications
├── plan.md                              # this file
├── research.md                          # 4 findings, 10 probes, D-TG-70…D-TG-97
├── data-model.md                        # revision 0005: one table, one alter
├── quickstart.md                        # operator walkthrough, smoke test, 12 limitations
├── contracts/
│   ├── attention-rules.md               # THE contract: burst, rule set v1, closure, attribution
│   ├── attention-metrics.md             # the exact SQL behind every figure
│   └── control-panel-attention.md       # the screen, its actions, what it may not do
├── checklists/requirements.md           # all items passing
└── tasks.md                             # NOT created here — /speckit-tasks
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── domain/moderation/
│   │   └── attention.py                     # NEW — rule set v1. PURE: no I/O, no clock, no session.
│   │                                        #       Literals stored normalised (Finding 1)
│   ├── application/moderation/
│   │   ├── attention.py                     # NEW — burst assembly, opening, the ONE matcher,
│   │   │                                    #       expiry, the sweep. Advisory lock lives here
│   │   └── messages.py                      # EDIT — clear attention_evaluated_at on edit (E5);
│   │                                        #       schedule judgement after insert
│   ├── workers/tasks/moderation/
│   │   ├── evaluate_attention.py            # NEW — delayed actor; an optimisation, not the record
│   │   ├── sweep_unjudged_bursts.py         # NEW — the authoritative catch-up (Finding 3)
│   │   ├── expire_stale_items.py            # NEW — one guarded set-based UPDATE
│   │   └── match_response.py                # NEW — invoked when a moderator message is derived
│   ├── telegram_main.py                     # EDIT — the tick: one leased enqueue per loop (Finding 4).
│   │                                        #        Enqueues only; writes no derived state
│   ├── workers/main.py                      # EDIT — import the four new actors
│   ├── scripts/rederive_chat.py             # EDIT — --with-attention, default off (D-TG-89)
│   └── infrastructure/
│       ├── models_moderation.py             # EDIT — attention_items + 2 columns, same metadata
│       └── config.py                        # EDIT — 2 settings, additive, both defaulted
├── alembic/versions/
│   └── 0005_moderation_attention.py         # NEW — 1 table, 1 alter, 6 indexes, up and down
└── tests/moderation/attention/              # NEW test package
    ├── conftest.py                          # reuses TG-M2's message factories + a controlled clock
    ├── test_rule_literals.py                # Finding 1 — the self-check
    ├── test_rules_v1.py       test_stoplist.py
    ├── test_burst.py          test_burst_scope.py
    ├── test_anchor_unique.py                # Finding 2
    ├── test_opening_idempotency.py
    ├── test_matching.py       test_oldest_only.py   test_out_of_order.py
    ├── test_settle_window_lookback.py
    ├── test_reaction_never_closes.py
    ├── test_closure_guard.py  test_tiebreak.py
    ├── test_attribution.py    test_unassigned.py
    ├── test_ageing.py         test_sweep.py
    ├── test_edits.py          test_rederive_attention.py
    ├── test_metrics.py                      # hand-computed fixtures, suppression, NULL≠0
    ├── test_migration_repoint_items.py
    └── test_migration_0005.py               # up and down

apps/ai-control/
├── app/Models/
│   └── AttentionItem.php                    # NEW — the guarded close lives HERE, not in the action
├── app/Filament/Pages/
│   └── LiveAttentionQueue.php               # NEW — custom page + table, ->poll('15s')
├── app/Filament/Pages/Concerns/
│   └── AttentionMetrics.php                 # NEW — the SQL of attention-metrics.md, quoted once
└── tests/Feature/
    ├── LiveAttentionQueueTest.php           # ordering, unassigned badge, purged-text row
    ├── AttentionDismissTest.php             # guarded close, double submit, reasons
    ├── AttentionManualAddTest.php           # duplicate anchor prevented in the form
    └── AttentionMetricsTest.php             # suppression, NULL≠0, no average, no score

.env.example                                 # EDIT — 2 new settings with defaults
CLAUDE.md / AGENTS.md                        # EDIT — active-feature pointer (identical files)
```

**Structure Decision.** No new top-level tree on either side. Four placements are load-bearing rather
than stylistic:

- **`app/domain/moderation/attention.py` holds the rules and nothing else.** The package exists and is
  empty; this is its first inhabitant, and the reason it was created. A pure function over strings is
  testable without a database, a clock or a fixture, which is what makes running the whole Arabic
  fixture corpus cheap enough to actually do.
- **One `match_response` in `app/application/moderation/attention.py`, called from two places.** The
  open-time lookback (C10) and the new-message path delegate to the same predicate. Two
  implementations of the same rule are two ways for the number to disagree with itself — the one thing
  this milestone cannot afford.
- **The tick in `app/telegram_main.py`, enqueueing only.** Finding 4: this is the only loop in the
  stack with a bounded period, and it already sends `drain_pending_updates` without writing derived
  state, so §7.3's component boundary is preserved rather than bent. Adding a scheduler dependency for
  two recurring jobs was rejected under Principle V.
- **The guarded close on `AttentionItem`, not in the Filament action.** Directly mirroring TG-M2's
  `ModeratorGroupAssignment` and M1's `ModelProfile::save()`: the invariant holds from `tinker` and a
  future artisan command, not only when a Filament form happens to be in front of it.

## ⚠ Two Items for the Operator

Neither blocks starting work; both should be agreed before merge. Both are **corrections to the plan of
record**, not preferences.

### 1. The source plan's §10.7 unique constraint is wrong, and wrong silently.

§10.7 specifies the attention item's anchor as `UNIQUE (telegram_message_id)`. Telegram numbers messages
per chat from 1 upward, so two groups collide on their own message #2 — and because FR-009 forces the
`ON CONFLICT … DO NOTHING` form, the collision does not raise. Measured: `INSERT 0 0`, one row where
there should be two, no error and no log line (`research.md` Finding 2). It lands on the *first*
questions of every group after the first.

The design uses `UNIQUE (telegram_chat_id, telegram_message_id)`, matching TG-M2's own
`uq_telegram_messages_chat_msg`. **§10.7 needs a one-line correction.**

### 2. The source plan's §13.1 rule literals cannot match anything as printed.

Seven of the thirty-one interrogative and support entries — `متى`, `أين`, `كيفية`, `إيش`, `أبغى`,
`مشكلة`, `متأخر` — do not survive TG-M0's `normalize()`, and FR-019 requires matching against normalised
text. Each would have returned false for every message forever, with no error
(`research.md` Finding 1). `متى` and `مشكلة` are among the commonest real question signals in a support
group.

The design stores every literal already normalised and adds a test asserting
`normalize(literal) == literal` for all 45 entries. **§13.1's printed list needs correcting, or an
explicit note that it is illustrative orthography rather than the literals.**

Flagged because in both cases the *stored artefact* differs from approved text. An agent quietly
"fixing" an approved specification is a Principle V violation; the operator should confirm the
correction rather than discover it.

**Separately, two operator prerequisites become real at this milestone** (runbook §C's TG-M3 row and
§D), and neither is an agent decision: **which group is the pilot and who moderates it**, and **where
the live capture process runs**. Development and every automated test proceed without either; the smoke
test does not.

## Complexity Tracking

No Constitution violations. Three choices cost more than the obvious alternative and each buys
something specific:

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| `attention_evaluated_at` as a second column | Distinguishes *not judged* from *judged and declined* — most messages are the second | A NULL `attention_item_id` alone would make the sweep re-judge every message in the database, forever |
| A per-chat advisory lock | Rule (b)'s "oldest open item" is a read-then-write race across 8 consumers | `FOR UPDATE SKIP LOCKED` stops two closers writing the same row but not each picking a *different* "oldest" — the failure that silently credits one message with two items |
| The sweep beside the delayed actor | The delayed judgement lives only in a Redis with `appendonly no` and 60–3600 s RDB thresholds | Trusting the queue makes a lost message a question that never existed, with no error and no gap record |

## Post-Design Constitution Re-Check

Re-run after Phase 1. **All five still pass.**

1. **Principle I.** The test table above was written from the finished design, not from the spec; every
   row protects a rule, an invariant or an arithmetic result. Four tests exist *because* of a probe
   (`test_rule_literals`, `test_anchor_unique`, `test_sweep`, `test_settle_window_lookback`) and would
   not have been written without one. Framework behaviour stays exempt and the exemption list did not
   grow.
2. **Principle II.** Unchanged and unchallenged by the design. The one new thing worth stating: the
   advisory lock is transaction-scoped (`pg_advisory_xact_lock`), so a test that fails mid-transaction
   releases it on rollback — no lock can leak into another test.
3. **Principle III.** Still nothing inside `injazedu/`.
4. **Principle IV.** No Git action entered the design. The branch was found, not made.
5. **Principle V.** Two narrowings escalated above rather than absorbed. Nothing was added beyond the
   spec: the tick is the minimum mechanism for an approved requirement (FR-038), not an
   opportunistic scheduler; the second column is the minimum shape for an approved guarantee (FR-009,
   FR-082); and the per-group/per-moderator figures ship on this milestone's own page precisely so
   TG-M7's screens are not half-built here.

## Requirement → Design Traceability

| FR | Where it is satisfied |
|---|---|
| FR-001…FR-003 | `domain/attention.py` burst key; contract §1; D-TG-79 |
| FR-004…FR-007 | `uq_attention_anchor` (chat + message), `attention_item_id`; D-TG-71; **Finding 2** |
| FR-008…FR-009 | `evaluate_attention` delay + idempotent open; contract §1 B4; D-TG-80 |
| FR-010 | measurement gate reused from TG-M2 |
| FR-011…FR-021 | `domain/moderation/attention.py`; contract §2; D-TG-74…D-TG-78; **Finding 1** |
| FR-022…FR-024 | `messages.apply_edit` clears `attention_evaluated_at`; contract §3; D-TG-88 |
| FR-025…FR-035 | one matcher, two entry points; contract §4; D-TG-82…D-TG-85, D-TG-81 |
| FR-036…FR-040 | `expire_stale_items`, the tick; contract §6; D-TG-86, D-TG-87 |
| FR-041…FR-045 | `responsible_at` snapshot at `opened_at`; contract §5; D-TG-48 reused |
| FR-046…FR-053 | `AttentionItem` guarded close, panel actions; contract `control-panel-attention.md` §2 |
| FR-054…FR-062 | `LiveAttentionQueue` page, `->poll('15s')`, `dir="auto"`; D-TG-93…D-TG-97 |
| FR-063…FR-070 | `contracts/attention-metrics.md`, quoted by the panel; D-TG-90…D-TG-92 |
| FR-071…FR-077 | boundary + silence tests carried forward from TG-M1/TG-M2 |
| FR-078…FR-081 | correlation ids on the three steps; item follows a supergroup promotion |
| FR-082…FR-084 | `rederive_chat.py --with-attention`; no automatic backfill; offline test suite |

| SC | Verified by |
|---|---|
| SC-001, SC-021 | `test_matching.py` + the runbook smoke test |
| SC-002, SC-003 | `test_burst.py`, `test_opening_idempotency.py` |
| SC-004 | `test_attribution.py` — the reassign-after check |
| SC-005, SC-006 | `test_oldest_only.py`, `test_out_of_order.py` |
| SC-007 | `test_reaction_never_closes.py` |
| SC-008, SC-009 | `test_rules_v1.py`, `test_metrics.py` §5 |
| SC-010 | `test_ageing.py` |
| SC-011, SC-012, SC-013, SC-014 | `test_metrics.py`, `AttentionMetricsTest.php` |
| SC-015, SC-016, SC-017 | `LiveAttentionQueueTest.php` |
| SC-018, SC-019, SC-020 | `make check` offline; the existing check 4; the silence test |
| SC-022 | `test_migration_repoint_items.py` |
| SC-023, SC-024, SC-025 | `test_settle_window_lookback.py`, `test_edits.py`, `test_rederive_attention.py` |

## Phase Status

| Phase | Status | Output |
|---|---|---|
| Phase 0 — Research | ✅ complete | `research.md` — 4 findings, 10 probes, D-TG-70…D-TG-97, settings, traceability |
| Phase 1 — Design & Contracts | ✅ complete | `data-model.md`, 3 contracts, `quickstart.md`, agent context updated |
| Constitution Check | ✅ passed, re-checked post-design | 2 items escalated to the operator, 0 violations |
| Phase 2 — Tasks | ⏳ not started | `/speckit-tasks` |
| Phase 3 — Implementation | ⏳ not started | `/speckit-implement` |
