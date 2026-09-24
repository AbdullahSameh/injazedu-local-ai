---
description: "Task list for TG-M3 — Deterministic Response Tracking"
---

# Tasks: TG-M3 — Deterministic Response Tracking

**Input**: Design documents from `specs/006-tg-m3-response-tracking/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts, business
rules, idempotency and retry safety, data integrity, and migrations that transform data — which is
almost the whole of this milestone, because this milestone *is* a set of business rules and their
arithmetic. `plan.md`'s Constitution Check enumerates the **27 behaviours that earn one**, each mapped
to an FR/SC. Behaviours named exempt there — Filament table rendering and action wiring, Livewire's
polling transport, Eloquent casting, Dramatiq delivery, the poll loop's sleep, column types, JSON
serialisation — get **no** test task here.

**Four tests exist because a probe proved the obvious test would pass while the code was broken:**
**T014** (the rule-set literals: seven of the source plan's own entries never survive `normalize()`, so
a test of the *rules* passes on fixtures written in the same unnormalised orthography while every real
message fails to match), **T015** (two chats' message #2 — the plan's stated unique constraint collides
and `ON CONFLICT DO NOTHING` swallows it, so a single-chat test is green), **T036** (a moderator
answering *inside* the settle window, which no test of "reply closes item" reaches), and **T061** (the
sweep — every test passes when the delayed message is delivered, and this stack's Redis does not
guarantee that).

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US6, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its tests at
`apps/ai-api/tests/moderation/attention/`, migrations at `apps/ai-api/alembic/versions/`. Panel at
`apps/ai-control/` — Eloquent models at `app/Models/`, custom pages at `app/Filament/Pages/`, feature
tests at `tests/Feature/`.

⚠ Four placements are load-bearing, not stylistic:

- **`app/domain/moderation/attention.py` holds the rules and nothing else** — no I/O, no clock, no
  session. The package exists and is empty; this is its first inhabitant and the reason it was created.
  A pure function over strings is what makes running the whole Arabic corpus cheap enough to do.
- **One matcher in `app/application/moderation/attention.py`, called from two places.** The open-time
  lookback and the new-message path delegate to the same predicate. Two implementations of one rule
  are two ways for the number to disagree with itself.
- **The tick in `app/telegram_main.py`, enqueueing only.** It is the only loop in the stack with a
  bounded period, and it already sends `drain_pending_updates` without writing derived state. It is a
  composition root, exempt from the boundary check by directory.
- **The guarded close on `AttentionItem`**, not in the Filament action — mirroring TG-M2's
  `ModeratorGroupAssignment` and M1's `ModelProfile::save()`, so the invariant holds from `tinker` too.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Two settings and the test scaffolding. Nothing here has behaviour.

- [X] T001 [P] Add `MODERATION_TICK_INTERVAL_S` (default `30`) and `MODERATION_PERCENTILE_MIN_SAMPLES` (default `10`) to `apps/ai-api/app/infrastructure/config.py`, in a new `# --- Deterministic Response Tracking (TG-M3, optional, defaulted) ---` block following the existing `MODERATION_*` shape, each with a positive-value validator (research §3)
- [X] T002 [P] Add both keys with their defaults to `.env.example`, beside the TG-M2 block
- [X] T003 [P] Create the test package `apps/ai-api/tests/moderation/attention/__init__.py`
- [X] T004 [P] Create `apps/ai-api/tests/moderation/attention/conftest.py` — an async session factory against `injaz_ai_test` following `tests/moderation/actors/conftest.py`, a **controlled clock** fixture (every time-dependent assertion in this milestone is fixed-clock; nothing calls `datetime.now()` in a test), and builders that insert `telegram_messages` rows directly with an explicit `sent_at`, `is_from_moderator`, `reply_to_message_id` and `message_thread_id`. Reuses TG-M2's chat/moderator/assignment factories. No transport and no credential: this milestone reads stored messages
- [X] T005 [P] Create `apps/ai-api/tests/moderation/attention/fixtures/arabic_corpus.py` — the labelled fixture set the rule set is measured against: real questions with and without `؟`, dialect forms (`وين`, `ايش`, `ليش`, `ازاي`), support phrasings (`مش ظاهر`, `ما وصل`, `دفعت`), acknowledgements (`شكرا`, `تمام`, `جزاك الله خير`), emoji-only and emoji runs, ≤2-character messages, and the known over-firing cases (`من` used as a preposition). Each entry carries its expected verdict. This file is the milestone's second deliverable and TG-M5's baseline

**Checkpoint**: Both settings validate, the test package exists, messages can be built at a chosen
instant, and the corpus is labelled.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The table, its invariants, the two columns, the Eloquent model, and the shared helpers
two stories need.

