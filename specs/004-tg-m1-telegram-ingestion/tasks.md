---
description: "Task list for TG-M1 — Telegram Event Ingestion"
---

# Tasks: TG-M1 — Telegram Event Ingestion

**Input**: Design documents from `specs/004-tg-m1-telegram-ingestion/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts,
idempotency and retry safety, data integrity, and migrations that transform schema — which is most of
this milestone. `plan.md`'s Constitution Check enumerates the **19 behaviours that earn one**, each
mapped to an FR/SC. Behaviours named exempt there — the poller's sleep loop, the health block's JSON
serialisation, `tg-doctor`'s exact prose, migration column types, Dramatiq's own delivery semantics,
`httpx`'s own retries — get **no** test task here.

Three tests exist because a probe proved the obvious test would pass while the code was broken:
**T060** (a status-only health assertion cannot detect a silently empty block), **T046** (a jump under
a week and a jump after a week are the same observable with opposite meanings), and **T047** (the
identifier reset is invisible unless the test drives the stall condition itself).

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US6, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its tests at
`apps/ai-api/tests/`, migrations at `apps/ai-api/alembic/versions/`, compose at `infra/`, `Makefile`
and `.env.example` at the root. **No `apps/ai-control/` work in this milestone** — TG-M1 has no UI.

⚠ Three placements are load-bearing, not stylistic, and a task that moves them will fail `make check`:
`app/telegram_main.py` at the `app/` root; `ingestion_probe.py` inside `app/application/moderation/`
(**not** `app/application/probes/` — probe 4 proved that fails the gate); `models_moderation.py` in
`app/infrastructure/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration and test scaffolding. Nothing here has behaviour.

