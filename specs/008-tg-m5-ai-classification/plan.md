# Implementation Plan: TG-M5 — AI Classification

**Branch**: `m5/ai-classification` *(operator-created; Principle IV)* | **Date**: 2026-09-27
**Spec**: [`spec.md`](./spec.md) · **Research**: [`research.md`](./research.md) ·
**Data model**: [`data-model.md`](./data-model.md) ·
**Contracts**: [`classification-pipeline.md`](./contracts/classification-pipeline.md) ·
[`classification-metrics.md`](./contracts/classification-metrics.md) ·
[`control-panel-classification.md`](./contracts/control-panel-classification.md) ·
**Quickstart**: [`quickstart.md`](./quickstart.md)
**Milestone**: TG-M5 of `docs/plan/telegram/telegram-moderation-intelligence.md` §25

## Summary

Every new text message from a student in a measured group is classified by the local model — category,
needs-an-answer, needs-moderation, severity and self-reported confidence — from its first-posted, redacted words
and nothing else. The prediction is recorded once, immutable, with its model, instruction version, vocabulary
version, model call, and the route the system took under the thresholds in force. A confident, coherent
violation opens a TG-M4 incident through TG-M4's own insert, in the same transaction; an uncertain or
self-contradicting one is listed for an operator; everything below the floor waits for TG-M8's review. The model
opens no question and closes nothing. A comparison page measures the model against the human labels TG-M3 and
TG-M4 already hold, beside the rule set's own baseline.

Six measured facts shaped the design (`research.md` §0): the installed model **reasons before answering**, and at
the plan's 128-token budget every answer was cut off — `reasoning_effort: "none"` fixes it and makes each call
~1 s and deterministic; its **confidence barely moves** (0.90–1.00 on everything), so the band between floor and
threshold will be nearly empty and the model's false-positive count is the real control; moderation code **cannot
import the gateway's request types** under TG-M0's boundary; a classification waiting for the model's one-at-a-time
lane would **hold a worker thread** that message processing needs; an **edit overwrites** the stored words; and
M1's gateway **retries cut-off answers** and **returns no reference** to the call it recorded. Two probes created
revision `0007` exactly as written and ran every figure statement verbatim against a hand-computed scenario.

## Technical Context

**Language/Version**: Python 3.12 (`apps/ai-api`), PHP 8.3 / Laravel 12.69.1 (`apps/ai-control`)
**Primary Dependencies**: SQLAlchemy 2 Core (async), Alembic, Dramatiq 2.2.1 + Redis broker, pydantic 2, M1's
model gateway, Filament v5.7.8. **No new dependency on either side.**
**Model runtime**: Ollama 0.34.4, `gemma4:e2b-it-qat` (already installed), OpenAI-compatible endpoint, strict JSON
schema, `temperature 0`, `reasoning_effort "none"`, `num_predict 128`, `num_ctx 2048`
**Storage**: PostgreSQL 16.15 — revision `0007_moderation_classification`, down-revision `0006` (head in both
databases): 2 tables, 1 widened check, 1 column + 4 constraints on `moderation_incidents`, 1 FK on
`attention_items`
**Testing**: pytest against `injaz_ai_test` via `TEST_DATABASE_URL`, with the model scripted through M1's
`FakeLLMProvider`; one `@pytest.mark.llm` test against the real runtime, excluded by default. PHPUnit with
`DatabaseTransactions` against the same database. No credential, no network, no model runtime in `make check`
**Target Platform**: the existing local Docker stack **plus one service**, `ai-classifier` (same image, one process,
one thread, queue `moderation_classify`)
**Project Type**: two applications in one repository — Python service plus PHP control panel
**Performance Goals**: ~1 s per classification warm (probe 4: 0.6–1.4 s), one at a time machine-wide via M1's lane;
a busy pilot group (hundreds of messages a day) is minutes of model time. Detection latency is a reported figure,
not a target
**Constraints**: no outbound message, no alert, no bot action; no message text in any log line or either new table;
redaction before the gateway; the model never touches a question item or an incident's lifecycle; the panel makes
no model call and computes no route, eligibility or status
**Scale/Scope**: ~5 moderators, a handful of groups, 7 categories × 2 flags × 4 severities. The human-label set the
comparison rests on is small — every ratio shows its denominator

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 below.*

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested** — every row protects a contract, an AI-pipeline boundary, a business rule, an idempotency guarantee
or metric arithmetic:

