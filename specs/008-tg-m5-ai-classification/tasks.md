---
description: "Task list for TG-M5 — AI Classification"
---

# Tasks: TG-M5 — AI Classification

**Input**: Design documents from `specs/008-tg-m5-ai-classification/`
**Prerequisites**: `plan.md` (four operator items — **all approved 2026-09-27**), `spec.md`, `research.md`,
`data-model.md`, `contracts/`, `quickstart.md`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts and model-gateway
boundaries, AI pipeline behaviour (prompting, schema validation, output shape), business rules, idempotency and
retry safety, and data-transforming migrations — which is this milestone. `plan.md`'s Constitution Check enumerates
the behaviours that earn one. Behaviours it names exempt — Filament page, table and action wiring; Eloquent casting;
Dramatiq delivery; Redis `SET NX PX` semantics; the Compose service definition; JSON serialisation; the model's
*quality* — get **no** test task here.

**Six tests exist because a finding or probe proved the obvious test would pass while the code was broken:**
**T012** (a profile without `reasoning_effort` must digest byte-identically, and one with it must send it — the
unextended provider silently drops it and every answer is cut off, research **Finding 1**), **T031** (a scripted
fake never truncates; only an injected `ModelTruncatedError` shows that a cut-off answer is retried three times by a
default gateway, **Finding 6**), **T045** (a classifier reading `telegram_messages` passes every test that never
edits a message, **Finding 5**), **T044** (redaction tested on a string passes while the gateway's debugging capture
stores the original — only a real `AccountingWriter` with capture on proves it), **T052** (every actor on one queue
passes every functional test while a busy model stalls message processing, **Finding 4**), and **T016** (a plain
foreign key on the prediction id accepts a link to another message's prediction — probe 9 E2/E3).

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US7, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its new tests at
`apps/ai-api/tests/moderation/classification/`, gateway tests at `apps/ai-api/tests/gateway/`, migrations at
`apps/ai-api/alembic/versions/`. Panel at `apps/ai-control/` — models at `app/Models/`, new pages at
`app/Filament/Pages/` (following `LiveAttentionQueue.php`), feature tests at `tests/Feature/`.

⚠ Five rules are load-bearing, not stylistic:

- **One definition each.** Eligibility (E1–E8) and routing (R1–R6) live **only** in
  `app/domain/moderation/classification.py`, pure. The classifier calls them; the panel reads their **stored**
  outputs; **no test helper computes an expected route or eligibility** — tests call the function or assert the
  stored row (pipeline contract N7).
- **A prediction is never updated or deleted.** No `UPDATE`/`DELETE` on `message_classifications` or
  `message_classification_attempts` from any code path; the panel models throw (D-TG-147).
- **The model sees only the redacted, first-posted words.** Text comes from the message's captured event
  (`source_update_id`), never from `telegram_messages`; `redact()` runs before the gateway; the request is
  `system` + `user`, nothing else (pipeline §4).
- **No message text, redacted text or raw model output in any log line.** Log `message_id`, `chat_id`,
  `incident_id`, and a gateway error's `category` — never `str(exc)`, which for a schema failure echoes model
  output. Name the redacted string `redacted_text` so `scripts/check.sh` check 4 guards it.
- **Moderation reaches the model only through `app.application.gateway`.** Never import `app.providers.llm`,
  `httpx`, `ollama` or `openai` from a moderation module (Finding 3). Never write the Bot API's admin method names
  anywhere in application source — `tests/moderation/ingest/test_no_outbound.py` scans for them.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The four settings, the dedicated classifier service (operator item 2), and the test scaffolding.

- [X] T001 [P] Add a `# --- AI Classification (TG-M5, optional, defaulted) ---` block to `apps/ai-api/app/infrastructure/config.py`: `moderation_confidence_floor: float = 0.60` (`MODERATION_CONFIDENCE_FLOOR`), `moderation_incident_confidence: float = 0.85` (`MODERATION_INCIDENT_CONFIDENCE`), `moderation_classify_max_attempts: int = 5` (`MODERATION_CLASSIFY_MAX_ATTEMPTS`), `moderation_classify_retry_base_s: int = 30` (`MODERATION_CLASSIFY_RETRY_BASE_S`). A `field_validator(..., mode="before")` maps `""` to the default for all four (as `_empty_telegram_bot_token_is_absent` does); a `model_validator(mode="after")` requires `0 ≤ floor ≤ threshold ≤ 1` and both integers positive, each message naming the key (D-TG-143, FR-026)
- [X] T002 [P] Add the four keys with their defaults to `.env.example` beside the TG-M4 block, with a one-line comment that confidence is the model's self-report and not a safety signal (plan item 3)
- [X] T003 [P] In `infra/docker-compose.yml`: change `ai-worker`'s command to add `"--queues", "default"`; add an `ai-classifier` service — `build: ../apps/ai-api`, `command: ["dramatiq", "app.workers.main", "--queues", "moderation_classify", "--processes", "1", "--threads", "1"]`, the same environment block as `ai-worker` plus `MODERATION_CONFIDENCE_FLOOR: ${MODERATION_CONFIDENCE_FLOOR:-0.60}`, `MODERATION_INCIDENT_CONFIDENCE: ${MODERATION_INCIDENT_CONFIDENCE:-0.85}`, `MODERATION_CLASSIFY_MAX_ATTEMPTS: ${MODERATION_CLASSIFY_MAX_ATTEMPTS:-5}`, `MODERATION_CLASSIFY_RETRY_BASE_S: ${MODERATION_CLASSIFY_RETRY_BASE_S:-30}`, and M1's `GATEWAY_*` keys each as `${KEY:-<M1 default>}` (`GATEWAY_CAPTURE_PAYLOADS` defaulting to `false`), `mem_limit: 384m`, `depends_on` postgres and redis healthy. A comment cites research **Finding 4** and operator item 2 — approved (D-TG-148)
- [X] T004 [P] `apps/ai-api/tests/moderation/classification/test_config_classification.py` — defaults; each key set to `""` reads its default; floor `0.9` with threshold `0.8` refused; `1.2` and `-0.1` refused; attempts `0` refused; every message names its key
- [X] T005 [P] Create `apps/ai-api/tests/moderation/classification/__init__.py` and `conftest.py`: an async session factory against `injaz_ai_test` following `tests/moderation/incidents/conftest.py`; reuse its chat / user / moderator / assignment factories and its `insert_message` builder, extended so every message is created **from a captured `message` event** whose payload carries the text (the classifier reads the payload, not the row); an `insert_prediction(...)` builder writing `message_classifications` directly; a `classification_redis` fixture (real local Redis, a per-run key prefix, cleaned up on teardown — as `tests/gateway/conftest.py`'s `gateway_redis`); and `scripted_gateway(responses=None, fail_with=None, capture_payloads=False)` returning `(gateway, provider_calls)` — a `Gateway` over a test `ProfileRegistry` with an active `moderation` profile, `llm_provider_factory` returning a `FakeLLMProvider` with **scripted** responses (M1's fake cannot synthesise `Literal` fields — research probe 7), the gateway tests' lane and breaker wiring, a real `AccountingWriter` on the test session factory, and `max_retries=0`

**Checkpoint**: settings validate; the stack definition isolates classification; tests can build messages from
captured events and a gateway whose every answer is scripted.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: M1's four additive extensions (operator item 1), revision `0007`, the pure domain functions, the
instruction, the shared Python pieces, and the panel's read-only models.

**⚠ CRITICAL**: No user story work can begin until this phase is complete.

### M1 gateway — four additive extensions (operator item 1 — approved)

- [X] T006 [P] In `apps/ai-api/app/domain/model_profile.py`: `Role = Literal["llm", "embedding", "moderation"]`; add `GenerationRole = Literal["llm", "moderation"]` with a one-line comment that it is the generation subset of `Role` (D-TG-131)
- [X] T007 [P] In `apps/ai-api/app/providers/llm/base.py`: add `model_run_id: int | None = None` to `TextResponse` and `StructuredResponse` (D-TG-133). Nothing else in the module changes
- [X] T008 [P] In `apps/ai-api/app/providers/llm/openai_compatible.py` `_bound_params`: when `profile.params` contains `"reasoning_effort"`, set `payload["reasoning_effort"]` to it; otherwise send exactly what is sent today. Docstring cites research **Finding 1** (probe 3: `reasoning_effort: "none"` works, `think: false` is ignored) (D-TG-130)
- [X] T009 In `apps/ai-api/app/application/gateway/accounting.py`: `AccountingLike.record(...) -> int | None`; `NullAccountingWriter.record` returns `None`; `AccountingWriter.record` inserts with `.returning(model_runs.c.id)` and returns the id, returning `None` from its existing swallowed-failure path (M1 FR-040 unchanged) (D-TG-133)
- [X] T010 In `apps/ai-api/app/application/gateway/gateway.py`: `generate_text(self, req, *, role: GenerationRole = "llm")` and `generate_structured(self, req, *, role: GenerationRole = "llm")` resolve `self._registry.resolve(role)` and keep the `llm` provider factory and `llm` lane; `_call` attaches the id returned by `accounting.record` to a successful result via `result.model_copy(update={"model_run_id": run_id})`; `_generation_params` adds `"reasoning_effort"` **only when** the profile's params carry it, so existing profiles' `request_digest` is byte-identical. `embed` / `embed_many` untouched (D-TG-130, D-TG-131, D-TG-133)
- [X] T011 In `apps/ai-api/app/application/gateway/__init__.py` (empty today): re-export `Gateway`, `Message`, `StructuredRequest`, `StructuredResponse`, `GatewayError`, `NoActiveProfileError`, `ProviderUnreachableError`, `ModelTimeoutError`, `CircuitOpenError`, `ModelTruncatedError`, `StructuredOutputInvalidError`, with `__all__`. Docstring cites research **Finding 3**: moderation modules import the gateway's vocabulary from here, never from `app.providers.llm` (D-TG-132)
- [X] T012 [P] `apps/ai-api/tests/gateway/test_role_and_extensions.py` — `role="moderation"` resolves the active moderation profile and the default resolves `llm`; a `moderation` role never touches the embed lane; with an `httpx.MockTransport` provider, a profile whose params carry `reasoning_effort` sends it and one without sends **no** such key; the `request_digest` of a request against a profile without it equals the digest computed before this change (pin the expected hex); a successful call's response carries the `model_runs.id` just written; `NullAccountingWriter` yields `model_run_id is None`. ⚠ **Finding 1**: without the forwarding every classification is cut off — a test that only checks role selection passes against that broken provider. The existing `tests/gateway/` suite must still pass unchanged

### Revision `0007`

- [X] T013 In `apps/ai-api/app/infrastructure/models_moderation.py`: append `message_classifications` and `message_classification_attempts` on the shared `metadata`, exactly per `data-model.md` §2–§3 — every column, `uq_classification_identity`, both composite FKs to `telegram_messages`, **every** `ck_classification_*` and `ck_attempt_*` constraint, and the five indexes (three partial via `postgresql_where`); add `prompted_by_classification_id` to the existing `moderation_incidents` Table with `fk_incident_classification`, `fk_incident_prompted_by`, `ck_incident_ai_link`, `ck_incident_prompted_by` (`data-model.md` §4). No text column anywhere
- [X] T014 Create `apps/ai-api/alembic/versions/0007_moderation_classification.py`, down-revision `0006`. `upgrade()`: drop and re-add `ck_model_profiles_role` with `'moderation'`; create both tables and their indexes; add the `moderation_incidents` column and its four constraints; add `fk_attention_classification` on `attention_items` — every statement exactly as `data-model.md` §1–§5 (research probe 9 ran them verbatim). `downgrade()`: reverse in dependency order, restoring the two-role check. **No `GRANT`** (probe 9), no view, no data backfill. Module docstring cites research Findings 1–6 in one line each, as `0006`'s does
- [X] T015 [P] `apps/ai-api/tests/moderation/classification/test_migration_0007.py` — upgrade to `0007`: both tables, the new column and every named constraint exist; downgrade to `0006`: all gone and `ck_model_profiles_role` is two-role again; upgrade again. Column types not asserted (exempt)
- [X] T016 [P] `apps/ai-api/tests/moderation/classification/test_db_invariants.py` — research probe 9's twelve planted violations, each **directly in SQL** and each expected to raise the named constraint: model-opened incident without a prediction; an operator flag prompted by **another message's** prediction; a model-opened incident citing another message's prediction; a model-opened incident carrying a prompted-by; a second current prediction; confidence `1.3`; a possible violation without a reason; a catch-up prediction routed to `incident`; a second active `moderation` profile; a duplicate exclusion; a failure naming no model; a floor above its threshold. Plus: an exclusion with a failure reason and a failure with an exclusion reason are refused. ⚠ **Probe 9 E2/E3**: a plain FK on the prediction id accepts the cross-message links — only the composite key refuses them

### Pure domain

- [X] T017 [P] In `apps/ai-api/app/domain/moderation/attention.py`: rename `_matches_ack_stoplist` to public `is_acknowledgement(text: str) -> bool`, update its one caller in `evaluate`, keep the docstring and behaviour byte-identical. TG-M3's `test_stoplist.py` and `test_rules_v1.py` must pass unchanged (D-TG-137)
- [X] T018 Create `apps/ai-api/app/domain/moderation/classification.py` — **pure** (no I/O, no clock, no session, standard library and `app.domain.moderation.attention` only): the seven `CATEGORIES`, four `SEVERITIES`, `VIOLATION_CATEGORIES = {"SPAM_OR_AD","ABUSE"}`, `INCIDENT_CATEGORIES = {"SPAM_OR_AD","ABUSE","OTHER"}`, `TAXONOMY_VERSION = 1`; a frozen `MessageFacts` dataclass (`is_service`, `media_kind`, `text`, `text_removed`, `is_from_moderator`, `sender_chat_id`, `group_chat_id`, `is_automatic_forward`); `eligibility(facts) -> str | None` returning the first matching reason of pipeline contract §3 E1–E8 in order, or `None`; a frozen `Prediction` dataclass (the five values); `is_consistent(p) -> bool` per R8 — **both directions** (D-TG-141, operator item 4 — approved); `quantise(confidence: float) -> Decimal` (three places, `ROUND_HALF_UP`); `route_prediction(p, *, floor: Decimal, threshold: Decimal, path: str) -> tuple[str, str | None]` per R1–R6 on the **quantised** confidence. Module docstring: the only definition of eligibility and routing (N7)
- [X] T019 [P] `apps/ai-api/tests/moderation/classification/test_eligibility.py` — pure: each of E1–E8 alone; precedence when several hold (text removed beats service beats media…); a bot account's message and another channel's message are eligible; `sender_chat_id == group_chat_id` → `group_itself`; `is_automatic_forward` → `linked_channel` (operator item 4); a bare «شكرا», «تمام» and an emoji-only text → `acknowledgement` via TG-M3's own matcher (FR-002…FR-004, SC-016)
- [X] T020 [P] `apps/ai-api/tests/moderation/classification/test_routing.py` — pure, over every combination of category × needs-moderation × severity at confidences `0.599`, `0.600`, `0.720`, `0.849`, `0.8495`, `0.850`, `1.000` with floor `0.60` / threshold `0.85`: R1 catch-up → `measurement_only` whatever the values; R2 below floor → `review`; R3 both inconsistency directions (chit-chat / question / complaint needing moderation; severity `none` needing moderation; spam or abuse **not** needing moderation) → `possible_violation`/`inconsistent`; R4 → `none`; R5 exactly at threshold and `0.8495` (quantises to `0.850`) → `incident`; R6 → `possible_violation`/`uncertain`. Thresholds passed in are what decide — the same prediction under `(0.60, 1.00)` routes to the list (FR-026…FR-031, SC-008, SC-009)

### Shared pieces

- [X] T021 [P] In `apps/ai-api/app/application/moderation/messages.py`: rename `_text_and_normalized` to public `extract_text(body) -> tuple[str | None, str | None]`, update its callers, behaviour byte-identical (D-TG-138)
- [X] T022 [P] In `apps/ai-api/app/application/moderation/incidents.py`: extract the insert into `insert_incident(session, *, telegram_chat_id, telegram_message_id, category, severity, source, opened_by_user_id: int | None, message_classification_id: int | None = None, prompted_by_classification_id: int | None = None) -> int | None` — the anchor's `sent_at` and `is_service` read, `detected_at` from one `SELECT now()`, `responsible_at(chat, detected_at)`, `ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING RETURNING id` — **on the caller's session, not committing**; `open_incident` becomes a thin wrapper that opens a session, calls it, commits and logs, with its signature unchanged except `opened_by_user_id: int | None`. Labels validated against `domain.incident`'s vocabularies as today. TG-M4's `tests/moderation/incidents/` suite must pass unchanged (D-TG-153)
- [X] T023 [P] Create `apps/ai-api/app/prompts/moderation/classify_v1.md` — **byte for byte** the text in `contracts/classification-pipeline.md` §2 (ending in a single newline); update `apps/ai-api/app/prompts/README.md` with one line: moderation prompts live under `moderation/`, versioned by filename, never edited in place
- [X] T024 [P] `apps/ai-api/tests/moderation/classification/test_prompt_pinned.py` — the SHA-256 of `classify_v1.md` equals a pinned constant; the failure message says to create `classify_v2.md` instead of editing (D-TG-136)
- [X] T025 [P] In `apps/ai-api/app/scripts/seed_profiles.py` `_ROSTER`: add `ollama-gemma4-e2b-moderation` — `ollama`, `http://host.docker.internal:11434/v1`, `gemma4:e2b-it-qat`, role `moderation`, params `{"num_ctx": 2048, "num_predict": 128, "temperature": 0, "reasoning_effort": "none"}`, `dim` NULL, **`is_active: False`** (D-TG-129)
- [X] T026 [P] Extend `apps/ai-api/tests/gateway/test_seed.py` — the moderation row is seeded **inactive** with exactly those params; re-running the seed inserts nothing and never activates it

### Panel — read-only models and one renderer

- [X] T027 [P] Create `apps/ai-control/app/Models/MessageClassification.php` and `apps/ai-control/app/Models/MessageClassificationAttempt.php` — `$timestamps = false`, casts (`confidence` as decimal:3, booleans), `modelProfile()` relation; `booted()` registers `updating` and `deleting` listeners that throw `LogicException` (D-TG-147). Header comment: Alembic owns the schema; routes and eligibility are **read**, never computed here
- [X] T028 [P] Create `apps/ai-control/app/Filament/Support/ModelView.php` — the one renderer for the model's view: `confidence(string|float $c): string` → three places + " self-reported confidence" (never `%`, never "probability"); `status(int $chatId, int $messageId): string` implementing `control-panel-classification.md` §5 by **reading** C5's precedence (current prediction → exclusion → latest failure → not yet), checking first whether any `moderation` profile is active; `exclusionLabel()` / `failureLabel()` maps from the stored reason codes to §5's words
- [X] T029 [P] `apps/ai-control/tests/Feature/ClassificationImmutabilityTest.php` — inserting a prediction and an attempt row succeeds; `update()` and `delete()` on either model throw and leave the row unchanged (FR-015)

**Checkpoint**: `make migrate` reaches `0007` and rolls back cleanly; every invariant in `data-model.md` is enforced
by the database; the gateway selects a model by role, disables reasoning where told, and returns its call id;
eligibility and routing exist, pure and exhaustively tested; nothing classifies yet.

---

## Phase 3: User Story 1 — An eligible message is classified, and the prediction is kept with its full provenance (Priority: P1) 🎯 MVP

**Goal**: Every newly derived message is sent — once — to the classifier on its own queue; excluded messages are
recorded with their reason; eligible ones get exactly one immutable prediction with its model, model call,
instruction version, vocabulary version, route and thresholds. The operator can smoke-test the real model.

**Independent Test**: With the model scripted and a controlled clock, derive messages of every kind and confirm
which reach the model, what each prediction records, and that re-interpretation yields no second prediction and
no second model call.

### Tests for User Story 1

- [X] T030 [P] [US1] `apps/ai-api/tests/moderation/classification/test_classify_one.py` — an eligible student message → exactly one `message_classifications` row with `model_profile_id` (the active moderation profile), `model_run_id` (the `model_runs` row the call wrote), `prompt_version = "classify_v1"`, `taxonomy_version = 1`, the scripted values, `path = "live"`, the stored route and both thresholds; each exclusion (service, moderator, media, no text, group itself, linked channel, acknowledgement, text removed) → one `excluded` row with that reason and **no** provider call; a bot account's and another channel's message → classified; after an edit, an answered question and an opened incident on the message, the prediction row is byte-identical (FR-001…FR-005, FR-011…FR-017, SC-006)
- [X] T031 [P] [US1] `apps/ai-api/tests/moderation/classification/test_structured_output.py` — scripted valid → prediction; `fail_with=ModelTruncatedError` → **no** prediction, one `failed` row `model_truncated`, and the provider called **once**; `fail_with=StructuredOutputInvalidError` → `structured_output_invalid`, called once; a scripted `confidence` of `1.3` and of `-0.1` → `confidence_out_of_range`, no prediction, never clamped; an inconsistent combination is stored verbatim. ⚠ **Finding 6**: a default gateway (`max_retries=2`) calls three times for a cut-off answer — only asserting the call count catches it (FR-012, FR-014, FR-023, SC-004)
- [X] T032 [P] [US1] `apps/ai-api/tests/moderation/classification/test_idempotency.py` — the same message classified three times → one prediction and **one** provider call; a claim already held for the message → the second `classify_one` ends without calling the provider and writes nothing; an excluded message classified twice → one exclusion row (FR-005, SC-007, pipeline I1–I4)
- [X] T033 [P] [US1] `apps/ai-api/tests/moderation/classification/test_enqueue.py` — with `classify_message.send` monkeypatched: a newly derived message sends once with `(chat pk, message_id, "live")` **after** the insert committed; a duplicate delivery sends nothing; a moderator's message is still sent (its exclusion must be recorded); `derive_message(..., schedule_classification=False)` sends nothing; `rederive_chat` over a window sends nothing (FR-001, D-TG-149)

### Implementation for User Story 1

- [X] T034 [US1] Create `apps/ai-api/app/application/moderation/classification.py` (part 1): `MessageClassificationResult` (pydantic, `Literal` category and severity, plain `float` confidence — pipeline §4); `load_facts(session, chat_pk, message_id) -> tuple[MessageFacts, text]` reading the `telegram_messages` row, its chat's platform `chat_id`, and the captured event at `source_update_id` — text via `messages.extract_text(body)` then `normalize`, `is_automatic_forward` from the body, `text_removed` when `text_purged_at` is set or the payload is purged (P1, D-TG-138); `build_model_input(text) -> list[Message]` → `[system = classify_v1.md, user = redact(text)]` with the redacted string named `redacted_text` (P2–P3, D-TG-140); `claim(redis, chat_pk, message_id, ttl_ms, prefix="ai:mod:classify:msg")` as an async context manager using `SET NX PX` with a random token and an owner-checked Lua delete (D-TG-150). Imports only from permitted prefixes; gateway types from `app.application.gateway` (T011)
- [X] T035 [US1] In the same file (part 2): `classify_one(session_factory, gateway, registry, redis, settings, *, chat_pk, message_id, path, attempt=1) -> str` — F1: `registry.resolve("moderation")`, on `NoActiveProfileError` return `"no_active_model"` recording nothing; take the claim or return `"claimed_elsewhere"`; I1: return if a current prediction or an exclusion exists; eligibility → on a reason, insert one `excluded` row `ON CONFLICT DO NOTHING` and return; build input; `gateway.generate_structured(StructuredRequest(messages=…, schema_model=MessageClassificationResult), role="moderation")`; O3 range check → `confidence_out_of_range` failure; O4 quantise; `route_prediction(...)` with the settings' thresholds (none on `catch_up`); insert the prediction `ON CONFLICT (telegram_chat_id, telegram_message_id) WHERE is_current DO NOTHING` with every O5 field and commit; on a non-transient `GatewayError` insert one `failed` row with `exc.category` and the profile id. Transient errors are **re-raised** to the caller (US3 adds the retry). Logs `message_id` / `chat_id` and, on failure, the category only — never `str(exc)`
- [X] T036 [US1] Create `apps/ai-api/app/workers/tasks/moderation/classify_message.py` — `@dramatiq.actor(queue_name="moderation_classify", max_retries=3)` `classify_message(chat_pk: int, message_id: int, path: str = "live", attempt: int = 1)`; per task: `load_settings()`, a session factory, a `redis.asyncio` client, a `ProfileRegistry`, and a `Gateway` with M1's lane (`Lane(redis, "llm", …)`), breaker and `AccountingWriter(capture_payloads=settings.gateway_capture_payloads)` wired from `Settings`, and **`max_retries=0`** (D-TG-134); runs `classify_one` under `asyncio.run`, as `process_update` does. Logs `message_id` only
- [X] T037 [US1] In `apps/ai-api/app/workers/main.py`: import the classify actor alongside the other moderation actors (noqa as they are)
- [X] T038 [US1] In `apps/ai-api/app/application/moderation/messages.py` `derive_message`: add `schedule_classification: bool = True`; after the insert commits, when `inserted_id is not None and schedule_classification`, `classify_message.send(chat_pk, body["message_id"], "live")` — for every new message, moderators' included (their exclusion is recorded by the classifier). Comment cites Q1–Q2 and D-TG-149
- [X] T039 [US1] In `apps/ai-api/app/scripts/rederive_chat.py`: pass `schedule_classification=False` to every `derive_message` call, with a comment: a re-derived message is history — a live-path prediction on it could open an incident dated today and charged to today's owner; history is classified only by `classify_chat` (D-TG-149)
- [X] T040 [P] [US1] Create `apps/ai-api/app/scripts/moderation_smoke_fixtures.jsonl` — research probe 4's twelve **synthetic** fixtures, one `{"text", "category", "needs_moderation"}` object per line, in un-normalised Arabic as a student would type. No real student text
- [X] T041 [US1] Create `apps/ai-api/app/scripts/smoke_moderation.py` — reads JSONL from stdin, or the shipped `moderation_smoke_fixtures.jsonl` when stdin is a TTY or empty; `--profile NAME` pins that profile via a `ProfileRegistry` subclass overriding `resolve`, active or not; otherwise uses the active `moderation` profile; a short reachability probe as `smoke_llm.py` does; for each fixture: `normalize` → `redact` → `build_model_input` → the real gateway with `role="moderation"`; prints expected vs predicted category and needs-moderation plus self-reported confidence and latency; exits non-zero on any mismatch. Writes nothing to the database (D-TG-161, pipeline C4)
- [X] T042 [US1] In the root `Makefile`: `smoke-moderation` target — when `FIXTURES` is set, `$(COMPOSE) --profile tools run --rm -T migrate python -m app.scripts.smoke_moderation $(ARGS) < "$(FIXTURES)"` (the file is streamed; it never enters the image or the repository); when unset, the same command with no redirection, so the script falls back to the shipped set; `## …` help text naming runbook §C's TG-M5 row (FR-063, SC-001)
- [X] T043 [P] [US1] `apps/ai-api/tests/moderation/classification/test_real_model.py` — `@pytest.mark.llm`: one real classification of a synthetic advert through the gateway against the local runtime returns a complete, in-range `MessageClassificationResult` with `finish_reason` stop; touches no database. Excluded from `make check` by `addopts`

**Checkpoint**: activate the moderation profile, post in the dev group — the message has one prediction with full
provenance; a moderator's message has an exclusion row; `make smoke-moderation` passes on the shipped fixtures.

---

## Phase 4: User Story 2 — What the model sees is the words, never the person (Priority: P2)

**Goal**: Prove, at the boundary, that only redacted first-posted words ever reach the model or any record the
model layer keeps, and that no log line carries text.

**Independent Test**: Classify fixtures full of phone numbers, emails, links and handles with the gateway's
debugging capture on; inspect the request the scripted provider received, the `model_runs` row, and the logs.

### Tests for User Story 2

- [X] T044 [P] [US2] `apps/ai-api/tests/moderation/classification/test_model_input.py` — using `scripted_gateway(capture_payloads=True)`: a message containing a phone number in Latin, Arabic-Indic and Eastern digits, an email, a link with and without a scheme, and a handle → the provider received exactly two messages, `system` equal to `classify_v1.md` and `user` containing the four placeholders and none of the originals, with Latin words mixed into Arabic intact; the sender's name, handle and id, the chat title and the timestamp appear nowhere in the request; `model_runs.request_payload` for the call contains only redacted text. ⚠ Redaction tested on a string passes while capture stores the original — only the real `AccountingWriter` proves it (FR-007, FR-008, SC-005)
- [X] T045 [P] [US2] `apps/ai-api/tests/moderation/classification/test_first_posted_text.py` — a message derived, then an `edited_message` applied through `apply_edit` (the stored text is now different), then classified → the provider received the **first-posted** words; the edited words appear nowhere. ⚠ **Finding 5**: a classifier reading `telegram_messages` passes every test that never edits (FR-006)
- [X] T046 [P] [US2] `apps/ai-api/tests/moderation/classification/test_classification_logs.py` — with `caplog` at DEBUG, classify an eligible message, an excluded one, and one whose scripted provider raises `StructuredOutputInvalidError`: no record's message or extras contain the original, normalised or redacted text or any scripted output value; records carry `message_id` in `extra` (FR-010, SC-020)

### Implementation for User Story 2

- [X] T047 [US2] Harden `apps/ai-api/app/application/moderation/classification.py` against T044–T046: the redacted string is bound only to `redacted_text` and never passed to a logger; failure logs use `exc.category`; no `repr` of the request or response anywhere; a docstring paragraph cites pipeline P5 and N6
- [X] T048 [P] [US2] Extend `apps/ai-api/tests/moderation/test_boundary_checks.py` — no module under the moderation directories imports `app.providers.llm`, `httpx`, `ollama` or `openai` (pipeline N10, Finding 3); `app/domain/moderation/classification.py` imports only the standard library and `app.domain.moderation`

**Checkpoint**: flip `GATEWAY_CAPTURE_PAYLOADS` on in a test and the only text the model layer ever stores is
redacted; nothing in any log line.

---

## Phase 5: User Story 3 — When the model is slow, broken or absent, nothing the team relies on changes (Priority: P3)

**Goal**: Transient failures are retried by the task with increasing delay; final failures are recorded; with no
active model nothing is recorded; the classifier's queue is isolated; TG-M3 and TG-M4 behave identically whatever
the model does.

**Independent Test**: Script the model unreachable, timing out, circuit-open, cut off; with and without an active
profile; compare every question item, incident and figure with the same traffic and no classification model.

### Tests for User Story 3

- [X] T049 [P] [US3] `apps/ai-api/tests/moderation/classification/test_task_retry.py` — with `classify_message.send_with_options` monkeypatched: `ProviderUnreachableError`, `ModelTimeoutError` and `CircuitOpenError` on attempt 1 → re-sent with `attempt=2` and `delay = 30 000 ms`, then 60 000, 120 000, 240 000; on the last attempt → one `failed` row with the category and no re-send; any other gateway error → one `failed` row on the first attempt, never re-sent (FR-023, FR-024, D-TG-151)
- [X] T050 [P] [US3] `apps/ai-api/tests/moderation/classification/test_no_active_profile.py` — no active `moderation` profile: classifying any message — eligible or not — writes **no** prediction, exclusion or failure row and calls no provider (FR-025, D-TG-152)
- [X] T051 [P] [US3] `apps/ai-api/tests/moderation/classification/test_attention_unaffected.py` — one seeded traffic set processed three ways — no moderation profile; a profile whose provider always raises `ProviderUnreachableError`; a working scripted profile — gives identical question items (opened, answered, times, attribution) and identical `first_response_time_stats`, `unanswered_stats`, `oldest_waiting` and `accuracy_by_rule_version`; operator incidents' `moderation_incident_state` rows identical (FR-022, FR-067, SC-003, SC-015)
- [X] T052 [P] [US3] `apps/ai-api/tests/moderation/classification/test_queue_isolation.py` — `classify_message.queue_name == "moderation_classify"`; every other actor under `app.workers.tasks.moderation` is on `"default"`; `infra/docker-compose.yml` (parsed with `yaml.safe_load`) runs `ai-worker` with `--queues default` and `ai-classifier` with `--queues moderation_classify`, `--processes 1`, `--threads 1`. ⚠ **Finding 4**: every functional test passes with one shared queue while a busy model stalls message processing — only the configuration shows it (FR-022)

### Implementation for User Story 3

- [X] T053 [US3] In `apps/ai-api/app/workers/tasks/moderation/classify_message.py`: catch the transient set `(ProviderUnreachableError, ModelTimeoutError, CircuitOpenError)` re-raised by `classify_one`; if `attempt < settings.moderation_classify_max_attempts`, `classify_message.send_with_options(args=(chat_pk, message_id, path, attempt + 1), delay=settings.moderation_classify_retry_base_s * 2 ** (attempt - 1) * 1000)`; otherwise record one `failed` row with the error's `category` through a small `record_failure(...)` in `classification.py`. Docstring cites F2–F5; `CircuitOpenError` is transient **for the task** although M1 marks it non-retryable within a call

**Checkpoint**: quit Ollama, post and answer a question in the dev group — the item is exactly TG-M3's; relaunch —
the message is classified once.

---

## Phase 6: User Story 4 — A confident violation opens an incident on its own (Priority: P4)

**Goal**: A live prediction routed `incident` opens a TG-M4 incident through `insert_incident`, in the same
transaction as the prediction; everything else about incidents is TG-M4's.

**Independent Test**: With a controlled clock and a scripted model, produce moderation predictions across the
confidence range and consistency combinations, on anchored and unanchored messages, with and without prior
enforcement and owners; confirm exactly which open an incident and what each records.

### Tests for User Story 4

- [X] T054 [P] [US4] `apps/ai-api/tests/moderation/classification/test_auto_open.py` — a confident, consistent live prediction → one incident: `source='ai'`, `opened_by_user_id` NULL, `message_classification_id` = the prediction, category and severity = the prediction's, `opened_at` = the message's `sent_at`, `detected_at` = the prediction's `created_at` transaction time, `responsible_moderator_id` = the owner at `detected_at` (NULL with no owner, unmoved by a later handover); an operator incident already on the message → no second incident, the operator's row byte-identical, the prediction stored with route `incident`; the sender banned before classification → the incident's `moderation_incident_state.status` is `resolved` and its enforcement is "acted before flagging" in TG-M4's figures (read, not computed); a catch-up prediction with the same values opens nothing; closing a model-opened incident as a false positive removes it from every handled / missed / timing figure (FR-034…FR-040, SC-002, SC-017)
- [X] T055 [P] [US4] `apps/ai-api/tests/moderation/classification/test_never_moves_state.py` — across every route and value combination, predictions on messages that anchor open, answered and expired question items and operator incidents in every state: no `attention_items` row changes, no `moderation_actions` row is written, no operator incident's derived state changes, and no attention item is ever created with `source='ai'` (FR-032, FR-033, SC-014)

### Implementation for User Story 4

- [X] T056 [US4] In `apps/ai-api/app/application/moderation/classification.py` `classify_one`: when the inserted prediction's route is `incident`, call `incidents.insert_incident(session, …, source="ai", opened_by_user_id=None, message_classification_id=<prediction id>, category=…, severity=…)` **before** the commit, in the same transaction (A1–A3, D-TG-153); log `incident opened` with `incident_id` and `message_id` only (A6). Nothing else — no alert, no evidence, no state (A4–A5)

**Checkpoint**: post an obvious advert from the disposable account — a model-opened incident appears on the
Incidents list; ✅ acknowledges it; restricting the sender resolves it.

---

## Phase 7: User Story 5 — An uncertain violation is listed for a person (Priority: P5)

**Goal**: The Possible Violations page lists live predictions routed `possible_violation` whose message anchors no
incident; its one action flags the message through TG-M4's form, recorded as list-prompted.

**Independent Test**: Seed predictions in every route, some anchored; load the page; flag from it; confirm
membership, the list-prompted record, and the absence of any other action.

### Tests for User Story 5

- [X] T057 [P] [US5] `apps/ai-control/tests/Feature/IncidentOpenPromptedByTest.php` — `openOn(..., promptedByClassificationId: $id)` writes `prompted_by_classification_id` and leaves `message_classification_id` NULL with `source='operator'`; the Incidents list action and the Live Attention Queue action write no prompted-by; a prompted-by naming another message's prediction is refused by the database (FR-043, FR-044)
- [X] T058 [P] [US5] `apps/ai-control/tests/Feature/PossibleViolationsPageTest.php` — rows are exactly C4's: `possible_violation` live predictions, unanchored; `review`, `none`, `incident` and `measurement_only` predictions never listed; an anchored one never listed; "Why listed" reads **Uncertain** / **Inconsistent** from `route_reason`; the **Flag message** action requires category and severity, opens an operator incident recorded as list-prompted, and the row disappears; no dismiss, relabel or bulk action exists; the empty state and the no-active-model state render §3 V4's words; Arabic text carries `dir="auto"` (FR-041…FR-045, SC-018)

### Implementation for User Story 5

- [X] T059 [US5] In `apps/ai-control/app/Models/ModerationIncident.php` `openOn`: add `?int $promptedByClassificationId = null` and write it; every existing caller passes nothing (D-TG-154)
- [X] T060 [US5] In `apps/ai-control/app/Filament/Resources/Incidents/Actions/OpenIncidentAction.php`: add `forPossibleViolationRow()` — the same category and severity selects, calling `openOn($record->message, $category, $severity, $user, promptedByClassificationId: $record->id)`; `forList()` and `forQueueRow()` unchanged
- [X] T061 [US5] Create `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php` with `possibleViolations(?int $chatId, Carbon $from, Carbon $to)` — `classification-metrics.md` C4 **verbatim** as a bound query, with a header comment that the file quotes the contract and defines nothing (D-TG-156)
- [X] T062 [US5] Create `apps/ai-control/app/Filament/Pages/PossibleViolations.php` — a `Page implements HasTable` in navigation group **Moderation Intelligence** after Incidents, following `LiveAttentionQueue.php`: columns per `control-panel-classification.md` §3 (Group, Message `dir="auto"` / "Text removed", Posted in the operator's timezone, Model's view via `ModelView::confidence`, Why listed, Model · instruction version), default sort newest posting first, group and posting-period filters, the one row action from T060, the empty and no-model states (V4). **No bulk action**

**Checkpoint**: a scripted 0.72 advert appears on Possible Violations; flagging it opens an operator incident marked
"flagged from the possible-violations list", and the row is gone.

---

## Phase 8: User Story 6 — The model is measured against the humans' labels (Priority: P6)

**Goal**: C1–C8 exactly as the contract states, in Python and PHP; the Classification Accuracy page; detection
latency by opener; the catch-up command that classifies labelled history for measurement only.

**Independent Test**: Load research probe 10's scenario and compare every figure with the hand-computed values;
run the catch-up twice.

### Tests for User Story 6

- [X] T063 [P] [US6] `apps/ai-api/tests/moderation/classification/test_metrics.py` — research probe 10's fourteen-message, two-model scenario built through `conftest.py`: C1 rule-kept 1/1, rule-dismissed 0/1, operator-added 1/1 for model A; C2 unverified 1 per model, **two rows**; C3 independent 2 → agreed 1 → same category 1, list-prompted 1 → 1 → 1, false-positive closures 2 → model raised 1, model-opened 1 → false positive 1; C4 exactly one entry; C5 14 = 11 + 1 + 1 + 1; C6 the burst's needs-response message wins over its greeting anchor; C7 two rows with operator additions in the NULL-version row; C8 ai 4 s, operator median 120 s / p90 168 s. Recomputing after changing both thresholds in `Settings` gives identical figures (FR-046…FR-051, SC-009, SC-012, SC-017)
- [X] T064 [P] [US6] `apps/ai-api/tests/moderation/classification/test_catch_up.py` — over a measured chat's history: every prediction has `path='catch_up'`, route `measurement_only`, no thresholds; a message whose scripted prediction is a confident violation opens **no** incident and is **not** in C4; a second run classifies nothing and makes no provider call; the printed report's counts equal the rows written; an unmeasured chat is refused; transient failures are recorded, not re-scheduled (FR-061, FR-062, SC-011)
- [X] T065 [P] [US6] `apps/ai-control/tests/Feature/ClassificationAccuracyPageTest.php` — the same scenario rendered: every figure as numerator / denominator matching T063; one block per model, never pooled; list-prompted shown apart; a zero denominator reads "no labelled examples"; the estimate heading present; no `%`, no "average", no " avg", no combined score (FR-046…FR-049, SC-012, SC-013)
- [X] T066 [P] [US6] Extend `apps/ai-control/tests/Feature/IncidentMetricsTest.php` — detection latency renders one row per opener (Operator, Model) with its own count and p90 suppression; every other incident figure unchanged and inclusive of model-opened incidents (FR-037, FR-067)

### Implementation for User Story 6

- [X] T067 [US6] In `apps/ai-api/app/application/moderation/metrics.py`: add `classification_question_stats`, `classification_unverified_stats`, `classification_violation_stats`, `possible_violations`, `classification_volume_stats` (with the by-reason breakdowns of M15) and `classification_labels_for_items` — each quoting its C1–C6 statement **verbatim** from `contracts/classification-metrics.md`, with `:chat_id` NULL meaning every measured group; and change `detection_latency_stats` to C8 (grouped by `source`), returning one block per opener. A module comment names the contract as the single definition (D-TG-156, D-TG-159)
- [X] T068 [US6] Extend `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php` with C1, C2, C3, C5 (+ breakdowns), C6 and C7 — each verbatim, bound parameters, no arithmetic beyond reading the returned counts
- [X] T069 [US6] In `apps/ai-control/app/Filament/Resources/Incidents/Concerns/IncidentMetrics.php` `detectionLatencyStats`: replace the statement with C8 and return one block per opener; update the incidents figures view under `apps/ai-control/resources/views/filament/resources/incidents/` to render the two rows ("Operator", "Model"). Nothing else in the concern changes
- [X] T070 [US6] Create `apps/ai-control/app/Filament/Pages/ClassificationAccuracy.php` and `apps/ai-control/resources/views/filament/pages/classification-accuracy.blade.php` — navigation group **Moderation Intelligence**; period and group filters; the estimate heading; sections Rule set baseline (C7 read per M19), Questions (C1, C2), Violations (C3, C4 count), What happened to every message (C5) — one block per `(model, instruction version, vocabulary version)`, every figure rendered as `n / d` with its label, "no labelled examples" for `d = 0`. No control changes anything (`control-panel-classification.md` §4)
- [X] T071 [US6] Create `apps/ai-api/app/scripts/classify_chat.py` — `--chat <platform chat id> [--since] [--until]`; refuses an unmeasured chat as `rederive_chat` does; walks the chat's messages in `sent_at` order that have neither a current prediction nor an exclusion; calls the **same** `classify_one(..., path="catch_up")` with a gateway wired like the actor's (`max_retries=0`); records transient failures as `failed` rather than re-scheduling; prints `classified=<n> excluded=<reason:n,…> failed=<kind:n,…>`. Module docstring: composition root; predictions are measurement only; history is never classified any other way (D-TG-160, pipeline C1–C3)

**Checkpoint**: seed the probe 10 scenario and the Classification Accuracy page matches the hand-computed values;
the catch-up classifies a week of dev history and opens nothing.

---

## Phase 9: User Story 7 — Why a label was given is visible where the work is done (Priority: P7)

**Goal**: The model's view on the Live Attention Queue and the incident screens; the `moderation` role in the
roster.

**Independent Test**: Seed messages with and without predictions (each status) and incidents of every origin; load
the queue, list and detail; switch the active classification model and the active generator.

### Tests for User Story 7

- [X] T072 [P] [US7] `apps/ai-control/tests/Feature/ModelViewDisplayTest.php` — the queue row shows C6's category and "self-reported confidence" and the row's order, age and actions are unchanged; a message with no prediction shows each §5 status (excluded with each reason's words, failed with its kind, not classified yet, no active classification model); the incidents list's **Opened by** column and filter; the incident detail's "why flagged" for an independent operator flag (operator-assigned labels + the model's view), a list-prompted flag ("Flagged from the possible-violations list") and a model-opened incident (the opening prediction with model, instruction and vocabulary version); TG-M4's "No model classification — arrives with TG-M5" line is gone; nowhere is a confidence followed by `%` or described as a probability, chance or likelihood (FR-052…FR-056, W1–W2)
- [X] T073 [P] [US7] `apps/ai-control/tests/Feature/ModelProfileRoleTest.php` — the form and filter offer `moderation`; activating a second moderation profile deactivates the first and leaves the active `llm` profile unchanged; activating a different `llm` profile leaves the moderation profile unchanged; deactivating the only moderation profile is refused by the existing guard (FR-058, SC-010)

### Implementation for User Story 7

- [X] T074 [US7] In `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`: add **one** column, "Model's view", from `ClassificationMetrics` C6 for the page's item ids (one query per page, not per row), falling back to `ModelView::status` of the anchor; change nothing else (Q1–Q2)
- [X] T075 [US7] In `apps/ai-control/app/Filament/Resources/Incidents/Tables/IncidentsTable.php`: add the **Opened by** column ("Operator" / "Model" from `source`) and a matching `SelectFilter` (L1–L2)
- [X] T076 [US7] In `apps/ai-control/app/Filament/Resources/Incidents/Schemas/IncidentInfolist.php`: replace the "No model classification — arrives with TG-M5" entry with the "why flagged" answers of `control-panel-classification.md` §2.3 — operator-assigned labels plus `ModelView`'s view of the message; "Flagged from the possible-violations list" with the listing prediction when `prompted_by_classification_id` is set; for `source='ai'`, "Opened by the model" and the opening prediction's fields, labels marked "the model's". Every other entry unchanged (D1–D2)
- [X] T077 [US7] In `apps/ai-control/app/Filament/Resources/ModelProfiles/Schemas/ModelProfileForm.php` and `Tables/ModelProfilesTable.php`: add `moderation` to the role options and filter; extend the params helper text with the classification keys `num_ctx`, `num_predict`, `temperature`, `reasoning_effort` (R1)

**Checkpoint**: the queue and every incident page say what the model thinks — and say it is the model's
self-report; the roster offers the classification role.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T078 [P] Extend `apps/ai-control/tests/Feature/IncidentWordingTest.php` and the no-average assertions in `IncidentMetricsTest.php` to render **Possible Violations** and **Classification Accuracy** as well: the incident pages keep the standing sentence and no other `delet` / `remov` substring apart from the retention marker; neither new page contains "average", " avg" or a combined score (W3–W4, SC-013)
- [X] T079 [P] Run `scripts/check.sh` check 4 against every new and edited moderation module and confirm no logging line references `original_text`, `normalized_text`, `redacted_text`, `message_text` or `caption`; confirm the classifier and the actor log only whitelisted extras (`message_id`, `chat_id`, `incident_id`) (FR-010, SC-020)
- [X] T080 Add three additive correction notes to `docs/plan/telegram/telegram-moderation-intelligence.md`, in the same form as the existing "**Correction (TG-M4, research Finding 3).**" paragraphs: under §15.3 — "**Correction (TG-M5, research Finding 1).**" the seed also sets `reasoning_effort: "none"` (the installed model reasons first and every 128-token answer was cut off), and it is seeded **inactive**; under §15.6 — "**Correction (TG-M5, clarification 1 and Finding 2).**" 0.60–0.85 opens no incident and is listed as a possible violation; inconsistent predictions are listed too; the model's self-reported confidence is not a safety signal and the pilot false-positive rate of model-opened incidents is the operational gate (operator item 3); under §25 TG-M5 — the pre-filter classifies bot and already-answered messages, excludes the group's linked channel, and the model opens no question item (clarification 2). Change no other text
- [X] T081 Add one line to `specs/007-tg-m4-policy-incidents/contracts/incident-metrics.md` §4: "From TG-M5 this statement is grouped by `source` — see `specs/008-tg-m5-ai-classification/contracts/classification-metrics.md` C8." Change nothing else
- [X] T082 Update `docs/runbooks/tg-operator-prerequisites.md` §C's TG-M5 row only where it has drifted from `quickstart.md` §2–§5: fixtures in a file **outside the repository**; `FIXTURES=<path> make smoke-moderation ARGS="--profile ollama-gemma4-e2b-moderation"` **before** activating the profile; then activate it in the roster. SC-001 is the operator's own run (quickstart §4), not an automated task
- [X] T083 Run `make check` (`scripts/check.sh`) from the repository root with **Ollama quit and no `TELEGRAM_BOT_TOKEN` set** and confirm it passes offline (FR-070, SC-019)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
   └─▶ Phase 2 (Foundational)  ── BLOCKING ──┐
                                             ▼
                                      Phase 3 — US1 🎯  (classify_one, the actor, enqueue)
                                             │
        ┌──────────────────┬─────────────────┼──────────────────┬───────────────────┐
        ▼                  ▼                 ▼                  ▼                   ▼
   Phase 4 — US2      Phase 5 — US3     Phase 6 — US4     Phase 7 — US5        Phase 9 — US7
   (privacy proofs)   (retry, isolation) (auto-open)       (panel; Python-free) (panel)
                                             │                  │
                                             └────────┬─────────┘
                                                      ▼
                                               Phase 8 — US6  (figures, catch-up)
                                                      │
                                                      └──▶ Phase 10 (Polish)
```

### User Story Dependencies

- **US1** depends only on Phase 2. It is the MVP.
- **US2** depends on US1 (it proves US1's boundary) and edits `classification.py` only to harden it.
- **US3** depends on US1 (it adds the retry to US1's actor).
- **US4** depends on US1 (one addition to `classify_one`).
- **US5** is panel-only; its tests seed predictions directly, so it needs Phase 2 (T027–T028) and nothing from
  US1–US4.
- **US6**'s arithmetic (T063, T067) needs Phase 2 only — its fixture writes predictions and incidents directly;
  its catch-up (T064, T071) needs US1; its page (T065, T068, T070) extends US5's concern.
- **US7** is panel-only and needs Phase 2's `ModelView` and US5's concern (for C6).

### Within Each Story

Tests first, then the pure function, then the application layer, then the actor or script, then the panel.

### Shared files — run in the order listed

- `app/application/moderation/classification.py`: T034 → T035 → T047 → T056 (and `record_failure` in T053).
- `app/workers/tasks/moderation/classify_message.py`: T036 → T053.
- `app/application/moderation/metrics.py`: T067 only.
- `app/Filament/Pages/Concerns/ClassificationMetrics.php`: T061 → T068.
- `app/Models/ModerationIncident.php`: T059 only. `OpenIncidentAction.php`: T060 only.

### Parallel Opportunities

- **Phase 1**: T001–T005 are all `[P]`.
- **Phase 2**: T006–T008 `[P]`; T009 → T010 → T011 in order (same package); T012 after T011. T013 → T014, then
  T015–T016 `[P]`. T017–T029 are `[P]` except T018 before T019–T020.
- **Every story's test block is fully parallel** — separate files, fixtures only in `conftest.py`.
- **After US1**: US2, US3 and US4 touch `classification.py` in turn (see shared files) but their **tests** run in
  parallel; US5, US7 and US6's arithmetic are independent of all three.
- **Phase 10**: T078–T079 `[P]`; T080–T083 last and sequential.

## Parallel Example: Foundational

```
T006 domain/model_profile.py        T007 providers/llm/base.py        T008 providers/llm/openai_compatible.py
T017 domain/moderation/attention.py T021 messages.py extract_text     T022 incidents.py insert_incident
T023 prompts/moderation/classify_v1.md                                T025 seed_profiles.py
T027 MessageClassification(.php, Attempt.php)                         T028 ModelView.php
      — ten files, no shared edits; then T009 → T010 → T011 → T012, and T013 → T014 → T015/T016
```

## Parallel Example: after US1

```
  Agent A → US2 tests (T044–T046) + US3 tests (T049–T052) + US4 tests (T054–T055), then T047 → T053 → T056 in order
  Agent B → US5 (T057–T062)  — panel only
  Agent C → US6 arithmetic (T063, T067) — metrics.py only, fixture writes rows directly
  Agent D → US7 (T072–T077) — panel only, after B's T061

  ⚠ A owns classification.py and classify_message.py. B and D share only ClassificationMetrics.php (B first).
     C touches metrics.py only.
```

## Implementation Strategy

### MVP first (US1 only)

Phases 1–3 deliver a real slice: every new message in a measured group is either classified — once, from its
first-posted redacted words, with its model, call, instruction, vocabulary, route and thresholds — or recorded as
excluded with its reason; the operator can smoke-test the real model before switching it on. Nothing opens and
nothing is shown yet, but the record the rest of the milestone reads is correct and immutable. **Stop here and the
milestone is still worth having.**

### Incremental delivery

1. **Phases 1–3** → classification runs. Demo: runbook §C's smoke test; a message's prediction in `make psql`.
2. **+ Phase 4** → privacy proven at the boundary, including with payload capture on.
3. **+ Phase 5** → the model can be down for a day and TG-M3 does not notice.
4. **+ Phase 6** → confident adverts open incidents on their own. Demo: quickstart §6.1.
5. **+ Phase 7** → uncertain ones wait for a person on Possible Violations.
6. **+ Phase 8** → the comparison: the model against your labels, beside the rule set — and the pilot
   false-positive rate that is the operational gate (plan item 3).
7. **+ Phase 9** → the model's view where the work is done; the classification role in the roster.
8. **+ Phase 10** → wording, logs, the plan's corrections, the runbook, offline `make check`.

### Suggested MVP scope

**Phases 1, 2 and 3** — 43 tasks. The checkpoint is real: activate the seeded profile, post a question and an
advert in the dev group, and see one prediction each with `model_run_id`, `classify_v1`, taxonomy 1 and its route —
and one exclusion row for your own moderator reply.

## Notes

- **Tests are required here**, per Principle I and `plan.md`'s enumeration. Six of them — **T012, T016, T031,
  T044, T045, T052** — exist because a finding or probe proved the obvious test passes while the code is broken.
  Those are the ones not to skip when time runs short.
- **Tests never compute an expected route or eligibility** — they call the pure function or read the stored row.
  An expectation computed by test code is a second definition and will drift with it (pipeline N7). Incident state
  is still read from TG-M4's view, never computed.
- **Every prediction in a test is scripted.** M1's fake cannot synthesise `Literal` fields (probe 7); an unscripted
  fake raises outside the gateway's taxonomy.
- **Operator steps, not tasks:** add the four keys to `.env` if other than default (quickstart §2); write the
  fixtures file outside the repository; run the smoke test, then activate the profile (quickstart §4–§5); read the
  model-opened false-positive figure after a week of pilot traffic — **the operational gate** (plan item 3).
- **No Git action appears in any task** (Principle IV). The branch exists; committing, merging and tagging are the
  operator's.
- **Recorded, not fixed, and deliberately without a task:** the assessment profile's reasoning cost, M1's fake and
  `Literal`, TG-M3's accuracy query's NULL-version row, and the baseline gate in this database (`plan.md`,
  "Recorded, not fixed") — Principle V.
- **Nothing here reads or writes `injazedu/`** (Principle III), and no test touches a database whose name lacks
  `_test` (Principle II). The one real-model test touches no database at all.