**⚠ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Append `attention_items` to `apps/ai-api/app/infrastructure/models_moderation.py` on the shared `metadata`, exactly per `data-model.md` §1 — every column, and **all eight CHECK constraints**, including `ck_attention_answered_complete` and `ck_attention_response_order`. ⚠ The anchor is `UniqueConstraint("telegram_chat_id", "telegram_message_id")` — **not** `telegram_message_id` alone, which is what the source plan §10.7 says and what research **Finding 2** measured as silently wrong (D-TG-71). `message_thread_id` is denormalised onto the item, deliberately (D-TG-83)
- [X] T007 In the same file, add `attention_item_id` and `attention_evaluated_at` to `telegram_messages`. Both nullable. **Two columns, not one** — a NULL `attention_item_id` cannot distinguish *not yet judged* from *judged and correctly declined*, and most messages are the second (D-TG-72, research **Finding 3**)
- [X] T008 Create `apps/ai-api/alembic/versions/0005_moderation_attention.py`, down-revision `0004`. `upgrade()` creates `attention_items`, adds the two columns to `telegram_messages`, then the six indexes of `data-model.md` — four of them **partial**: `ix_attention_open`, `ix_attention_chat_thread_open`, `ix_messages_unjudged`, `ix_messages_attention_item`, using `postgresql_where=sa.text(...)` per `0002_model_gateway.py:65`. `downgrade()` reverses in dependency order. **No `GRANT`** (probe 10), and **no FK to `message_classifications`** — that table does not exist until `0007`
- [X] T009 [P] `apps/ai-api/tests/moderation/attention/test_migration_0005.py` — upgrade to `0005`, assert the table, the two columns and the six indexes exist, downgrade to `0004`, assert they are gone, upgrade again. Column types are **not** asserted (exempt)
- [X] T010 [P] `apps/ai-api/tests/moderation/attention/test_db_invariants.py` — attempt each violation **directly in SQL**, not through the application: a duplicate `(telegram_chat_id, telegram_message_id)`; an item anchored on a message that was never stored; `status='answered'` with no `first_response_at`; `first_response_at <= opened_at`; `source='rule'` with a NULL `rule_version`; `source='operator'` with one. Each must raise
- [X] T011 [P] Create `apps/ai-control/app/Models/AttentionItem.php` — `$table = 'attention_items'`, relations to chat, responsible moderator and responding moderator, and a `closeIfOpen(string $status, array $attrs)` method implementing `contracts/attention-rules.md` C8 as a single guarded `UPDATE … WHERE id = ? AND status = 'open'` returning the affected row count. The guard lives **here**, not in the Filament action, so it holds from `tinker` (D-TG-85). A header comment records that Alembic owns this schema, as `ModelProfile.php` does
- [X] T012 [P] Create `apps/ai-api/app/application/moderation/locks.py` — `chat_lock(session, chat_id)`, an async context manager issuing `SELECT pg_advisory_xact_lock(hashtext(:key))`. Transaction-scoped, so it releases on commit **and** on rollback with no cleanup path to get wrong; a test that fails mid-transaction cannot leak it into the next (D-TG-81, probe 8)
- [X] T013 [P] Add `tick_lease(redis, ttl_s)` to `apps/ai-api/app/application/moderation/ingest.py` — one `SET ai:tg:tick:lease <token> NX EX <ttl>`, returning whether this caller won. Shaped on the existing `hold_poll_lease` but **not** renewed and **not** released: expiry *is* the interval (D-TG-86). No actor is referenced here; the wiring lands in T059

**Checkpoint**: `make migrate` reaches `0005` and rolls back cleanly; the anchor collision from Finding
2 is impossible at the database; the panel has a model whose close is guarded; the lock and the lease
exist and are tested by the stories that use them.

---

## Phase 3: User Story 1 — A student's question becomes one item of work, dated when they actually spoke (Priority: P1) 🎯 MVP

**Goal**: A settled burst of messages from one student becomes exactly one item, dated from the first
of them, opened by a versioned rule set, attributed to whoever owned the group at that instant.

**Independent Test**: Feed scripted message sets through the recogniser with a controlled clock —
three inside the settle window, three spread beyond it, the same set replayed and shuffled, and sets
from an unmeasured group. One item per settled question, start equal to the first message's platform
timestamp, one item after replay, none for unmeasured groups, rule version present. No credential, no
network, no model.

### Tests for User Story 1