| Area | Test | Why it earns one |
|---|---|---|
| Eligibility | E1–E8 in order; bot account and other channel eligible; linked channel and group-itself excluded; the stoplist is TG-M3's | FR-002…FR-004, pure, exhaustive |
| Routing | R1–R9 over every consistency combination (both directions), the floor and threshold exactly, the catch-up path, quantisation at the boundary (0.8495 → 0.850 opens at 0.85) | FR-026…FR-031, **the milestone's accusation guard** |
| Prompt pinned | SHA-256 of `classify_v1.md` | D-TG-136 — an edited instruction silently rewrites every past prediction's meaning |
| Model input | the gateway receives exactly `system` + redacted `user`; no identity, group or time; with capture on, `model_runs.request_payload` holds only redacted text | FR-007, FR-008, SC-005 — privacy, greppable |
| First-posted words | an edit applied before classification → the model sees the original words | FR-006, **Finding 5** |
| Structured output | scripted valid; cut off; malformed; confidence 1.3 / −0.1 → no prediction, one `failed` row with the kind, no retry | FR-012, FR-023, SC-004 — the gateway boundary |
| Task retry | transient → re-sent with `attempt + 1` and the doubling delay; exhausted → one `failed` row; `circuit_open` treated as transient | FR-023, FR-024 |
| No active model | nothing classified, **nothing recorded** | FR-025 |
| Idempotency | same message ×3 → one prediction, one model call; a held claim → the second task ends; exclusion recorded once | FR-005, SC-007 |
| Automatic opening | route `incident` → one AI incident with the prediction, labels, both moments, owner at detection; no owner → NULL; operator first → no second incident; sender already banned → opens resolved, "acted before flagging" (read from TG-M4's view) | FR-034…FR-039, SC-002 |
| Never moves state | every prediction combination × open question items and operator incidents → no item change, no evidence row, no state change | FR-032, FR-033, SC-014 |
| TG-M3 unaffected | question figures identical with and without a classification model, including with the model failing | FR-067, SC-003, SC-015 |
| Enqueue | new message → one send after commit; duplicate → none; `rederive_chat` → none | FR-001, D-TG-149 |
| Catch-up | measurement only, no incident, not listed, second run does nothing, counts reported, unmeasured chat refused | FR-061, FR-062, SC-011 |
| Metric arithmetic | research probe 10's scenario: C1–C8 exactly, never pooled, list-prompted apart, the partition, C6's choice | FR-046…FR-051, SC-012 |
| DB invariants | probe 9's twelve planted violations | the composite links, one current prediction, route shape |
| Gateway extensions | `role="moderation"` resolves the moderation profile, default unchanged; `reasoning_effort` forwarded only when in params; digests of existing profiles byte-identical; `model_run_id` returned; existing gateway suite unchanged | FR-019, D-TG-130…D-TG-133 — **M1's contract** |
| Config | blank → default; out of range and floor > threshold refused | FR-026 |
| Migration `0007` | up and down | data-transforming migration |
| Real model (`@pytest.mark.llm`) | one real classification through the gateway returns a complete prediction | the only proof against the runtime; excluded from `make check` |
| Panel — possible violations | C4 membership; the flag action records list-prompted and removes the row; no other action | FR-041…FR-045 |
| Panel — accuracy page | C1–C8 rendered with denominators, never pooled, no average, no percentage | FR-046…FR-051 |
| Panel — model's view | queue column; incident "why flagged" for all three kinds; every no-prediction status; W1's words | FR-052…FR-056 |
| Panel — immutability | `MessageClassification` / `MessageClassificationAttempt` update and delete throw | FR-015 |
| Panel — roster | `moderation` role; one active; activation leaves `llm` alone | FR-058, SC-010 |
| Panel — wording and averages | TG-M4's wording and no-average tests extended to the new pages | W3, W4 |
| Silence | unchanged TG-M1/TG-M4 tests still pass | FR-064, FR-065 |

**Exempt under Principle I**: Filament page, table and action wiring; Eloquent casting; Dramatiq delivery
semantics; Redis `SET NX PX` semantics; the Compose service definition; JSON serialisation; the model's *quality*
beyond the operator's smoke fixtures (quality is what the accuracy page measures, not what a test asserts).

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

Yes. Python tests reach Postgres only through `TEST_DATABASE_URL`; `tests/conftest.py`'s session guard is untouched.
The model is scripted — no test reaches a model runtime except the one `@pytest.mark.llm` test, which touches no
database. PHP feature tests use `DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase`,
`DatabaseMigrations` or `migrate:fresh`. Research probes against the development database were **read-only counts**;
every schema probe ran as `ai_migrator` inside `BEGIN … ROLLBACK` in `injaz_ai_test` and left it at `0006`. Model
probes used synthetic text only.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.**

### 4. Are there Git actions in the task list? (Principle IV)

**No.** The branch `m5/ai-classification` exists and was created by the operator; the agent created none. The
`before_specify`, `before_plan` and `after_plan` hooks are surfaced and left to the operator.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

Yes — see **Requirement → Design Traceability**. Four design choices touch merged milestones or read the approved
text in a particular way and were escalated rather than taken quietly (**⚠ Four Items for the Operator** — all
approved 2026-09-27); four
observations are recorded and deliberately **not** acted on. Deliberately not built: the model opening, dismissing
or closing questions; human verdicts, reprocessing, alerts, dashboards; any bot action, deletion inference, average
or composite.

## Project Structure

### Documentation (this feature)

```text
specs/008-tg-m5-ai-classification/
├── spec.md                                   # FR-001…FR-070, SC-001…SC-021, 2 clarifications
├── plan.md                                   # this file
├── research.md                               # 6 findings, 10 probes, D-TG-129…D-TG-161
├── data-model.md                             # revision 0007: 2 tables, the incident links, the roster role
├── quickstart.md                             # smoke test first, switch on, live check, figures, 12 limitations
├── contracts/
│   ├── classification-pipeline.md            # THE contract: enqueue, prompt, eligibility, input, routing, opening, failure, never
│   ├── classification-metrics.md             # the exact SQL behind every classification figure (C1–C8)
│   └── control-panel-classification.md       # the model's view, possible violations, accuracy page, words
├── checklists/requirements.md                # all items passing
└── tasks.md                                  # NOT created here — /speckit-tasks
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── domain/
│   │   ├── model_profile.py                      # EDIT — Role + 'moderation'; GenerationRole ⚠1
│   │   └── moderation/
│   │       ├── classification.py                 # NEW — PURE: eligibility (E1–E8), consistency (R8),
│   │       │                                     #       route_prediction (R1–R6), quantise. No I/O, no clock
│   │       └── attention.py                      # EDIT — _matches_ack_stoplist → public is_acknowledgement
│   ├── application/
│   │   ├── gateway/
│   │   │   ├── __init__.py                       # EDIT — exports request/response vocabulary + errors ⚠1
│   │   │   ├── gateway.py                        # EDIT — role=; model_run_id on responses; reasoning in digest ⚠1
│   │   │   └── accounting.py                     # EDIT — record() returns the inserted id ⚠1
│   │   └── moderation/
│   │       ├── classification.py                 # NEW — classify_one(): claim → check → eligibility → first-posted
│   │       │                                     #       text → redact → call → validate → route → one transaction
│   │       ├── incidents.py                      # EDIT — insert_incident(session, …) extracted; ai source accepted
│   │       ├── messages.py                       # EDIT — extract_text public; schedule_classification=True
│   │       └── metrics.py                        # EDIT — C1–C8 of classification-metrics.md, quoted
│   ├── providers/llm/
│   │   ├── base.py                               # EDIT — model_run_id: int | None = None on responses ⚠1
│   │   └── openai_compatible.py                  # EDIT — forward params["reasoning_effort"] when present ⚠1
│   ├── workers/
│   │   ├── main.py                               # EDIT — import the classify actor
│   │   └── tasks/moderation/classify_message.py  # NEW — actor on queue moderation_classify; wires the gateway
│   │                                             #       (max_retries=0); task-level transient retry
│   ├── prompts/moderation/classify_v1.md         # NEW — contract §2, byte for byte
│   ├── scripts/
│   │   ├── classify_chat.py                      # NEW — the catch-up; measurement only
│   │   ├── smoke_moderation.py                   # NEW — JSONL on stdin; --profile pins an inactive profile
│   │   ├── moderation_smoke_fixtures.jsonl       # NEW — synthetic only
│   │   ├── seed_profiles.py                      # EDIT — ollama-gemma4-e2b-moderation, inactive
│   │   └── rederive_chat.py                      # EDIT — schedule_classification=False
│   └── infrastructure/
│       ├── config.py                             # EDIT — 4 settings, validated, blank-safe
│       └── models_moderation.py                  # EDIT — 2 tables; prompted_by column
├── alembic/versions/0007_moderation_classification.py   # NEW — up and down
└── tests/
    ├── gateway/test_role_and_extensions.py       # NEW — role, reasoning forwarding, digests, model_run_id
    └── moderation/classification/                # NEW test package
        ├── conftest.py                           # scripted-gateway factory; reuses TG-M4 message/incident builders
        ├── test_eligibility.py   test_routing.py   test_prompt_pinned.py              # pure
        ├── test_model_input.py   test_first_posted_text.py   test_structured_output.py
        ├── test_task_retry.py    test_no_active_profile.py   test_idempotency.py
        ├── test_auto_open.py     test_never_moves_state.py   test_attention_unaffected.py
        ├── test_enqueue.py       test_catch_up.py            test_metrics.py
        ├── test_db_invariants.py test_config_classification.py test_migration_0007.py
        └── test_real_model.py                    # @pytest.mark.llm — excluded from make check

apps/ai-control/
├── app/Models/
│   ├── MessageClassification.php             # NEW — read-only; update/delete throw
│   ├── MessageClassificationAttempt.php      # NEW — read-only; update/delete throw
│   └── ModerationIncident.php                # EDIT — openOn(…, ?int $promptedByClassificationId = null)
├── app/Filament/
│   ├── Pages/PossibleViolations.php          # NEW — read-only table, one row action
│   ├── Pages/ClassificationAccuracy.php      # NEW — the figures, per model group
│   ├── Pages/Concerns/ClassificationMetrics.php  # NEW — C1–C8, quoted once
│   ├── Support/ModelView.php                 # NEW — the model's view / no-prediction status, one renderer
│   ├── Pages/LiveAttentionQueue.php          # EDIT — one column
│   └── Resources/
│       ├── Incidents/Tables/IncidentsTable.php          # EDIT — Opened-by column + filter
│       ├── Incidents/Schemas/IncidentInfolist.php       # EDIT — "why flagged"
│       ├── Incidents/Actions/OpenIncidentAction.php     # EDIT — forPossibleViolationRow()
│       ├── Incidents/Concerns/IncidentMetrics.php       # EDIT — C8 by source
│       └── ModelProfiles/{Schemas/ModelProfileForm,Tables/ModelProfilesTable}.php  # EDIT — role option
├── resources/views/filament/pages/classification-accuracy.blade.php   # NEW
└── tests/Feature/
    ├── PossibleViolationsPageTest.php    ClassificationAccuracyPageTest.php
    ├── ModelViewDisplayTest.php          ClassificationImmutabilityTest.php
    ├── ModelProfileRoleTest.php          IncidentOpenPromptedByTest.php
    └── IncidentWordingTest.php / IncidentMetricsTest.php   # EDIT — new pages; C8 by source

infra/docker-compose.yml       # EDIT — new ai-classifier service; ai-worker --queues default ⚠2
Makefile                       # EDIT — smoke-moderation (FIXTURES on stdin)
.env.example                   # EDIT — 4 keys
CLAUDE.md / AGENTS.md          # EDIT — active-feature pointer (identical files)
specs/007-…/contracts/incident-metrics.md  # EDIT — one pointer line: §4 is grouped by source from TG-M5 (C8)
```

**Structure Decision.** No new top-level tree. Four placements are load-bearing:

- **Eligibility and routing are pure, in `app/domain/moderation/classification.py`.** They decide what reaches
  the model and what may accuse someone; both are exhaustively testable without a database or a model, and both
  have exactly one definition (pipeline contract N7). The panel reads their stored outputs and never recomputes
  them.
- **The prediction and the incident it opens are one transaction through TG-M4's own insert.**
  `insert_incident` is the single Python opening path; the classifier and `open_incident` both call it, so a
  model-opened incident is an incident in every respect TG-M4 defined.
- **Classification has its own consumer.** A separate queue and a one-thread service are what make FR-022
  structural rather than hoped for (Finding 4).
- **The gateway is extended, not bypassed.** Every model call goes through M1's lane, breaker, accounting and
  structured-output check; the four extensions are additive and leave every existing caller byte-identical.

## ⚠ Four Items for the Operator

**All four approved by the operator on 2026-09-27.** Each either touches a merged milestone or reads the approved
spec in a specific way; each is now in scope for `tasks.md`.

### 1. ✅ Approved — Extend M1's gateway in four additive ways.

| Change | Why | Files |
|---|---|---|
| `role=` keyword on `generate_text` / `generate_structured`; `Role` gains `moderation` | the plan's own D-TG-14 — select the classification model independently of the generator | `domain/model_profile.py`, `gateway.py` |
| forward `reasoning_effort` from a profile's params when present | **Finding 1** — without it every classification is cut off | `providers/llm/openai_compatible.py`, `gateway.py` (digest) |
| export `Message`, `StructuredRequest`, `StructuredResponse` and the error classes from `app.application.gateway` | **Finding 3** — moderation cannot otherwise build a request without breaking TG-M0's boundary | `application/gateway/__init__.py` |
| `AccountingWriter.record` returns the row id; responses carry `model_run_id` (default `None`) | **Finding 6** — FR-013's reference from each prediction to its model call | `accounting.py`, `providers/llm/base.py`, `gateway.py` |

No existing caller changes; profiles without `reasoning_effort` send and digest exactly what they do today; the
gateway suite runs unchanged. *Alternatives:* widen TG-M0's boundary allowlist instead of the export (touches a
guardrail rather than a facade); drop the model-call reference and amend FR-013 (weaker provenance). Recommended:
approve all four.