- [X] T001 [P] Add the TG-M1 settings to `apps/ai-api/app/infrastructure/config.py` with documented defaults and positive-value validators, following the existing `MODERATION_*` block: `TELEGRAM_API_BASE_URL` (default `https://api.telegram.org`), `TELEGRAM_POLL_TIMEOUT_S` (30), `TELEGRAM_POLL_LIMIT` (100, **and must be 1–100** — the Bot API's own ceiling, D-TG-40), `TELEGRAM_CONFLICT_STANDDOWN_COUNT` (5), `MODERATION_GAP_MIN_SILENCE_S` (300), `MODERATION_STALL_RESYNC_S` (691200 = 8 days) (FR-041, D-TG-33, D-TG-39, D-TG-40)
- [X] T002 [P] Add the same six variables with their defaults to `.env.example`, beside the existing TG-M0 block; `TELEGRAM_BOT_TOKEN` stays empty, never a placeholder shaped like a token (FR-041)
- [X] T003 [P] Create the test package `apps/ai-api/tests/moderation/ingest/__init__.py`
- [X] T004 [P] Add a `tg-doctor` target to `Makefile` invoking `app.scripts.tg_doctor`, following the `doctor` target's shape and help-text convention (FR-036)
- [X] T005 Add the `ai-telegram` service to `infra/docker-compose.yml`: same build context as `ai-api`, command `python -m app.telegram_main`, `mem_limit: 256m`, `depends_on` postgres and redis only, `TELEGRAM_*` and `MODERATION_*` environment passthrough, and **no `ports:` block** (FR-001, FR-002, D-TG-29)

**Checkpoint**: Settings validate, the container is declared, and the test package exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The tables, the provider and the scripted stand-in. Every user story needs all three.

**⚠️ CRITICAL**: No user story work can begin until T007–T017 are complete. T006 blocks *merge*, not
implementation.

- [X] T006 ⚠ **OPERATOR AGREEMENT — the two items in `plan.md` → "Two Items for the Operator".** (a) **FR-019 is corrected, not merely implemented**: the approved spec says the confirmed position "MUST never move backwards", and Telegram's documented random renumbering after a week of silence makes that, read literally, cause permanent silent capture failure. The design gives it one documented exception (D-TG-33). (b) **D-TG-34 accepts a residual data-integrity risk**: after a reset, a recycled `update_id` is silently dropped by `ON CONFLICT`; the `id_epoch` fix was rejected because it makes idempotency depend on a counter never advancing spuriously. Both concern data integrity and one widens an approved requirement, so Constitution Principle V makes them the operator's call. Implementation proceeds meanwhile.
- [X] T007 Create `apps/ai-api/app/infrastructure/models_moderation.py` — the four SQLAlchemy Core tables of `data-model.md` §1–§4 on the metadata imported from `app/infrastructure/models.py`, with every `uq_`/`ck_`/`ix_` named exactly as the data model specifies (FR-008, FR-044)
- [X] T008 Write `apps/ai-api/alembic/versions/0003_moderation_ingest.py` with `down_revision = "0002"`, creating `telegram_updates`, `ingestion_state`, `ingestion_gaps` and `telegram_chats`, and a `downgrade()` that drops all four (FR-044, SC-019)
- [X] T009 [P] Add `apps/ai-api/tests/moderation/ingest/test_migration_0003.py` — upgrade to `0003`, assert the two `UNIQUE` constraints, both `CHECK` constraints and the partial pending index exist, then downgrade to `0002` and assert all four tables are gone (Principle I: migrations that transform schema; SC-019)
- [X] T010 [P] Create `apps/ai-api/app/providers/telegram/errors.py` — the six-class closed taxonomy of `contracts/telegram-provider.md` §4, each with a `retryable` class-var, mirroring `app/application/gateway/errors.py` (FR-005, D-TG-38)
- [X] T011 [P] Create `apps/ai-api/app/providers/telegram/models.py` — `TelegramUpdate` (`update_id`, kind, `chat_id`, and `raw` carrying the whole update), `BotIdentity`, `WebhookInfo`, `ChatMemberStatus`. Model only what routing needs; everything else stays in `raw` so a Bot API addition never breaks ingestion (`contracts/telegram-provider.md` §3)
- [X] T012 Create `apps/ai-api/app/providers/telegram/client.py` implementing the `TelegramProvider` protocol over `httpx`: `get_me`, `get_updates`, `get_webhook_info`, `get_chat_member`. `httpx.Timeout(connect=5, read=35)` — the read timeout **must exceed** the 30 s long poll or every poll aborts at the moment Telegram is legitimately holding the connection (D-TG-39). Map HTTP status and `httpx` exception type to the taxonomy structurally, never by matching message text. **No SDK import** (FR-005, FR-040, D-TG-38)
- [X] T013 In `apps/ai-api/app/providers/telegram/client.py`, honour `429` by waiting exactly `parameters.retry_after` from the response body — in the provider and nowhere else, so no caller may implement its own backoff (FR-005)
- [X] T014 ⚠ In `apps/ai-api/app/providers/telegram/client.py`, make `offset=None` **omit the parameter entirely** rather than send `0`, and add an assertion that a negative offset can never be issued — the docs define it as "All previous updates will be forgotten", a data-loss operation (`contracts/telegram-provider.md` §5, §8)
- [X] T015 Create `apps/ai-api/tests/moderation/ingest/conftest.py` — `FakeTelegramTransport` built on `httpx.MockTransport` (probe 5 confirmed the round trip), scripting the eleven response shapes in `contracts/telegram-provider.md` §7, plus an async session factory against `injaz_ai_test` via `TEST_DATABASE_URL`, following `tests/gateway/conftest.py` (FR-042, Principle II)
- [X] T016 [P] Add `apps/ai-api/tests/moderation/ingest/test_provider_errors.py` — each HTTP status and transport failure maps to its taxonomy class with the right `retryable`; `429` waits `retry_after`; a negative offset is never issued (FR-005, T014)
- [X] T017 Create `apps/ai-api/app/application/moderation/ingest.py` with bot-identity resolution: call `get_me` before anything may be stored, retry with increasing delay **indefinitely** on failure, never fall back to a cached identity, and never fail startup — a machine that boots before its Wi-Fi connects must recover unattended (FR-007a, FR-007b, FR-007d, D-TG-42)
- [X] T018 Create `apps/ai-api/app/telegram_main.py` — the poller entrypoint at the `app/` root (composition root, exempt from the reverse boundary check **by directory**): load settings, configure logging, and exit cleanly doing nothing when no credential is configured (FR-002, FR-007, D-TG-29)
- [X] T019 [P] Add `apps/ai-api/tests/moderation/ingest/test_identity.py` — identity unresolvable leaves the process up and retrying; a rejected credential is distinct from an unreachable platform; nothing is stored and the position does not advance while unresolved (FR-007a–d, SC-023)
- [X] T020 [P] Add `apps/ai-api/tests/moderation/ingest/test_config_ingest.py` — each new setting rejects an out-of-range value at startup with a message naming it; `TELEGRAM_POLL_LIMIT` outside 1–100 is rejected (FR-041, SC-020)

**Checkpoint**: Tables exist and roll back; the provider speaks the Bot API with a closed error
taxonomy; the scripted stand-in drives it with no credential and no network.

---

## Phase 3: User Story 1 — Every event is captured exactly once (Priority: P1) 🎯 MVP

**Goal**: Every update delivered while capture runs is stored exactly once, verbatim, with its true
order recoverable — and schedules exactly one unit of interpretation.

**Independent Test**: Drive capture against the stand-in with a known batch, the same batch again, and
a shuffled batch. Confirm one row per distinct event, one job per newly stored row, content identical
to what was delivered, order recoverable. No credential, no network.

### Tests for User Story 1

- [X] T021 [P] [US1] `apps/ai-api/tests/moderation/ingest/test_idempotency.py` — a batch of 3 stores 3 rows and schedules 3 jobs; the same batch again stores 0 and schedules 0; a shuffled batch stores all and leaves `update_id` ordering recoverable (FR-008, FR-010, FR-011, SC-001, SC-002)
- [X] T022 [P] [US1] In `apps/ai-api/tests/moderation/ingest/test_idempotency.py`, an update of an unmodelled kind is stored as `unknown` and an update carrying no chat is stored with `chat_id` NULL — neither is discarded (FR-012)
- [X] T023 [P] [US1] `apps/ai-api/tests/moderation/ingest/test_append_only.py` — after interpretation, only `processed_at` / `process_error` differ; `payload`, `update_id`, `bot_id` and `received_at` are unchanged (FR-009)
- [X] T024 [P] [US1] In `test_idempotency.py`, assert the platform's own timestamp is what ordering and measurement use, and `received_at` is recorded separately and never substituted (FR-013)

### Implementation for User Story 1

- [X] T025 [US1] In `apps/ai-api/app/application/moderation/ingest.py`, implement `store_batch` as **one** statement — `INSERT … VALUES (…),(…) ON CONFLICT (bot_id, update_id) DO NOTHING RETURNING id, update_id` — so FR-010 and FR-011 are the same operation with no read-then-write race (probe 1b, D-TG-30)
- [X] T026 [US1] In `apps/ai-api/app/application/moderation/ingest.py`, extract `update_type` and `chat_id` for routing; an unrecognised kind becomes `unknown` and a chat-less update stores NULL (FR-012)
- [X] T027 [US1] Create `apps/ai-api/app/workers/tasks/moderation/process_update.py` — the interpreting stub. It sets `processed_at` and records `process_error` on failure, and **derives nothing else**. Setting it twice is the same result (FR-032, FR-033)
- [X] T028 [US1] Register the actor in `apps/ai-api/app/workers/main.py` alongside the existing diagnostics import
- [X] T029 [US1] In `apps/ai-api/app/application/moderation/ingest.py`, schedule interpretation **after the storing transaction commits**, and only for the identifiers `RETURNING` gave back. Enqueueing inside the transaction lets a worker look for a row whose transaction has not committed, or has rolled back and never will (D-TG-36)
- [X] T030 [US1] Wire the poll loop in `app/telegram_main.py`: `get_updates(offset, limit, timeout_s, allowed_updates)` → `store_batch` → schedule, logging with `update_id` and `chat_id` and **no message text** (FR-037)

**Checkpoint**: Post a message in the dev group and see the raw row via `make psql` within seconds.
The append-only spine exists — already more than the repository has today.

---

## Phase 4: User Story 2 — A restart resumes; it does not restart, and it does not lose (Priority: P2)

**Goal**: The confirmed position survives restarts and outages, never runs ahead of what is stored, and
a backlog drains without loss or duplication.

**Independent Test**: Stop mid-stream and restart; confirm the resumed position. Separately make
storage fail for one batch and confirm the position does not advance and the redelivered events store
exactly once.

### Tests for User Story 2

- [X] T031 [P] [US2] `apps/ai-api/tests/moderation/ingest/test_offset.py` — after a restart, capture asks only for events after the stored position; previously stored events are neither redelivered as new nor duplicated (FR-017, SC-003)
- [X] T032 [P] [US2] In `apps/ai-api/tests/moderation/ingest/test_offset.py`, **the sharpest test here**: across every simulated partial-failure interleaving, the confirmed position is at or behind the last successfully stored identifier and never ahead of it (FR-016, FR-018, SC-004)
- [X] T033 [P] [US2] In `apps/ai-api/tests/moderation/ingest/test_offset.py`, a batch where the third row fails to store advances the position only as far as the second (FR-016)
- [X] T034 [P] [US2] In `apps/ai-api/tests/moderation/ingest/test_offset.py`, the store being unavailable leaves the position unmoved and the batch retried; the redelivered events store exactly once (FR-018)
- [X] T035 [P] [US2] `apps/ai-api/tests/moderation/ingest/test_drain.py` — a backlog of at least 100 unhandled rows accumulated while the worker was stopped is handed over in `update_id` order, 100% marked handled, 0 duplicates (FR-020, SC-021)
- [X] T036 [P] [US2] In `test_offset.py`, the subscription set is re-asserted on restart and includes the kinds the platform does not deliver by default (FR-006)

### Implementation for User Story 2

- [X] T037 [US2] In `ingest.py`, update `ingestion_state` after commit — `last_update_id` to the highest **successfully stored** identifier, plus `last_poll_at`, `last_success_at`, `last_event_at` and `consecutive_failures`. `last_event_at` is deliberately separate from `last_success_at`: an empty poll is a success, and a week of them is US3's reset condition (FR-015, FR-016, `data-model.md` §2)
- [X] T038 [US2] In `apps/ai-api/app/application/moderation/ingest.py`, compute the next offset as `last_update_id + 1`, and re-assert `allowed_updates` on every call so FR-006's "re-asserted on every restart" is free rather than a skippable startup step (FR-006, FR-017, D-TG-41)
- [X] T039 [US2] Create `apps/ai-api/app/workers/tasks/moderation/drain_pending_updates.py` — claim in `update_id` order over the partial index with `FOR UPDATE SKIP LOCKED` so it runs alongside live capture (probe 8). The pending index is authoritative; the queue message is an optimisation (FR-020, D-TG-36)

**Checkpoint**: Stop the container five minutes, restart, watch the backlog drain — the runbook's
TG-M1 smoke test, part 2.

---

## Phase 5: User Story 3 — A window that was not observed is marked as not observed (Priority: P3)

**Goal**: Every period during which events could have occurred but could not have been received is
recorded with its reason — and a renumbering is **not** recorded as a loss.

**Independent Test**: Simulate each cause against the stand-in and confirm exactly one window row with
the correct reason and bounds; confirm a silence beyond retention is marked permanently unrecoverable
and a reset is not.

### Tests for User Story 3

- [X] T040 [P] [US3] `apps/ai-api/tests/moderation/ingest/test_gaps.py` — a stop longer than the 5-minute minimum produces exactly one `downtime` row covering the silence (FR-021, FR-022, SC-005)
- [X] T041 [P] [US3] In `apps/ai-api/tests/moderation/ingest/test_gaps.py`, a pause shorter than the minimum produces **zero** rows — a marker that appears on every report means nothing on any report (FR-025, SC-007)
- [X] T042 [P] [US3] In `apps/ai-api/tests/moderation/ingest/test_gaps.py`, a window longer than 24 h is marked `unrecoverable` (FR-023, SC-006)
- [X] T043 [P] [US3] In `apps/ai-api/tests/moderation/ingest/test_gaps.py`, every row carries start, end, reason and detection time, and two adjacent downtime windows stay two rows — never silently merged or deleted (FR-021, SC-006)
- [X] T044 [P] [US3] In `apps/ai-api/tests/moderation/ingest/test_gaps.py`, `open_gaps` is visible in the health report (FR-021 scenario 6 — asserted against the block US5 builds in T068; skip until then if running US3 alone) — written as `pytest.mark.skip`, pending T068
- [X] T045 [P] [US3] `apps/ai-api/tests/moderation/ingest/test_reset.py` — an identifier jump with a **recent** `last_event_at` produces one `update_id_jump` row, `unrecoverable=true`, and capture continues from the identifier actually received rather than stalling (FR-024, SC-008)
- [X] T046 ⚠ [P] [US3] In the same file, an identifier jump with `last_event_at` **older than a week** is **not** an `update_id_jump`. Same observable, opposite meaning: under a week it is a real loss, after a week it is Telegram renumbering. Conflating them either invents losses or hides them (D-TG-33, `contracts/ingestion-guarantees.md` G4)
- [X] T047 ⚠ [P] [US3] In `apps/ai-api/tests/moderation/ingest/test_reset.py`, the reset case end to end: successful empty polls, `last_event_at` 9 days old, then a re-sync with `offset` **omitted** returns a **lower** identifier → it is stored, the position moves **backwards**, and one `update_id_reset` row is written with `unrecoverable=false` (FR-019's one exception, D-TG-33)
- [X] T048 ⚠ [P] [US3] In the same file, assert `update_id_reset` is **not** treated as missing data — a report window overlapping it must not be marked incomplete. Marking it would be dishonest in the opposite direction from the one this domain guards against (`contracts/ingestion-guarantees.md` G4)

### Implementation for User Story 3

- [X] T049 [US3] In `ingest.py`, detect downtime on startup by comparing `last_success_at` against now, and write a `downtime` row only when the silence exceeds `MODERATION_GAP_MIN_SILENCE_S`; set `unrecoverable` when it exceeds 24 h (FR-021, FR-022, FR-023, FR-025)
- [X] T050 [US3] In `apps/ai-api/app/application/moderation/ingest.py`, detect an identifier jump — next identifier above `last_update_id + 1` — and branch on `last_event_at`: under a week, write `update_id_jump` with `unrecoverable=true` and continue from what arrived; a week or more, take the reset path (FR-024, T046)
- [X] T051 ⚠ [US3] Implement the reset protocol of `contracts/telegram-provider.md` §5: when polls succeed, return empty, and `last_event_at` is older than `MODERATION_STALL_RESYNC_S`, re-sync by calling `get_updates(offset=None, …)`, adopt whatever identifier returns **even a lower one**, and write `update_id_reset` with `unrecoverable=false`. **Never a negative offset.** Without this the poller goes silent forever while every health signal stays green (FR-019 exception, D-TG-33)

**Checkpoint**: Every report from TG-M7 onward can say "this window is incomplete" instead of silently
under-counting — and can avoid saying it when nothing was actually lost.

---

## Phase 6: User Story 4 — Groups appear by themselves, and losing coverage is visible (Priority: P4)

**Goal**: Adding the bot to a group creates its record with the bot's standing; demotion and removal
are visible; a supergroup promotion keeps one history.

**Independent Test**: Feed the stand-in the add/promote/demote/remove events and confirm the record
and each standing change; feed a promotion and confirm both directions are linked with nothing lost.

### Tests for User Story 4

- [X] T052 [P] [US4] `apps/ai-api/tests/moderation/ingest/test_chats.py` — a `my_chat_member` add creates the row with identifier, kind, title, standing and observation time (FR-026, SC-009)
- [X] T053 [P] [US4] In `apps/ai-api/tests/moderation/ingest/test_chats.py`, all four standing changes — added, promoted, demoted, removed — update the record, and `bot_can_delete` is recorded as an observation only (FR-027, SC-010)
- [X] T054 ⚠ [P] [US4] In `apps/ai-api/tests/moderation/ingest/test_chats.py`, a group seen only through an ordinary message gets a row with `bot_status = 'unknown'` — **never guessed**. Guessing `administrator` would hide exactly the coverage failure §20.2 calls the one most likely to go unnoticed (FR-028, D-TG-43)
- [X] T055 [P] [US4] In `apps/ai-api/tests/moderation/ingest/test_chats.py`, a new chat is **not** monitored, and events from an unmonitored chat are still stored while producing no interpreted state (FR-030, FR-031, SC-012)
- [X] T056 [P] [US4] `apps/ai-api/tests/moderation/ingest/test_migration_supergroup.py` — a promotion links old and new rows in both directions with 0 events lost and 0 double-counted across the change (FR-029, SC-011)

### Implementation for User Story 4

- [X] T057 [US4] In `ingest.py`, upsert `telegram_chats` from **any** chat-bearing update — identity fields and `last_event_at` — because a bot already present before capture started never emits a standing-change update, and those are precisely the groups a pilot begins with (FR-026, FR-028, D-TG-43)
- [X] T058 [US4] In `apps/ai-api/app/application/moderation/ingest.py`, write `bot_status`, `bot_status_at` and `bot_can_delete` **only** from `my_chat_member`, leaving `unknown` otherwise (FR-027, FR-028, D-TG-43)
- [X] T059 [US4] In `apps/ai-api/app/application/moderation/ingest.py`, handle `migrate_to_chat_id` / `migrate_from_chat_id`: write both columns on both rows so the pair is navigable from either side. Re-point no derived state — none exists until TG-M2 (FR-029, D-TG-44)

**Checkpoint**: The operator adds the bot to a group and the group appears, with no identifier copied
by hand.

---

## Phase 7: User Story 5 — The operator can tell capture is healthy without a database query (Priority: P5)

**Goal**: One health block answers "is ingestion working"; one command answers "is it set up
correctly".

**Independent Test**: Assemble the block from known state, including on a system that has never
captured anything. Run the diagnostic in each of its five setup shapes.

### Tests for User Story 5

- [X] T060 ⚠ [P] [US5] `apps/ai-api/tests/moderation/ingest/test_health_block.py` — assert the block's **contents**: all eight required fields present and populated. **Never assert only `status == "ok"`** — probe 3 proved that passes while the block is silently empty (FR-034, SC-013)
- [X] T061 [P] [US5] In `apps/ai-api/tests/moderation/ingest/test_health_block.py`, the block renders with nulls and zeros — not an exception — on a system that has never captured anything (SC-013)
- [X] T062 [P] [US5] In `apps/ai-api/tests/moderation/ingest/test_health_block.py`, the four credential/identity states are distinct and readiness is identical in all of them; collapsing any two misleads an operator debugging a real outage (FR-007c, FR-035, SC-023)
- [X] T063 [P] [US5] In the same file, `health.py` adds **no** ProbeSpec when the composition-root state attribute is absent (D-TG-31)
- [X] T064 [P] [US5] `apps/ai-api/tests/moderation/ingest/test_tg_doctor.py` — the five setup states are reported distinctly, and no credential exits **0** because the command must run on a machine that holds none (FR-036, SC-014)
- [X] T065 [P] [US5] In `apps/ai-api/tests/moderation/ingest/test_tg_doctor.py`, the credential is never printed, not even truncated (FR-039)
- [X] T066 [P] [US5] `apps/ai-api/tests/moderation/ingest/test_ingest_logging.py` — capture log lines carry `update_id`/`chat_id` and contain no message text; the correlation key is `message_id`, never `message`, and the test calls `setLevel` so the stdlib `KeyError` can actually fire (FR-037, SC-017, TG-M0 D-TG-24)

### Implementation for User Story 5

- [X] T067 ⚠ [US5] In `apps/ai-api/app/application/health_service.py`, add `ingestion: dict[str, Any] | None = None` as a **declared field** on `ComponentReport`, beside `gateway`. `frozen=True` without `extra="forbid"` means an ad-hoc keyword is accepted and silently dropped (probe 3, D-TG-32)
- [X] T068 [US5] Create `apps/ai-api/app/application/moderation/ingestion_probe.py` — the eight required fields plus `credential`, `bot_identity` and `stood_down`, per `contracts/health-ingestion.md` §1. **Inside the moderation boundary by necessity**: probe 4 proved `app/application/probes/` fails the gate (D-TG-31)
- [X] T069 [US5] In `apps/ai-api/app/main.py` (composition root, exempt by directory), construct the probe during startup and store the callable on `app.state` (D-TG-31)
- [X] T070 [US5] In `apps/ai-api/app/api/v1/health.py`, add the `ProbeSpec` **only when that state attribute is present**, with `required=False`. This file must import **nothing** from moderation (FR-034, FR-035, D-TG-31)
- [X] T071 [US5] Create `apps/ai-api/app/scripts/tg_doctor.py` — composition root, exempt by directory. Reports credential presence, `getMe`, that the inbound delivery mechanism is **not** configured, the subscription set against configuration, and per-chat bot standing; exit codes per `contracts/health-ingestion.md` §2 (FR-036)

**Checkpoint**: `make health` and `make tg-doctor` both answer usefully — including with no credential.

---

## Phase 8: User Story 6 — The bot stays silent, and the machine stays closed (Priority: P6)

**Goal**: Nothing is ever sent to a chat, nothing listens for inbound connections, and one credential
never has two competing consumers.

**Independent Test**: Inspect the change set for any send/react/delete/ban/restrict call and confirm
none exists; confirm no inbound port and no configurable webhook; run the full gate offline with no
credential.

### Tests for User Story 6

- [X] T072 [P] [US6] `apps/ai-api/tests/moderation/ingest/test_no_outbound.py` — assert no `sendMessage`, `setMessageReaction`, `deleteMessage`, `banChatMember` or `restrictChatMember` method exists on the provider, and no such call appears anywhere in the change set. Absence is normally a smell to test; here silence is a headline guarantee whose violation is a visible incident in a real student group (FR-038, SC-015)
- [X] T073 [P] [US6] In the same file, `setWebhook` is not implemented and `infra/docker-compose.yml`'s `ai-telegram` service declares no `ports:` (FR-001, SC-015)
- [X] T074 [P] [US6] `apps/ai-api/tests/moderation/ingest/test_conflict_standdown.py` — five consecutive conflicts stop polling, write one `conflict_409` gap row, and report `stood_down` in the health block; a single conflict followed by a success resets the counter and leaves capture running (FR-004a, FR-004b, FR-022, SC-022)
- [X] T075 [P] [US6] In `apps/ai-api/tests/moderation/ingest/test_conflict_standdown.py`, a second capture process against the same credential on the same machine is refused the lease and stands down rather than competing (FR-003, FR-005 scenario 5)

### Implementation for User Story 6

- [X] T076 [US6] In `ingest.py`, claim the Redis lease `ai:tg:poll:lease` with `SET … PX … NX`, reusing the fencing-token and watchdog pattern proved in `app/application/gateway/lanes.py`. Redis holds **a lock, never a fact** (FR-003, D-TG-37)
- [X] T077 [US6] In `apps/ai-api/app/application/moderation/ingest.py`, on `TelegramConflictError`, increment `consecutive_conflicts`, back off with increasing delay, and at `TELEGRAM_CONFLICT_STANDDOWN_COUNT` set `stood_down_at`, write the `conflict_409` gap row and stop polling until an explicit restart. A successful poll resets the counter. Retrying forever makes the two consumers alternate and lose events on **both** sides while each looks healthy (FR-004a, FR-004b, D-TG-37)

**Checkpoint**: The two non-negotiable guarantees are mechanically demonstrated, not asserted in prose.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T078 [P] Add the `ai-telegram` service to `make up`'s default set and to `make logs`, and confirm `make mem-report` stays inside the 5 GB budget with the new 256 MB container (D-TG-29)
- [X] T079 [P] Update `README.md`'s service list and `docs/plan/telegram/telegram-api-capabilities.md` with the two facts re-verified in this milestone: `getUpdates` `limit` is capped at 100, and the identifier is chosen **randomly** after a week of silence (D-TG-33, D-TG-40)
- [X] T080 Run the full gate three ways and confirm all three are green: `make check`; `TELEGRAM_BOT_TOKEN= make check`; and `make check` with Ollama quit and no network (FR-042, SC-016)
- [X] T081 Run the migration round-trip — `make migrate`, `make migrate-down`, `make migrate` — and confirm `0003` applies and reverses cleanly (SC-019)
- [X] T082 ⚠ **OPERATOR — runbook §B in full**: both bots created with privacy **disabled before the first group add**, a dev group with two other accounts, the bot promoted to administrator there, and the dev token in `.env`. Every automated test above runs without this; only the smoke test blocks (Dependencies, `quickstart.md` §1). Verified against `injaz_ai`: `telegram_chats` shows the dev group discovered, `bot_status='administrator'`, `is_monitored=true`
- [X] T083 ⚠ **OPERATOR — the smoke test**, `quickstart.md` §3: post in the dev group and see the raw row within seconds; then stop `ai-telegram` for five minutes, post during the outage, restart, and confirm the backlog drains and **exactly one** `downtime` gap row exists (runbook §C TG-M1 row). Verified: 14 rows in `telegram_updates`; `ingestion_gaps` has a `downtime` row (~23 min window, `unrecoverable=false`)
- [X] T084 Walk `quickstart.md` end to end and correct anything that has drifted, including the §6 probe commands and the §8 troubleshooting table. **Found materially more than prose drift**: `app/telegram_main.py` had only ever been wired for Phase 3 (US1) — none of Phases 4-8's tested `ingest.py` functions (durable offset, gap/stall detection, chat discovery, lease, conflict stand-down) were ever called from the real poller, and it had no dramatiq broker configured at all, so `store_batch`'s default scheduling would have thrown against an unreachable default broker on the first real captured update. Rewired `telegram_main.py` in full, registered `drain_pending_updates` on the worker (also never wired), and added `tests/moderation/ingest/test_telegram_main.py`. Separately found and fixed two more gaps surfaced only by running against a real credential for the first time: `httpx`'s own INFO logging put the bot token in plaintext into every log line (Telegram's Bot API embeds it in the URL path) — fixed in `app/infrastructure/logging.py`, regression-tested in `test_credential_never_logged.py` — and `docker-compose.yml`'s `ai-api`/`migrate` services never passed `TELEGRAM_*` through, so `/health` and `tg-doctor` could never report anything but "absent" regardless of `.env`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: needs Phase 1 — **blocks every user story**. T006 blocks merge, not work
- **Phases 3–8 (User Stories)**: all need Phase 2. US1 → US2 is a genuine sequence; US3–US6 are independent of each other
- **Phase 9 (Polish)**: needs the stories you intend to ship

### User Story Dependencies

| Story | Depends on | Why |
|---|---|---|
| **US1** (P1) | Phase 2 only | The spine. Nothing else means anything without it |
| **US2** (P2) | Phase 2, **US1** | The position is only meaningful once rows exist to be behind |
| **US3** (P3) | Phase 2, **US2** | A gap is defined against `last_success_at`/`last_event_at`, which US2 writes |
| **US4** (P4) | Phase 2, US1 | Chat rows are written from stored updates |
| **US5** (P5) | Phase 2 | Renders whatever state exists, including none. T044's and T074's health assertions land here |
| **US6** (P6) | Phase 2 | The lease is independent; the stand-down's gap row shares US3's table but not its logic |

**Not independent, and deliberately so:** US2 → US3 is the one real chain in this milestone. Everything
downstream of "was this window observed?" needs "where had we got to?" first.

### Within Each Story

Tests first, and they must fail before implementation. Provider before application; application before
worker; migration before anything that reads a table.

### Parallel Opportunities

- T001–T004 (Setup) are four different files
- T009–T011, T016, T019, T020 within Foundational
- Every `[P]` test inside a story — they are separate files or separate cases in one file with no shared fixture state
- **US4, US5 and US6 can be built in parallel** by three people once Phase 2 is done; US1 → US2 → US3 is one lane

---

## Parallel Example: Foundational

```bash
# After T007 and T008 land, these are four independent files:
Task: "T009 migration round-trip test in tests/moderation/ingest/test_migration_0003.py"
Task: "T010 error taxonomy in app/providers/telegram/errors.py"
Task: "T011 update models in app/providers/telegram/models.py"
Task: "T020 settings validation in tests/moderation/ingest/test_config_ingest.py"
```

## Parallel Example: the three independent stories

```bash
# Once Phase 2 is complete:
Developer A: US1 → US2 → US3   (T021–T051, the capture lane)
Developer B: US4                (T052–T059, chats and coverage)
Developer C: US5 → US6          (T060–T077, observability and silence)
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 → Phase 2 → Phase 3 (T001–T030).
2. **Stop and validate**: drive the stand-in with a duplicate batch and a shuffled batch; then post a
   real message in the dev group and see the row via `make psql`.
3. At that point the append-only spine exists and is provably exactly-once — and the events it holds
   are events Telegram will never hand over again.

### Incremental delivery

| After | You have | Milestone unblocked |
|---|---|---|
| US1 | An exactly-once, replayable record of everything the bot observes | **TG-M2** — nothing can be derived without it |
| + US2 | Downtime that costs nothing under 24 h | Development without babysitting the container |
| + US3 | Reports that can admit what they do not know | **TG-M7** — the "incomplete data" marker |
| + US4 | Groups that discover themselves; coverage loss made visible | **TG-M2** — monitored groups and ownership |
| + US5 | One place to see whether capture is alive | Operating the TG-M3 pilot at all |
| + US6 | The silence guarantee, mechanically demonstrated | **TG-M6** — the first milestone that sends anything |

**US1 and US2 are the pair not to split.** Capture without durable position resumption loses a window
on every restart, and unlike a bug in interpretation, that loss is permanent — there is no history API
to re-fetch from.

### Suggested MVP scope

Phases 1–3 (T001–T030) — 30 tasks.

---

## Notes

- `[P]` = different files, no dependency on incomplete work
- Every task names its file path; every user-story task carries its `[US#]` label
- Tests are written first within each story and must fail before implementation
- Commit after each task or logical group — **operator action** (Constitution Principle IV)
- **All database tests run against `injaz_ai_test` via `TEST_DATABASE_URL`.** M0's session guard in `tests/conftest.py` already aborts otherwise and is unchanged here (Principle II)
- **No `apps/ai-control/` task exists.** The panel gets its Moderation Intelligence navigation group at TG-M7
- **No `injazedu/` task exists**, and none may be added — the source plan's §24 states it for the whole track (Principle III)
- **Nine tasks carry a ⚠**, each encoding a measured finding or an operator decision: **T006** (two items needing the operator's explicit agreement), **T014**/**T051** (the identifier-reset protocol — omit `offset`, never negate it), **T046**/**T047**/**T048** (a jump under a week and after a week are opposite meanings; the reset must move the position backwards; it is not a loss), **T054** (never guess `administrator`), **T060**/**T067** (the health block is silently dropped unless declared, and a status-only assertion cannot tell), and **T082**/**T083** (operator prerequisites and the smoke test)