- [X] T014 [P] [US1] `apps/ai-api/tests/moderation/attention/test_rule_literals.py` — assert `normalize(literal) == literal` for **all 45 entries** of both `ACK_STOPLIST` and `QUESTION_PATTERNS`. ⚠ This is the milestone's cheapest and most valuable test: seven of the source plan §13.1 entries (`متى`, `أين`, `كيفية`, `إيش`, `أبغى`, `مشكلة`, `متأخر`) do not survive the normaliser and would match **nothing, forever, with no error** (research **Finding 1**). The test fixes the class, not the seven instances
- [X] T015 [P] [US1] `apps/ai-api/tests/moderation/attention/test_anchor_unique.py` — two different chats, each with its own message `#2`, both opening an item → **two rows**. ⚠ Under the source plan's stated constraint this test fails with one row and `INSERT 0 0`, no error (research **Finding 2**). A single-chat test cannot see it
- [X] T016 [P] [US1] `apps/ai-api/tests/moderation/attention/test_rules_v1.py` — run the whole `arabic_corpus` fixture set and assert every labelled verdict, including the questions that carry no `؟` at all, and the token-boundary requirement (`من` inside a longer word must not fire)
- [X] T017 [P] [US1] `apps/ai-api/tests/moderation/attention/test_stoplist.py` — a burst of pure thanks opens nothing; `تمام` sent as a **direct reply to a moderator** opens nothing (the stoplist must beat the reply signal, or every thanks opens an item — C-R1); a single emoji, a run of four `👍`, a caption-less photo and a two-character message each open nothing
- [X] T018 [P] [US1] `apps/ai-api/tests/moderation/attention/test_burst.py` — three messages inside the window → **one** item whose `opened_at` is the **first** message's `sent_at`; the same three spread beyond the window → two items; two senders interleaved → two items, neither absorbing the other's messages
- [X] T019 [P] [US1] `apps/ai-api/tests/moderation/attention/test_burst_scope.py` — a different `message_thread_id` starts a new burst; `NULL` thread matches only `NULL` (the `IS NOT DISTINCT FROM` requirement, FR-002); a `sender_chat` message forms no burst; a service announcement in the burst suppresses the item
- [X] T020 [P] [US1] `apps/ai-api/tests/moderation/attention/test_opening_idempotency.py` — judge the same messages three times, once with the messages presented in reverse order; one item, byte-identical field values every pass. Also: judging a partial burst that declines, then the full burst, yields one item dated from the anchor
- [X] T021 [P] [US1] `apps/ai-api/tests/moderation/attention/test_attribution.py` — an item's `responsible_moderator_id` is `responsible_at(chat, opened_at)`; a handover *after* the item opened leaves it unmoved; a question asked exactly at a `valid_from` attributes to the incoming owner and one asked exactly at a `valid_to` to the outgoing one (the half-open boundary, reusing TG-M2's predicate)
- [X] T022 [P] [US1] `apps/ai-api/tests/moderation/attention/test_unassigned.py` — a chat with no primary at `opened_at` still opens the item, with `responsible_moderator_id` NULL. NULL is a real answer, never the current owner
- [X] T023 [P] [US1] In `test_burst_scope.py`, assert a burst in an **unmeasured** chat opens nothing and that its messages are still marked `attention_evaluated_at`, so the sweep does not revisit them forever

### Implementation for User Story 1