### 2. ✅ Approved — Add an `ai-classifier` service and restrict `ai-worker` to the `default` queue.

**Finding 4**: in the shared worker, a classification waiting for the model's lane holds a thread, and eight
waiting classifications stop message processing — against FR-022. The new service runs the same image with
`--queues moderation_classify --processes 1 --threads 1` and its own `mem_limit`; `ai-worker` gains
`--queues default`, which still consumes its delayed messages (probe 6). **This changes Compose.** *Alternative:*
keep one worker and accept that a busy model delays question tracking — a spec change to FR-022. Recommended:
approve.

### 3. ✅ Decided — Keep the approved thresholds; the pilot false-positive rate, not confidence, is the operational gate.

**Finding 2**: this model reported 0.90–1.00 on every message, including those it got wrong. At the defaults
(0.60 / 0.85) nearly every coherent violation it sees opens an incident; the possible-violations list will mostly
hold self-contradicting predictions; confidence cannot be the safeguard. The spec's other safeguards remain —
consistency routing, your false-positive closure, and the model's false-positive count (C3), which the quickstart
tells you to read after a week.

*Options:* **(a)** keep the approved defaults — no change (recommended); **(b)** start with
`MODERATION_INCIDENT_CONFIDENCE=1.0`, so only the model's maximum self-report opens incidents and the rest go to the
list, then lower it on evidence — a setting, no spec change; **(c)** amend the spec to add an explicit "list only"
mode.

**Decision (2026-09-27).** Implement with the approved defaults, 0.60 / 0.85. Model-reported confidence is **not**
treated as a reliable safety signal anywhere — not in the design, the screens or the quickstart. The **operational
gate** is the real pilot false-positive rate, above all the model-opened incidents later closed as *not a
violation* (`classification-metrics.md` C3, M9). No spec change; quickstart §8 states the gate.

### 4. ✅ Approved — Two interpretations that only ever make the model accuse less.

- **Consistency is judged both ways** (D-TG-141). FR-027 defines inconsistency only for predictions that *need*
  moderation. Probe 4 produced the reverse — an advert with needs-moderation false — which the literal text would
  route as "nothing to do", silently. Judged both ways, it is listed as a possible violation, marked inconsistent.
- **The group's linked channel is the group's own voice** (D-TG-139). FR-002 excludes messages "sent on behalf of
  the group itself"; this reads it to include automatic forwards from the group's linked channel — the
  organisation's own announcements, including promotions of its own courses, which the model would call adverts.
  Every other channel's message stays eligible (FR-003).

Recommended: approve both. *Alternative:* the literal text — the reverse contradiction goes unlisted, and your own
channel's promotions can open incidents.

### Recorded, not fixed

- **The assessment `llm` profile pays the same reasoning cost** (Finding 1) — the same model, a 1,024-token budget
  spent partly on hidden reasoning. M1/assessment work; this milestone sets `reasoning_effort` only on the new
  profile.