- [X] T024 [US1] Create `apps/ai-api/app/domain/moderation/attention.py` — `RULE_VERSION = 1`, `ACK_STOPLIST`, `QUESTION_PATTERNS`, and `evaluate(burst) -> bool`. ⚠ Every literal is written **already normalised**, exactly as `contracts/attention-rules.md` §2.1 lists them. **Pure**: no import of a session, a clock, `httpx` or anything under `app.infrastructure`. Matching is on **token boundaries**, never bare substrings — `من` is also the commonest Arabic preposition and `كم` is a substring of many words (D-TG-74, D-TG-77, D-TG-78)
- [X] T025 [US1] In the same module, implement the ordering of `contracts/attention-rules.md` §2.2: the acknowledgement stoplist is evaluated **first and wins outright**, before any question signal (R1). Bare-emoji detection handles runs itself — `normalize()` collapses repeated *letters* but not repeated emoji (R5, measured)
- [X] T026 [US1] Create `apps/ai-api/app/application/moderation/attention.py` with `assemble_burst(session, chat_id, user_id, thread_id, around)` — reads `telegram_messages`, groups by `MODERATION_BURST_GAP_S` over `sent_at` using `IS NOT DISTINCT FROM` for the thread, and returns the burst with its **earliest member as anchor** (D-TG-79, contract §1)
- [X] T027 [US1] In the same module, implement `open_item(session, burst)` — inside `chat_lock`: evaluate the rules, `INSERT … ON CONFLICT (telegram_chat_id, telegram_message_id) DO NOTHING RETURNING id`, snapshot `responsible_at(chat, opened_at)`, set `attention_item_id` on every burst member (B3), and set `attention_evaluated_at` on every burst member **whether or not an item resulted** (D-TG-72). ⚠ Never `DO UPDATE` — the same reasoning that made TG-M2's derivation insert-only
- [X] T028 [US1] Create `apps/ai-api/app/workers/tasks/moderation/evaluate_attention.py` — a `@dramatiq.actor` taking a chat, sender, thread and anchoring instant, calling `open_item`. It is the **fast path only**; T053's sweep is the record
- [X] T029 [US1] Edit `apps/ai-api/app/application/moderation/messages.py` so `derive_message`, on inserting a non-moderator message in a measured chat, schedules `evaluate_attention.send_with_options(delay=burst_gap_s * 1000)`. Scheduling happens **after** the insert commits, so the judgement can always see the message it was scheduled for
- [X] T030 [US1] Register `evaluate_attention` in `apps/ai-api/app/workers/main.py` beside the existing moderation actors
- [X] T031 [US1] Add `item_id` to the correlation-identifier whitelist in `apps/ai-api/app/infrastructure/logging.py`, and log opening with `extra={"chat_id": …, "message_id": …, "item_id": …}`. ⚠ Never `extra={"message": …}` — stdlib `logging` rejects it inside `makeRecord` (TG-M0's D-TG-24) — and never any text column (check 4)

**Checkpoint**: Post three messages as a student in a measured group and see **one** item, dated from
the first, with the right rule version and the moderator who owned the group at that instant. The
subject of every later measurement now exists.

---

## Phase 4: User Story 2 — A moderator's answer closes the item, and the gap between is the number (Priority: P2)

**Goal**: A moderator's reply closes the item; the gap is the first-response time; how it was answered
and by whom are recorded separately from who was responsible.

**Independent Test**: With a controlled clock and no network, script a group's traffic — a direct
reply, a plain next message, a message in the wrong thread, one in another group, a reply whose
platform timestamp precedes the question, and one moderator message while three items wait. Confirm
exactly which items close, the kind on each, and the gap against hand computation.

**Depends on**: US1 (there is nothing to close otherwise).

### Tests for User Story 2

- [X] T032 [P] [US2] `apps/ai-api/tests/moderation/attention/test_matching.py` — a direct reply to **any** message of the burst closes the item with kind `direct_reply`; a plain next moderator message in the same chat and thread closes it with kind `group_message`; a message in a different thread, a different chat, from a non-moderator, or from a bot closes nothing
- [X] T033 [P] [US2] In `test_matching.py`, assert the recorded response moment is the reply's **platform** `sent_at` and the gap matches a hand-computed value; and that `first_response_moderator_id` is recorded separately from `responsible_moderator_id` when a colleague answers
- [X] T034 [P] [US2] `apps/ai-api/tests/moderation/attention/test_oldest_only.py` — three open items in one chat and one plain moderator message → **exactly one** closes, the oldest, and the other two stay open. Then a direct reply to the *second*-oldest closes that one **out of order** (C2, C3)
- [X] T035 [P] [US2] In `test_oldest_only.py`, a single message that both directly replies to one item and is the next message after an older one → the **direct reply wins** and only the replied-to item closes (C1)
- [X] T036 [P] [US2] `apps/ai-api/tests/moderation/attention/test_settle_window_lookback.py` — a question at `T` and a moderator reply at `T+20s`, judged at `T+90s`: the item is **answered** with a first-response time of exactly 20 seconds, and appears in the answered count. ⚠ No test of "a reply closes an item" reaches this path — the reply is stored before the item exists (the session's first clarification, C10)
- [X] T037 [P] [US2] `apps/ai-api/tests/moderation/attention/test_out_of_order.py` — a moderator message whose `sent_at` is **not strictly after** `opened_at` closes nothing, asserted with the reply stored **before** the question and again with it stored after. The metric would be silently wrong otherwise (C4)
- [X] T038 [P] [US2] `apps/ai-api/tests/moderation/attention/test_reaction_never_closes.py` — a `message_reaction` update from a mapped moderator on a waiting question leaves the item `open` and changes no field. ⚠ This is the milestone's most tempting wrong implementation (C5)
- [X] T039 [P] [US2] `apps/ai-api/tests/moderation/attention/test_closure_guard.py` — a second closer updates zero rows and leaves the recorded response untouched; a `dismissed` item and an `expired` item are never closed; re-running the matcher over the same messages changes nothing (C8, FR-033, FR-035)
- [X] T040 [P] [US2] `apps/ai-api/tests/moderation/attention/test_tiebreak.py` — two moderator messages with the **identical** `sent_at` → exactly one is recorded as the answering moderator, chosen by the lower `message_id`, and the outcome is the same however many times matching runs (C9)
- [X] T041 [P] [US2] In `test_matching.py`, assert a message from someone who was **not** a moderator at send time closes nothing — even after that person is later made a moderator (relies on TG-M2's write-once `is_from_moderator`, FR-029)

### Implementation for User Story 2

- [X] T042 [US2] In `apps/ai-api/app/application/moderation/attention.py`, implement `_response_predicate(item, message)` — the single expression of `contracts/attention-rules.md` §4: same chat, `is_from_moderator` as stored, not a bot, `sent_at` **strictly** after `opened_at`, and rule (a) or rule (b). Everything else delegates to this
- [X] T043 [US2] Implement `match_response(session, message)` — inside `chat_lock`: resolve rule (a) through `telegram_messages.attention_item_id` from the reply target; if no direct match, resolve rule (b) as `ORDER BY opened_at ASC LIMIT 1` over open items in the same chat **and thread**. Rule (a) is evaluated first (C1, C3, D-TG-83)
- [X] T044 [US2] In `apps/ai-api/app/application/moderation/attention.py`, implement `close_item(session, item_id, message, kind)` as a guarded `UPDATE … SET status='answered', first_response_* WHERE id = :id AND status = 'open'`. Zero rows updated is a normal outcome, not an error (C8)
- [X] T045 [US2] In `apps/ai-api/app/application/moderation/attention.py`, implement `match_existing_responses(session, item)` — called from `open_item` at the moment an item opens, scanning messages already stored after `opened_at` and delegating to the **same** `_response_predicate`. ⚠ One matcher, two entry points (C10, D-TG-82). Do not write a second predicate here
- [X] T046 [US2] Create `apps/ai-api/app/workers/tasks/moderation/match_response.py` and register it in `app/workers/main.py`; have `derive_message` schedule it (no delay) when the inserted message has `is_from_moderator = true`
- [X] T047 [US2] In `apps/ai-api/app/application/moderation/attention.py`, add the tie-break `ORDER BY sent_at, message_id` to both resolution paths, so a re-derivation reaches the same answer as live traffic (C9)

**Checkpoint**: Post a question and reply eight minutes later — the item is answered, the gap is eight
minutes, the kind is recorded, and the responsible moderator is the one who owned the group when the
question was asked. **This is the milestone's core claim, provable from here.**

---

## Phase 5: User Story 3 — What is still waiting is on one screen, oldest first, ageing live (Priority: P3)

**Goal**: One screen showing every question still waiting, longest first, with a live waiting time,
the group, the beginning of what was asked, and who is responsible.

**Independent Test**: Seed items with known starts — some answered, some open, some in groups with no
owner, one whose text has been purged. Load the screen and confirm ordering, displayed waiting times
against hand computation, the unassigned marker, readable Arabic, and times advancing without a reload.

**Depends on**: US1. Reads US2's closures when present but does not require them.

### Tests for User Story 3

- [X] T048 [P] [US3] `apps/ai-control/tests/Feature/LiveAttentionQueueTest.php` — the page loads; open items are ordered longest-waiting first; an answered item is absent from the waiting list; an item whose group has no responsible moderator shows the **Unassigned** marker rather than being omitted or blank; an item whose `original_text` is NULL renders as removed while keeping its timings. `DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase` or `migrate:fresh`
- [X] T049 [P] [US3] In `apps/ai-control/tests/Feature/LiveAttentionQueueTest.php`, assert the page exposes **no** control that posts a message, calls a model, runs a bulk job or triggers a backfill (FR-057)

### Implementation for User Story 3

- [X] T050 [US3] Create `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php` — a custom page with a table over `AttentionItem`, in the existing **Moderation Intelligence** navigation group beside TG-M2's two resources. A page, not a resource: an item is not operator-created CRUD (D-TG-93)
- [X] T051 [US3] Add the five columns of `contracts/control-panel-attention.md` §1 — group, truncated question text, responsible (with the Unassigned badge), status, waiting time — ordered `opened_at ASC`. The waiting time is computed **server-side** on each render; ⚠ never from a browser clock, which would disagree with every other number by the viewer's skew (P3, D-TG-94)
- [X] T052 [US3] In `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`, add `->poll('15s')` to the table, and `dir="auto"` to the group-title and question-text columns. ⚠ Per **field**, not per navigation group — the latter does not exist in Filament v5.7.8, measured by TG-M2's Finding 1. The panel's locale and chrome stay English and LTR (P2, P4, D-TG-95)

**Checkpoint**: The operator opens one screen and sees what is waiting, in the order it should be
worked, with the times advancing on their own.

---

## Phase 6: User Story 4 — The rule set's mistakes are correctable, and the corrections are the measurement (Priority: P4)

**Goal**: An operator dismisses a false positive and hand-opens a missed question; both are recorded as
human acts and both are countable.

**Independent Test**: Open items by rule, dismiss some with reasons, hand-add some against specific
messages, then compute the accuracy figures from stored rows alone and check against hand arithmetic.

**Depends on**: US1, US3 (the screen the actions live on).

### Tests for User Story 4

- [X] T053 [P] [US4] `apps/ai-control/tests/Feature/AttentionDismissTest.php` — dismissing records the reason, the panel account and the moment; the item stops ageing, leaves the unanswered count and contributes no response time; a **double-submitted** dismissal updates zero rows the second time and does not corrupt the first; a later moderator message does not reopen or close it (FR-047, FR-048, C8)
- [X] T054 [P] [US4] `apps/ai-control/tests/Feature/AttentionManualAddTest.php` — a hand-opened item is `source='operator'` with a NULL rule version, dated from the chosen message's `sent_at`, and behaves identically thereafter; opening a second item against a message that already anchors one is **prevented in the form**, with `uq_attention_anchor` as the backstop (FR-049…FR-051, P6)
- [X] T055 [P] [US4] `apps/ai-api/tests/moderation/attention/test_accuracy.py` — from a seeded mix of rule-opened, dismissed and operator-opened items, the precision and recall figures of `contracts/attention-metrics.md` §5 match hand arithmetic, and are **grouped by `rule_version`** (M15)

### Implementation for User Story 4

- [X] T056 [US4] Add the two dismissal row actions to `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php` — *not a real question* and *the message was removed* — both calling `AttentionItem::closeIfOpen()`, both recording `closed_by_user_id`. ⚠ **No bulk action**: dismissing twenty items with one click is how a false-positive count stops meaning anything (P5)
- [X] T057 [US4] Add the *open item by hand* header action to `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php` — pick a stored message, then insert with `source='operator'`, `rule_version=NULL`, `opened_at` from that message's `sent_at`, and set `attention_item_id` on it. Reject an already-anchoring message in form validation (P6)
- [X] T058 [US4] Add a standing footnote to `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`: *"Telegram does not report message deletion in groups; no removal evidence is available."* ⚠ No screen text anywhere may suggest the platform reported a deletion — *message removed* is the operator's judgement, recorded as theirs (P7, FR-053)

**Checkpoint**: The rule set's precision is a number computed from stored rows, not an opinion. That
number is TG-M5's baseline.

---

## Phase 7: User Story 5 — An abandoned question stops distorting today's picture without being forgotten (Priority: P5)

**Goal**: Items past the ceiling expire, stay counted as unanswered forever, and leave the response-time
and oldest-waiting figures.

**Independent Test**: With a controlled clock, seed items straddling the ceiling, run the ageing step
twice, and confirm which expired, that the second run changes nothing, and how each status counts.

**Depends on**: US1.

### Tests for User Story 5

- [X] T059 [P] [US5] `apps/ai-api/tests/moderation/attention/test_ageing.py` — an item past the ceiling becomes `expired` with the moment recorded; one short of it is untouched; a second run changes nothing; a `dismissed` and an `answered` item are never expired
- [X] T060 [P] [US5] In `test_ageing.py`, assert an expired item is counted unanswered, contributes no response time, is excluded from oldest-still-waiting, and is **not reopened** by a much later moderator message (G3, G4)
- [X] T061 [P] [US5] `apps/ai-api/tests/moderation/attention/test_sweep.py` — messages older than the settle window with `attention_evaluated_at IS NULL` are judged by the sweep **without any delayed message ever being delivered**; running it twice changes nothing; a message the sweep judged and declined is marked evaluated and never revisited. ⚠ Every other test in this milestone passes when the delayed message arrives, and this stack's Redis does not guarantee that — `appendonly no`, RDB at 60–3600 s, a volume `make down-hard` deletes (research **Finding 3**)
- [X] T062 [P] [US5] `apps/ai-api/tests/moderation/attention/test_tick.py` — the tick lease admits exactly one caller per interval; a loop iterating ten times within one interval enqueues **once**; and the poll loop enqueues rather than computing (no derived state is written by `telegram_main.py`)

### Implementation for User Story 5

- [X] T063 [US5] Create `apps/ai-api/app/workers/tasks/moderation/expire_stale_items.py` — one set-based guarded `UPDATE attention_items SET status='expired', closed_at=now(), close_reason='expired' WHERE status='open' AND opened_at < now() - :max_age`. Idempotent by its own predicate; no row loop (D-TG-87)
- [X] T064 [US5] Create `apps/ai-api/app/workers/tasks/moderation/sweep_unjudged_bursts.py` — claims messages with `attention_evaluated_at IS NULL AND sent_at < now() - :burst_gap` in `sent_at` order with `FOR UPDATE SKIP LOCKED` (TG-M1's `drain_pending_updates` idiom), assembles each burst and calls `open_item`. ⚠ **This is the authoritative path**; the delayed actor is an optimisation (D-TG-72, D-TG-80)
- [X] T065 [US5] Register both actors in `apps/ai-api/app/workers/main.py`
- [X] T066 [US5] Edit `apps/ai-api/app/telegram_main.py`'s poll loop: once per iteration, call `tick_lease(...)` and on success send `expire_stale_items` and `sweep_unjudged_bursts`. ⚠ **Enqueue only** — `ai-telegram` writes no derived state, exactly as it already only sends `drain_pending_updates` (§7.3, D-TG-86). This is the stack's first periodic execution; research **Finding 4** explains why it goes here and not in a new scheduler

**Checkpoint**: A day-old unanswered question expires on its own, stays in the unanswered count, and
stops pinning the oldest-waiting figure. A lost delayed message costs latency, not items.

---

## Phase 8: User Story 6 — Every number on the screen can be reproduced by hand (Priority: P6)

**Goal**: Per group and per moderator, for a chosen period: asked, answered, median, p90 with its
sample count, max, unanswered as a count and a share, and oldest waiting.

**Independent Test**: Load a fixed set of items with known starts and response moments, including a
group below the percentile floor, and compare every displayed figure against hand computation.

**Depends on**: US1, US2, US5 (all four statuses must be reachable), US3 (the page).

### Tests for User Story 6

- [X] T067 [P] [US6] `apps/ai-api/tests/moderation/attention/test_metrics.py` — median, p90 and max over a fixed answered set match hand computation exactly; `open`, `expired` and `dismissed` items contribute **no** value; the unanswered figure counts `open` and `expired` and excludes `dismissed` from both numerator and denominator (M3, M9, M10)
- [X] T068 [P] [US6] In `test_metrics.py`, assert p90 is **suppressed** below `MODERATION_PERCENTILE_MIN_SAMPLES`; and that zero rows yield **NULL, not 0** — measured, and the difference between "nobody asked" and "answered instantly" (M6, M8)
- [X] T069 [P] [US6] In `test_metrics.py`, assert period selection uses `opened_at` and never `created_at`, inclusive at the start and exclusive at the end, by moving a boundary one second and checking exactly which items move (M1, M2)
- [X] T070 [P] [US6] In `test_attribution.py`, assert a moderator whose ownership changed mid-period is charged each item to whoever owned the group when **that** question was asked (M-A4, FR-044)
- [X] T071 [P] [US6] `apps/ai-control/tests/Feature/AttentionMetricsTest.php` — the figures table renders the counts beside every percentile, the suppression reason instead of a number below the floor, "no data" rather than "0s" for NULL, and **contains no average and no composite score** anywhere. ⚠ "Add an average, it is one line" is this milestone's most likely well-meaning regression (D-TG-92, M17, M18)

### Implementation for User Story 6

- [X] T072 [US6] Create `apps/ai-api/app/application/moderation/metrics.py` — the queries of `contracts/attention-metrics.md` §2–§5, quoted from the contract, as the Python-side definition
- [X] T073 [US6] Create `apps/ai-control/app/Filament/Pages/Concerns/AttentionMetrics.php` — the same SQL for the panel. ⚠ Quote it from the contract; the panel defines **no arithmetic of its own**, and computing percentiles in PHP over a fetched collection would be a second definition of the number this milestone exists to make defensible (P9, D-TG-91)
- [X] T074 [US6] Add the figures table to `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php` with a period filter, per group and per moderator, rendering suppression and NULL per T068. **Not a second navigation entry** — TG-M7 owns Team Performance, and half-building it here would have to be removed later (P11, D-TG-97)
- [X] T075 [US6] Render every moment in `Asia/Riyadh` and every duration in human units, with the store keeping UTC (FR-060)

**Checkpoint**: The operator's spreadsheet and the screen agree. That is the milestone's acceptance.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T076 [P] Extend `apps/ai-api/app/scripts/rederive_chat.py` with `--with-attention`, **default off** — clears `attention_evaluated_at` for the named chat and window, runs the judgement inline, and reports **opened / answered / expired**. A composition root: exempt from the boundary check by directory, as `tg_doctor.py` is (D-TG-89, FR-083)
- [X] T077 [P] `apps/ai-api/tests/moderation/attention/test_rederive_attention.py` — running it twice produces identical state; the three reported counts are correct; and **nothing else backfills** — ordinary derivation opens items only for messages derived from now on, and no screen control triggers it (FR-082)
- [X] T078 [P] `apps/ai-api/tests/moderation/attention/test_edits.py` — an edit that adds a question to a burst with no item opens one anchored on the **edited message**, dated from `edited_at`; an edit to a burst that already has an item — open, answered, dismissed or expired — opens none and alters none; the pre-edit text is never consulted (E1…E4, SC-024)
- [X] T079 [P] Edit `apps/ai-api/app/application/moderation/messages.py`'s `apply_edit` to clear `attention_evaluated_at` on the edited message, so the ordinary sweep re-judges it. ⚠ One judgement path, not two (E5)
- [X] T080 [P] `apps/ai-api/tests/moderation/attention/test_migration_repoint_items.py` — a chat promoted to a supergroup keeps every open item and every closed item's timings, extending TG-M2's re-point. Without it a group's whole waiting queue silently disappears at promotion, with every health signal green (FR-081, SC-022). ⚠ Implemented as: `attention_items` is deliberately **not** re-pointed like assignments — its composite FK to `telegram_messages` (chat, message_id) would either violate outright or silently misattribute the anchor, since message numbering restarts under the new supergroup id (D-TG-71). The test instead proves a migration never deletes or mutates an existing item; see `repoint_for_migration`'s docstring
- [X] T081 [P] Extend the existing silence test in `apps/ai-api/tests/moderation/ingest/` to cover this milestone's four new actors and the panel page: **no outbound call of any kind** (FR-071, FR-072, SC-020)
- [X] T082 [P] Extend `apps/ai-api/tests/moderation/test_boundary_checks.py` for the new modules — `app/domain/moderation/attention.py` must import nothing outside the domain layer; no Telegram or model import appears anywhere in this milestone's code (FR-073)
- [X] T083 [P] Run `scripts/check.sh` check 4 against the new modules and confirm **no `logger.*()` line mentions any text column** (FR-074, SC-019)
- [X] T084 Update `docs/runbooks/tg-operator-prerequisites.md` §C's TG-M3 row if the smoke test's wording drifted from `quickstart.md` §4. ⚠ **Do not edit** `docs/plan/telegram/telegram-moderation-intelligence.md` §10.7 or §13.1 — both need the corrections named in `plan.md`'s **⚠ Two Items for the Operator**, and that is the operator's call, not the agent's. No drift found — §C's TG-M3 row already matches quickstart.md §4 (10:03→10:11 = 8m, direct_reply, attribution snapshot); left unedited
- [X] T085 Run `make check` from the repository root with **Ollama quit and no `TELEGRAM_BOT_TOKEN` set** and confirm it passes offline (SC-018)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
   └─▶ Phase 2 (Foundational)  ── BLOCKING ──┐
                                             │
        ┌────────────────────────────────────┴───────────────┐
        ▼                                                    │
   Phase 3 — US1  🎯 MVP                                      │
        │                                                    │
        ├──▶ Phase 4 — US2  (needs items to close)            │
        ├──▶ Phase 5 — US3  (needs items to show)             │
        ├──▶ Phase 7 — US5  (needs items to age)              │
        │                                                     │
        └──▶ Phase 6 — US4  (needs US1 + US3's page)          │
                     │                                        │
                     └──▶ Phase 8 — US6  (needs US1, US2, US3, US5)
                                  │
                                  └──▶ Phase 9 (Polish)
```

### User Story Dependencies

- **US1** depends only on Phase 2. It is the MVP and the only story that stands entirely alone.
- **US2**, **US3** and **US5** each depend on US1 and on **nothing else** — they can run in parallel
  once US1 lands, by three people or three sessions.
- **US4** depends on US1 and on US3's page, because its actions live there.
- **US6** depends on US1, US2 and US5 (all four statuses must be reachable for the arithmetic to be
  testable) and on US3's page to render into.

### Within Each Story

Tests first, then the pure domain function, then the application layer, then the actor, then the
wiring. The panel's tasks follow the Python side within a story, never precede it.

### Parallel Opportunities

- **Phase 1**: T001–T005 are all `[P]`.
- **Phase 2**: T009–T013 are `[P]` once T006–T008 land.
- **Every story's test block is fully parallel** — they are separate files with no shared fixture
  writes beyond `conftest.py`.
- **Phases 4, 5 and 7 are parallel to each other** once Phase 3 is complete. This is the milestone's
  main opportunity: three independent slices off one foundation.
- **Phase 9**: T076–T083 are all `[P]`; T084 and T085 are last and sequential.

## Parallel Example: Foundational

```
After T006–T008 (schema, one file each in sequence):
  T009  test_migration_0005.py
  T010  test_db_invariants.py
  T011  AttentionItem.php
  T012  locks.py
  T013  tick_lease in ingest.py
        — five files, five agents, no shared edits
```

## Parallel Example: the three independent stories

```
After Phase 3 (US1) is green:
  Agent A → Phase 4 (US2)  app/application/moderation/attention.py + match_response.py
  Agent B → Phase 5 (US3)  apps/ai-control/ — page, columns, poll
  Agent C → Phase 7 (US5)  expire_stale_items.py, sweep_unjudged_bursts.py, telegram_main.py

  ⚠ A and C both touch app/application/moderation/attention.py — A adds the matcher,
     C only calls open_item. Sequence C's T064 after A's T045, or accept one merge.
```

## Implementation Strategy

### MVP first (US1 only)

Phases 1–3 deliver a complete, demonstrable slice: a student's question becomes one item of work,
dated from when they actually spoke, attributed to whoever was responsible then. Nothing closes it yet
and no number is displayed — but the subject of every later measurement exists and is provably
idempotent. **Stop here and the milestone is still worth having**, because the two hardest facts to
retrofit — the burst anchor and the attribution snapshot — are already correct.

### Incremental delivery

1. **Phases 1–3** → items open correctly. Demo: post three messages, see one item.
2. **+ Phase 4** → the product's core claim. Demo: the runbook's 8-minute smoke test, minus the screen.
3. **+ Phase 5** → the operator can see it without `psql`.
4. **+ Phase 7** → the numbers survive a real week rather than a demo afternoon.
5. **+ Phase 6** → the rule set's accuracy becomes measurable, which is what TG-M5 needs.
6. **+ Phase 8** → the acceptance test passes: a hand-computed number matches the screen.
7. **+ Phase 9** → edits, re-derivation, promotion, and the boundary and silence guarantees.

### Suggested MVP scope

**Phases 1, 2 and 3** — 31 tasks. The checkpoint is a real one: post three messages in the dev group
and confirm one item exists with `opened_at` equal to the first message's own send time and the right
moderator attached.

## Notes

- **Tests are required here**, per Principle I and `plan.md`'s enumeration. Four of them
  (T014, T015, T036, T061) exist because a probe proved the obvious test passes while the code is
  broken — those four are the ones not to skip when time runs short.
- **The clock never enters a stored number.** Every time-dependent test uses the controlled clock from
  T004. `opened_at` and `first_response_at` always come from Telegram's own timestamps; `now()` appears
  only in the expiry predicate and the live waiting-time display.
- **No Git action appears in any task** (Principle IV). The branch exists; committing, merging and
  tagging are the operator's.
- **Two corrections to the plan of record are deliberately not made by any task** — §10.7's unique
  constraint and §13.1's literal list. They are escalated in `plan.md` and are the operator's to
  confirm (Principle V).
- **Nothing here reads or writes `injazedu/`** (Principle III), and no test touches a database whose
  name lacks `_test` (Principle II).