- **M1's fake cannot synthesise a `Literal` field** (probe 7) — an unscripted fake raises a pydantic error outside
  the gateway's taxonomy. Classification tests script every prediction; the fake is unchanged.
- **TG-M3's accuracy query puts operator additions in their own row** (probe 10) — correct per its own definition;
  the comparison page reads both rows. The query is unchanged.
- **The baseline gate is not met in this database** (probe 8) — development traffic only. The comparison becomes
  meaningful after a week of pilot traffic; nothing in the build depends on it.

## Complexity Tracking

No Constitution violations. Four choices cost more than the obvious alternative, and each buys a specific
requirement:

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| A dedicated one-thread `ai-classifier` service | FR-022, structurally | The shared worker stalls whenever the lane is busy (Finding 4); Dramatiq cannot cap threads per queue |
| `message_classification_attempts` for exclusions and failures | FR-004, FR-024, FR-051, FR-055 — every message accounted for | Exclusions cannot be derived in SQL: the acknowledgement stoplist is Python, and a second copy in SQL would be a second definition |
| Composite links `(prediction, chat, message)` | An incident can never cite a prediction about another message | A plain FK on the prediction id allows exactly that mistake (probe 9 E2, E3) |
| A per-message Redis claim | SC-007's "one successful model call" when the catch-up overlaps the live service | The unique index alone prevents a second prediction but not a second, wasted call |

## Post-Design Constitution Re-Check

Re-run after Phase 1. **All five still pass.**

1. **Principle I.** The test table was written from the finished design. Six tests exist *because* of a finding or
   probe (`test_first_posted_text`, `test_model_input`'s capture check, `test_role_and_extensions`'s reasoning and
   digest checks, `test_structured_output`'s no-retry, `test_db_invariants`, `test_metrics`). Routing and
   eligibility are tested as pure functions, not re-derived in a test helper (pipeline N7). The exemption list
   gained only the Compose definition and model quality.
2. **Principle II.** Unchanged. No test reaches a model runtime or a non-`_test` database; the one real-model test
   touches no database.
3. **Principle III.** Still nothing inside `injazedu/`.
4. **Principle IV.** No Git action entered the design.
5. **Principle V.** Four items escalated, four observations recorded and left alone. Nothing added beyond the spec:
   no alert, no dashboard, no review queue, no reprocessing, no question opened by the model.

## Requirement → Design Traceability

| FR | Where it is satisfied |
|---|---|
| FR-001…FR-006 | `derive_message` enqueue (Q1–Q2); `domain/…/classification.py` eligibility (E1–E9); first-posted re-extraction (P1); the claim and `uq_classification_current` (I1–I3); D-TG-137…D-TG-139, D-TG-149, D-TG-150 |
| FR-007…FR-010 | pipeline §2, §4; `classify_v1.md` pinned; redaction before the gateway; check 4 unchanged; D-TG-136, D-TG-140 |
| FR-011…FR-017 | `MessageClassificationResult`; O3–O6; `message_classifications` and its checks; route + thresholds stored; D-TG-135, D-TG-141, D-TG-142, D-TG-147 |
| FR-018…FR-025 | `moderation` role and seed; gateway `role=`, `max_retries=0`; own queue and service; F1–F6; D-TG-129…D-TG-134, D-TG-148, D-TG-151, D-TG-152 |
| FR-026…FR-033 | `route_prediction` R1–R13; `Settings` validation; D-TG-141…D-TG-143 |
| FR-034…FR-040 | `insert_incident` in one transaction (A1–A6); `ck_incident_ai_link`, `fk_incident_classification`; C8; D-TG-145, D-TG-153, D-TG-159 |
| FR-041…FR-045 | Possible Violations page; C4; `openOn(…, promptedBy)`; `ck_incident_prompted_by`, `fk_incident_prompted_by`; D-TG-154, D-TG-155 |
| FR-046…FR-051 | `classification-metrics.md` C1–C7, quoted by `metrics.py` and `ClassificationMetrics.php`; D-TG-146, D-TG-156 |
| FR-052…FR-060 | `control-panel-classification.md` §1–§5; `ModelView.php`; roster role; D-TG-155…D-TG-158 |
| FR-061…FR-063 | `classify_chat.py` (C1–C3); `smoke_moderation.py` and `make smoke-moderation` (C4); D-TG-160, D-TG-161 |
| FR-064…FR-066 | silence tests unchanged; check 1–4 unchanged; gateway exports (Finding 3); no outbound path added |
| FR-067 | `test_attention_unaffected.py`; TG-M3/TG-M4 suites unchanged; C8 the only figure change |
| FR-068…FR-070 | predictions follow their messages (anchored per chat, like items and incidents); no text stored; offline `make check` |

| SC | Verified by |
|---|---|
| SC-001 | the operator's smoke run, quickstart §4 |
| SC-002 | quickstart §6.1 + `test_auto_open.py` |
| SC-003 | quickstart §6.3 + `test_attention_unaffected.py`, `test_task_retry.py` |
| SC-004 | `test_structured_output.py` |
| SC-005 | `test_model_input.py` |
| SC-006 | `test_db_invariants.py` (shape) + `test_auto_open.py` / `test_idempotency.py` (every live prediction written through one function) |
| SC-007 | `test_idempotency.py` |
| SC-008 | `test_routing.py` |
| SC-009 | `test_routing.py` (stored thresholds) + `test_metrics.py` (recomputed after a threshold change → identical) |
| SC-010 | `ModelProfileRoleTest.php` |
| SC-011 | `test_catch_up.py` |
| SC-012 | `test_metrics.py`, `ClassificationAccuracyPageTest.php` |
| SC-013 | extended no-average test, `ClassificationAccuracyPageTest.php` |
| SC-014 | `test_never_moves_state.py` |
| SC-015 | `test_attention_unaffected.py`, `IncidentMetricsTest.php` |
| SC-016 | `test_eligibility.py` |
| SC-017 | `test_metrics.py` (model-opened false positive) |
| SC-018 | `PossibleViolationsPageTest.php`, `IncidentOpenPromptedByTest.php` |
| SC-019, SC-020 | offline `make check`; the existing check 4 |
| SC-021 | TG-M1/TG-M4 silence tests + quickstart §6.4 |

## Phase Status

| Phase | Status | Output |
|---|---|---|
| Phase 0 — Research | ✅ complete | `research.md` — 6 findings, 10 probes, D-TG-129…D-TG-161, settings, traceability |
| Phase 1 — Design & Contracts | ✅ complete | `data-model.md`, 3 contracts, `quickstart.md`, agent context updated |
| Constitution Check | ✅ passed, re-checked post-design | 4 items escalated and **approved** (2026-09-27), 4 observations recorded, 0 violations |
| Phase 2 — Tasks | ✅ complete | `tasks.md` — 83 tasks, 10 phases, FR-001…FR-070 and SC-001…SC-021 covered |
| Phase 3 — Implementation | ⏳ not started | `/speckit-implement` |
