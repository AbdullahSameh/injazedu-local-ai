# Phase 0 Research: TG-M5 — AI Classification

**Feature**: `specs/008-tg-m5-ai-classification`
**Date**: 2026-09-27
**Inputs**: `spec.md` (FR-001…FR-070, SC-001…SC-021, 2 clarifications) ·
`docs/plan/telegram/telegram-moderation-intelligence.md` (§7, §9, §10.10, §14.1, §15, §18.7, §19, §20.2,
§22, §25 TG-M5, §27) · `docs/runbooks/tg-operator-prerequisites.md` (§A.1, §C TG-M5) ·
`.specify/memory/constitution.md` · the merged M1 gateway and TG-M0…TG-M4 code · the running local model
runtime (Ollama 0.34.4, `gemma4:e2b-it-qat`)

Decision ids continue the domain's log at **D-TG-129** (TG-M4 ended at D-TG-128).

---

## §0 — Six findings

Each was produced by a probe against the running model runtime, the test database, the merged code or
the library source. Two change what the model is asked to do; two change how the merged gateway and
worker must be extended; one changes where the model's input comes from; one changes what the
confidence thresholds can be expected to achieve.

Two later findings, from the end-to-end manual test (2026-10-01), are in §6: the instruction's policy gap
(Finding 7), and the context size the runtime actually uses (Finding 8).

### ⚠ Finding 1 — The installed model reasons before it answers, and at the plan's 128-token budget every answer is cut off.

Probe 1 sent twelve synthetic Arabic messages through the exact request shape
`OpenAICompatibleLLMProvider.generate_structured` builds — strict JSON schema, `temperature: 0`,
`max_tokens: 128`, as §15.3's seed prescribes:

```
12 / 12   finish_reason = "length"   completion_tokens = 128   content = ""   → ModelTruncatedError
```

Probe 2 inspected one raw response with a 600-token budget: the message carries a `reasoning` field of
2,296 characters, and the JSON answer begins only after it — still truncated at 600. `gemma4:e2b-it-qat`
under this runtime is a thinking model; its reasoning is spent from the same output budget.

Probe 3 tried four ways to turn it off through the same OpenAI-compatible endpoint:

| Request field | Result |
|---|---|
| `reasoning_effort: "none"` | **stop**, 51 tokens, no reasoning, valid JSON |
| `reasoning: {effort: "none"}` | stop, 51 tokens, valid |
| `think: false` | ignored — length, 522 chars of reasoning |
| `reasoning_effort: "low"` | length, 522 chars of reasoning |

With `reasoning_effort: "none"` (probe 4, 12 fixtures × 3 rounds): every call `finish_reason = stop`,
38–54 completion tokens, ~375–420 prompt tokens, **0.6–1.4 s**, identical output on every repeat,
**12 / 12** on category and needs-moderation.

The merged provider forwards only `max_tokens`, `temperature` and (for Ollama) `options.num_ctx`
(`app/providers/llm/openai_compatible.py:_bound_params`). **Resolution (D-TG-130).** The provider forwards a
`reasoning_effort` value from the profile's `params` when one is present; the moderation seed sets it to
`"none"`. Profiles without it send exactly what they send today. **This edits an M1 module** (plan, ⚠ Item 1).
Recorded, not fixed: the assessment `llm` profile uses the same model with a 1,024-token budget and pays
the same reasoning cost — an M1/assessment concern outside this milestone.

### ⚠ Finding 2 — The model's self-reported confidence barely moves. The band between the floor and the incident threshold will be almost empty.

Across all 70 answered calls — 12 clear fixtures and 12 deliberately ambiguous messages (a student selling a used book,
"contact me privately", a harsh complaint, a group-invite with a handle) — confidence was **0.90, 0.95 or
1.00, never lower**. The ambiguous cases were not less confident; some were simply wrong with 0.95
("selling my used book" → spam, 0.95; "anyone know a better channel?" → chit-chat, 0.95).

Consequences, stated so nobody discovers them in the pilot:

- At the defaults (floor 0.60, threshold 0.85), almost every consistent moderation prediction opens an
  incident, and almost nothing is routed as *uncertain*. The possible-violations list will be populated
  mostly by **inconsistent** predictions (Finding 2's probe produced one: an advert with needs-moderation
  false).
- Confidence cannot be what keeps a false accusation out of the figures with this model. What does is the
  spec's own design: consistency routing, the operator's false-positive closure, and — the figure that
  matters — the model's false-positive count on the incidents it opened (FR-046), read after a week.

**Resolution.** No design change is needed to honour the spec as approved; the thresholds stay data,
the quickstart tells the operator what to read and which lever exists, and the limitation is written down.
Whether to begin with automatic opening effectively off is the operator's call (plan, ⚠ Item 3). **Decided
2026-09-27:** implement with 0.60 / 0.85; confidence is not treated as a safety signal; the operational gate is the
real pilot false-positive rate of model-opened incidents (C3, M9).

### ⚠ Finding 3 — Moderation code cannot build a gateway request without breaking its own import boundary.

`Gateway.generate_structured` takes a `StructuredRequest[T]` built from `Message` objects — both defined in
`app/providers/llm/base.py`. TG-M0's forward allowlist (`scripts/check.sh` check 1) permits moderation
modules exactly seven prefixes; `app.application.gateway` is one, `app.providers.llm` is not. A classifier
in `app/application/moderation/` that imports the request types fails `make check` (probe 5: a planted
file in a scratch copy of the tree, run through check 1's exact `grep` pipeline — the
`app.providers.llm.base` import is reported as a violation; the same names imported from
`app.application.gateway` pass).

Two ways out: widen TG-M0's allowlist by one prefix, or have the gateway package — the facade its own
docstring calls "the single entry point later milestones import from" — export its request and response
vocabulary. **Resolution (D-TG-132).** The second: `app/application/gateway/__init__.py` re-exports
`Message`, `StructuredRequest`, `StructuredResponse` and `GatewayError`. No guardrail changes; the
boundary check stays exactly as TG-M0 wrote it. **This edits an M1 module** (plan, ⚠ Item 1).

### ⚠ Finding 4 — A classification waiting for the model would hold a worker thread that message processing needs.

Every actor in the domain runs on Dramatiq's `default` queue in one worker service —
`--processes ${WORKER_PROCESSES} --threads ${WORKER_THREADS}`, eight threads today. The gateway's `llm`
lane admits **one** generation machine-wide; a caller waits for it up to `GATEWAY_CALL_TIMEOUT_S` (180 s),
holding its thread. A burst of eight messages, or any future assessment generation holding the lane for a
minute, would park every thread in a classification wait — and `process_update`, `evaluate_attention` and
`match_response` would stop running. FR-022 forbids exactly that.

Dramatiq cannot cap threads per queue: a worker's threads serve every queue it consumes. Probe 6 read
Dramatiq 2.2.1's `Worker._add_consumer`: `--queues` whitelists by canonical name, so a worker started with
`--queues default` still consumes `default.DQ` — the delayed messages `evaluate_attention` relies on.

**Resolution (D-TG-148).** Classification runs on its own queue, `moderation_classify`, consumed by a
dedicated single-process, single-thread service; the existing worker is restricted to `default`. One thread
matches the lane's own concurrency of one, so the classifier never waits on itself. **This changes Compose:
one new service and one changed command line** (plan, ⚠ Item 2).

### ⚠ Finding 5 — An edit overwrites the stored words, so "the words as first posted" are not in `telegram_messages`.

`messages.apply_edit` updates `original_text` and `normalized_text` in place
(`app/application/moderation/messages.py:315-355`). A message edited before its classification runs — or any
message the catch-up command reaches after an edit — would be classified on the edited words, against
FR-006. A spammer posting something harmless and editing it into an advert is the classic case, in reverse.

The first-posted words are still captured: every message row carries `source_update_id`, pointing at the
append-only `message` event that created it, whose payload is immutable until retention.
**Resolution (D-TG-138).** The classifier re-extracts the text from that event through the same extraction
and the same `normalize` the message derivation uses, then redacts it. Nothing is copied, and the edited
words never reach the model.

### ⚠ Finding 6 — The gateway retries a cut-off or malformed answer on its own, and returns no reference to the call it recorded.

Two properties of M1's gateway meet FR-023 and FR-013 head-on:

- M1's taxonomy marks `ModelTruncatedError` and `StructuredOutputInvalidError` **retryable**
  (`app/application/gateway/errors.py`), so a default gateway makes up to three attempts at an answer that,
  at `temperature: 0`, is identical every time (probe 4). FR-023 says such output is not retried.
- `AccountingWriter.record` inserts the `model_runs` row and returns nothing; no response object carries its
  id. FR-013 requires a reference from each prediction to the call it came from.

**Resolution (D-TG-134, D-TG-133).** The classifier constructs its gateway with `max_retries=0` — an existing
constructor argument, no M1 change — and retries only transient failures itself, at the task level, with
increasing delay (D-TG-151). For the call reference, `AccountingWriter.record` returns the inserted id and
the gateway attaches it to the response as an optional `model_run_id`; existing callers ignore it. **The
second half edits M1** (plan, ⚠ Item 1). A recording failure is still swallowed (M1's FR-040), in which case
the prediction's reference is empty — honestly, because there is no record to point to.

---

## §1 — Probes

Ten probes. Ollama 0.34.4 with `gemma4:e2b-it-qat` (the only generation model installed — `qwen3:8b` and
`gemma3:4b` are in the roster but **not pulled**), Postgres 16.15, Dramatiq 2.2.1. Model probes used
**synthetic text only**, already in normalised form, with placeholders where a redactor would put them.
Development-database probes were **read-only** and selected counts only. Every schema probe ran inside
`BEGIN … ROLLBACK` in `injaz_ai_test`, as `ai_migrator` for DDL (Principle II); `to_regclass` confirmed
nothing survived and `alembic_version` stayed `0006`.

| # | Question | Result |
|---|---|---|
| 1 | Does the plan's seed (128 tokens, temperature 0, strict schema) produce answers? | **No.** 12/12 `finish_reason = length`, empty content → **Finding 1** |
| 2 | Why? | A `reasoning` field of 2,296 characters precedes the JSON; still truncated at 600 tokens |
| 3 | Can reasoning be disabled through the endpoint the gateway uses? | `reasoning_effort: "none"` and `reasoning: {effort: "none"}` — yes; `think: false` and `"low"` — no → **Finding 1** |
| 4 | With reasoning off: validity, latency, determinism, agreement, budget? | 12/12 valid, `stop`, 38–54 completion tokens, 0.6–1.4 s, identical across 3 rounds, **12/12** category + needs-moderation. A 3,516-character message: 1,178 prompt tokens, 2.6 s, valid — Telegram's 4,096-character maximum fits `num_ctx 2048`. Confidence only 0.90/0.95/1.00 → **Finding 2**. First prompt draft said adverts need a response; one added sentence fixed it (§2 D-TG-136) |
| 5 | Can a moderation module import the gateway's request types? | **No** — a planted `from app.providers.llm.base import …` in a scratch copy is reported by check 1's exact pipeline; `from app.application.gateway import …` is not → **Finding 3** |
| 6 | Does `--queues default` keep a worker consuming its delayed messages? | **Yes** — `Worker._add_consumer` whitelists by `q_name()`, the canonical name, so `default.DQ` is included → **Finding 4** |
| 7 | Can M1's fake provider synthesise the classification schema unscripted? | **No.** `synthesize_model` returns `None` for a `Literal` field and pydantic rejects it — a `ValidationError`, outside the gateway's taxonomy. Every classification test scripts its prediction (D-TG-135). M1's fake is not changed |
| 8 | Is the baseline the plan gates this milestone on available? | **Not yet, in this database.** Development traffic only: 35 messages over 6 days; 8 rule-opened items (1 dismissed), 3 operator-added, 2 incidents (1 false positive). The plan's gate — the rule set's precision read over real pilot traffic — is an operator dependency (spec Dependencies), not a build blocker |
| 9 | Does `data-model.md`'s revision `0007`, exactly as written, enforce what it claims? | **Yes.** Created as `ai_migrator`. Twelve planted violations each rejected by the named constraint: an AI incident without a prediction (`ck_incident_ai_link`); a flag prompted by another message's prediction (`fk_incident_prompted_by`); an AI incident linked to another message's prediction (`fk_incident_classification`); an AI incident with a prompted-by (`ck_incident_prompted_by`); a second current prediction (`uq_classification_current`); confidence 1.3; a possible violation without a reason; a catch-up prediction routed to an incident; a second active moderation profile (M1's `uq_model_profiles_one_active_per_role`, unchanged); a duplicate exclusion; a failure naming no model; a floor above the threshold. `ai_control` reads both new tables and `ai_app` inserts into them with **no `GRANT`** — TG-M4's probe 6 default ACL holds |
| 10 | Does `contracts/classification-metrics.md`'s SQL, exactly as written, produce the hand-computed figures? | **Yes**, over a 14-message scenario with two models. Question side: rule-kept 1/1, rule-dismissed 0/1, operator-added 1/1; unverified 1 per model, **never pooled**. Violation side: independent flags 2 → agreed 1 → same category 1; list-prompted 1 → 1 → 1; false-positive closures 2 → model would have raised 1; model-opened 1 → false positive 1. Possible-violations list: exactly the one unanchored entry. Volume: 14 = 11 classified + 1 excluded + 1 failed + 1 not yet. Queue label: the burst's needs-response message wins over the greeting that anchors it. Detection latency by source: ai 4 s; operator median 120 s. TG-M3's §5 accuracy query, run verbatim, returns operator additions in their **own** row (`rule_version` NULL) — the comparison reads both rows (D-TG-156) |

**Not probed, deliberately**: Filament page, table and action wiring; Eloquent casting; Dramatiq delivery
semantics; Redis `SET NX PX` semantics. All are framework or library behaviour, exempt under Principle I.

---

## §2 — Decisions

### The model call

**D-TG-129 — A `moderation` role, seeded inactive as `ollama-gemma4-e2b-moderation`; activating it is the
switch.** FR-018, FR-025. Same model as the generator (`gemma4:e2b-it-qat`, already installed — runbook
§A.1), `params = {num_ctx: 2048, num_predict: 128, temperature: 0, reasoning_effort: "none"}` (probe 4).
Seeded **inactive** by `make seed-profiles`: seeding is idempotent and may be re-run for unrelated reasons,
so it must not switch classification on by itself; activation in the roster is the deliberate act, after
the smoke test has run against the inactive profile (D-TG-161). No second moderation profile is seeded —
the only larger model in the roster is not installed (probe 1's inventory). *Alternative rejected:* seeding
it active — the next `make seed-profiles` on a fresh database would start classifying without anyone
having run the smoke test.

**D-TG-130 — Reasoning is disabled per profile, through `params.reasoning_effort`, forwarded by the provider
when present.** Finding 1. `_bound_params` adds `payload["reasoning_effort"]` only if the profile's params
carry the key; the gateway's `_generation_params` adds it to the canonical request likewise, so a profile's
digest reflects it and existing profiles' digests are byte-identical. *Alternatives rejected:* a larger
budget — reasoning still ran to 2,296 characters and cost seconds per message; `think: false` — ignored by
this endpoint (probe 3); a custom Ollama modelfile — a second artefact outside the roster to keep in sync.

**D-TG-131 — `Gateway.generate_text` and `generate_structured` gain `role: GenerationRole = "llm"`, where
`GenerationRole = Literal["llm", "moderation"]`.** FR-018, FR-019, D-TG-14. The role selects the profile;
the provider factory and the **`llm` lane** stay as they are — a classification is still a generation
(§15.3). `embed` is untouched. The domain's `Role` widens to include `moderation`; `GenerationRole` is its
generation subset, so asking `generate_*` for the embedding role is a type error, not a runtime surprise.

**D-TG-132 — The gateway package exports its request vocabulary.** Finding 3. `Message`, `StructuredRequest`,
`StructuredResponse`, `Gateway`, `GatewayError` and the error classes the classifier branches on are
importable from `app.application.gateway`. The provider module keeps defining them.

**D-TG-133 — `AccountingWriter.record` returns the inserted `model_runs.id`; responses carry
`model_run_id: int | None = None`.** Finding 6, FR-013. `NullAccountingWriter` returns `None`; a swallowed
recording failure returns `None`. The field has a default, so every existing construction and every
existing caller is unchanged.

**D-TG-134 — The classification gateway is constructed with `max_retries=0`.** Finding 6, FR-023. One gateway
call is one attempt. Transient failures are retried by the task with increasing delay (D-TG-151);
cut-off, malformed and out-of-range answers are recorded as failures and never retried automatically. The
breaker still counts every retryable failure, as M1 designed.

**D-TG-135 — The output model is `MessageClassificationResult` with `Literal` fields and a plain `float`
confidence; the range is checked in application code.** §15.2, FR-011, FR-012. Probe 4: Ollama's
constrained decoding honours the `Literal` enums (no invalid category or severity in 70 calls); a numeric
`minimum`/`maximum` in the schema would move an out-of-range confidence into the gateway's
`StructuredOutputInvalidError`, losing FR-024's failure kind. So the schema has no bounds, and the
classifier rejects `confidence < 0 or > 1` as `confidence_out_of_range` — never clamped. An accepted
confidence is quantised to three places, half-up, **before** routing, and that exact value is stored
(`numeric(4,3)`), so a routing decision is reproducible by hand from the stored row. Tests script every
prediction explicitly (probe 7).

**D-TG-136 — The instruction is `app/prompts/moderation/classify_v1.md`; its version is its filename stem;
its content is pinned by a test.** FR-009, §15.5. The version string `classify_v1` is stored on every
prediction; a test pins the file's SHA-256, so editing the words without renaming the file — which would
silently change what `classify_v1` means on every past prediction — fails `make check`. The text is in
`contracts/classification-pipeline.md` §2 (probe 4's final draft, including the one sentence that stopped
adverts being marked as needing a response). The vocabulary is `taxonomy_version = 1` (D-TG-08).

### Eligibility and input

**D-TG-137 — Eligibility is a pure function in `app/domain/moderation/classification.py`.** FR-002…FR-004.
Reasons, evaluated in this order, first match wins: `text_removed`, `service`, `media`, `no_text`,
`moderator`, `group_itself`, `linked_channel`, `acknowledgement`. The acknowledgement test is TG-M3's own
stoplist matcher, made public as `is_acknowledgement(text)` in `app/domain/moderation/attention.py` (a rename
of `_matches_ack_stoplist`, whose one caller moves with it) — one stoplist, so the rules and the model agree on
what was never a question. Captions are `media` (§4 defers them).

**D-TG-138 — The model's input is re-extracted from the message's own captured event.** Finding 5, FR-006.
`telegram_updates.payload` for the row's `source_update_id`, through `messages.extract_text` (the existing
`_text_and_normalized`, made public) and `normalize`, then `redact`. When the payload has been purged the
message is `text_removed`.

**D-TG-139 — An automatic forward from the group's linked channel is excluded as the group's own voice.**
FR-002's "sent on behalf of the group itself", read to include the channel whose posts the platform forwards
into its discussion group automatically (`is_automatic_forward`). Those are the organisation's own
announcements — including promotions of its own courses, which the model would call adverts. Any other
channel's message stays eligible (FR-003). **An interpretation of the spec, escalated** (plan, ⚠ Item 4).

**D-TG-140 — The model receives two messages: the instruction as `system`, the redacted text as `user`.
Nothing else.** FR-007, FR-008. No sender, handle, identifier, group, title, course, time, entity flags or
neighbouring message. Redaction happens in `classification.py` before the gateway is called, so
`GATEWAY_CAPTURE_PAYLOADS` can only ever capture redacted text (§15.5).

### Routing

**D-TG-141 — Consistency is judged in both directions.** FR-027, FR-014. A prediction is consistent when
*needs moderation* goes with a violation category (`SPAM_OR_AD`, `ABUSE`, `OTHER`) and a severity other than
`none`, **or** *needs no moderation* goes with a category other than `SPAM_OR_AD` and `ABUSE`. Probe 4
produced the second kind of contradiction — an advert, needs-moderation false — which FR-027's one-directional
wording would route as "no moderation needed", silently. Judged both ways, it is listed as a possible
violation, marked inconsistent (FR-031). **An interpretation of the spec that only ever lists more, escalated**
(plan, ⚠ Item 4).

**D-TG-142 — Routing is a pure function of the prediction, the two thresholds and the path; its output is
stored once.** FR-017, FR-026…FR-031. In order: catch-up path → `measurement_only`; confidence below the
floor → `review`; inconsistent → `possible_violation` (`inconsistent`); needs no moderation → `none`;
confidence at or above the threshold → `incident`; otherwise → `possible_violation` (`uncertain`). Stored with
the thresholds in force and the path, so a later change to either threshold revisits nothing (SC-009). "The
message was already flagged" is **not** stored: it is the observable fact that the anchor's incident is not
linked to this prediction — deriving it avoids a prediction row that a race could make untrue. Single writer
(the classifier), single definition (the pure function); the database constrains only the shape.

**D-TG-143 — `MODERATION_CONFIDENCE_FLOOR` (0.60) and `MODERATION_INCIDENT_CONFIDENCE` (0.85): validated
`0 ≤ floor ≤ threshold ≤ 1`, blank means default.** FR-026. A `mode="before"` validator maps `""` to the
default, as `TELEGRAM_BOT_TOKEN` already does; Compose passes both as `${KEY:-default}` (TG-M4's Finding 2
pattern). Read by the classifier only — the panel shows the thresholds stored on each prediction.

### Storage

**D-TG-144 — Revision `0007_moderation_classification`: two tables, one widened check, four constraints and a
column on `moderation_incidents`, one foreign key on `attention_items`.** `data-model.md`. Down-revision
`0006` (probe 9's starting point). No `GRANT` (probe 9). No view: nothing here is derived from later evidence.

**D-TG-145 — Links to a prediction are composite: `(classification id, chat, message)`.** FR-035, FR-044.
`message_classifications` carries `UNIQUE (id, telegram_chat_id, telegram_message_id)`, and both incident links
reference it, so an incident can never cite a prediction about a different message (probe 9 E2, E3). A
model-opened incident must cite one (`ck_incident_ai_link`); only an operator flag may carry a prompted-by
(`ck_incident_prompted_by`). TG-M4's `ck_incident_operator_labels` is unchanged: an operator's incident never
carries the *opening* link, even when a prediction prompted it.

**D-TG-146 — Messages that produced no prediction are recorded in `message_classification_attempts`.** FR-004,
FR-024, FR-051. One row per exclusion (unique per message) and one per final failure (append-only, naming the
model). A message's classification status is derived, in precedence: a current prediction → *classified*; an
exclusion → *excluded (reason)*; a failure → *failed (latest kind)*; nothing → *not classified yet*.

**D-TG-147 — Predictions are never updated.** FR-015. No code path issues an `UPDATE` or `DELETE` on
`message_classifications`; `is_current` exists, always true in this milestone, so TG-M8's reprocessing can
insert-and-flip without a migration. The panel's model throws on update and delete, as TG-M4's
`ModerationAction` does.

### Execution

**D-TG-148 — `classify_message` runs on queue `moderation_classify`, consumed by a dedicated `ai-classifier`
service (one process, one thread); `ai-worker` gains `--queues default`.** Finding 4, FR-022. Same image, same
entrypoint (`app.workers.main`), its own `mem_limit`. *Alternatives rejected:* the shared worker — Finding 4; a
Redis slot that re-enqueues when busy — still parks a thread on the lane whenever assessment generation holds
it, and turns a wait into message churn; a short gateway deadline — shortens the stall without removing it.

**D-TG-149 — Classification is enqueued by `derive_message`, after the insert commits, for every newly inserted
message — and never on re-derivation.** FR-001, FR-005. No settle window: the burst rule's delay belongs to
question judgement, not to recognising an advert (FR-001). `derive_message` gains
`schedule_classification: bool = True`; `rederive_chat` passes `False`, because a re-derived message is history
and a live-path prediction on it could open an incident dated today and charged to today's owner. History is
classified only by the catch-up command (D-TG-160), which never opens anything.

**D-TG-150 — A per-message claim in Redis stops two classifiers calling the model for one message.** SC-007.
`SET ai:mod:classify:msg:<chat pk>:<message id> <token> NX PX <call timeout + 30 s>`, released by an
owner-checked delete. The live service is single-threaded, so the claim matters only when the catch-up command
overlaps it. The partial unique index remains the correctness backstop; the claim prevents the wasted call. A
lock, not a fact — §7.3's rule for Redis holds.

**D-TG-151 — Transient failures are retried by the task: up to `MODERATION_CLASSIFY_MAX_ATTEMPTS` (5), delay
`MODERATION_CLASSIFY_RETRY_BASE_S × 2^(attempt−1)` (30 s base).** FR-023, FR-024. Transient =
`provider_unreachable`, `model_timeout`, `circuit_open` (M1 marks the last non-retryable because it fails
fast; for a task, a breaker that will close in 30 s is exactly transient). The actor re-sends itself with the
attempt number and a delay, so retry state is in the message, not in Redis. After the last attempt, or on any
other failure, one `failed` row is written. Unexpected exceptions keep Dramatiq's own `max_retries=3`, like
every other actor in the domain.

**D-TG-152 — With no active classification model, the classifier records nothing.** FR-025. The first step
resolves the `moderation` profile; `NoActiveProfileError` ends the task silently. Exclusions are not recorded
either, so an inert milestone writes nothing at all.

**D-TG-153 — The prediction and the incident it opens are written in one transaction, through the same
insert an operator's flag uses in Python.** FR-034, FR-035. `incidents.open_incident`'s insert is extracted into
`insert_incident(session, …)`: `opened_at` from the anchor, `detected_at = now()`, `responsible_at(chat,
detected_at)`, `ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING`. The classifier inserts the prediction
(`ON CONFLICT … WHERE is_current DO NOTHING`), and if its route is `incident`, calls `insert_incident` with
`source='ai'`, `opened_by_user_id=None`, the prediction's id, category and severity. Both commit or neither
does. Opening evaluates nothing else — TG-M4's I6 still holds, because incident state is a view.

### The control panel

**D-TG-154 — `ModerationIncident::openOn` gains an optional `?int $promptedByClassificationId`; the
possible-violations row action passes it.** FR-043, FR-044. Every other caller — the incidents list, the Live
Attention Queue — passes nothing and records an independent flag. The resulting incident is operator-opened in
every respect, with the operator's own labels.

**D-TG-155 — Possible Violations is a read-only custom page with a table, in the domain's navigation group.**
FR-041…FR-045. Like the Live Attention Queue, not a resource: there is no record to view or edit, and the one
row action opens TG-M4's form. Sorted newest first, filterable by group and posting period.

**D-TG-156 — Classification Accuracy is its own page; the SQL of `contracts/classification-metrics.md` is
quoted once, in a concern.** FR-046…FR-051, FR-057. Same arrangement as D-TG-90/D-TG-118. TG-M3's accuracy
query is quoted verbatim for the baseline, and the page reads its two rows the way the SQL returns them —
rule-opened counts per version, operator additions in the NULL-version row (probe 10).

**D-TG-157 — The model's view is shown wherever a label helps a person decide, always named as the model's
self-report.** FR-052…FR-056. Queue rows: category and confidence of the burst message chosen by
`classification-metrics.md` C6. Incident list: an "Opened by" column (Operator / Model) with a filter. Incident
detail: TG-M4's "No model classification — arrives with TG-M5" line is replaced by the model's view of the
message, or the reason there is none.

**D-TG-158 — The model roster offers the `moderation` role.** FR-053. `ModelProfileForm` and
`ModelProfilesTable` gain the option; `ModelProfile`'s existing one-active-per-role guard covers it unchanged.

**D-TG-159 — Detection latency is grouped by how an incident was opened.** FR-037. TG-M4's M16 statement gains
`i.source` in its select list and `GROUP BY`; nothing else in `incident-metrics.md` changes.
`contracts/classification-metrics.md` §7 states the amended statement; TG-M4's contract gets a pointer.

### The operator's commands

**D-TG-160 — `python -m app.scripts.classify_chat --chat <id> [--since] [--until]` is the catch-up.** FR-061,
FR-062. Composition root. Refuses an unmeasured chat, as `rederive_chat` does. Walks the chat's messages in
`sent_at` order that have no prediction and no exclusion, through the **same** classification function the
actor calls, with `path='catch_up'` — so every prediction it makes is `measurement_only`. Runs synchronously
through the gateway (the lane serialises it against the live service; the claim of D-TG-150 prevents
overlap), and prints `classified=<n> excluded=<n by reason> failed=<n by kind>`. A second run finds nothing to
do.

**D-TG-161 — `make smoke-moderation` classifies labelled JSONL fixtures read from standard input.** FR-063,
SC-001. `FIXTURES=<path> make smoke-moderation` streams the operator's file into the tools container; without
`FIXTURES`, the synthetic set shipped at `app/scripts/moderation_smoke_fixtures.jsonl` is used. Each line is
`{"text": …, "category": …, "needs_moderation": …}`; the text is normalised and redacted exactly as the
classifier does. `--profile <name>` smokes a named profile **before** it is activated, through a registry
subclass that pins that profile — the real gateway, lane and provider otherwise. Prints expected against
predicted per fixture and exits non-zero on any mismatch. The operator's fixtures never enter the repository.

---

## §3 — Settings

| Key | Default | Where |
|---|---|---|
| `MODERATION_CONFIDENCE_FLOOR` | 0.60 | **New.** Python `Settings`, validated; `.env.example`; Compose `${…:-0.60}` to `ai-classifier` |
| `MODERATION_INCIDENT_CONFIDENCE` | 0.85 | **New.** As above; `floor ≤ threshold` enforced |
| `MODERATION_CLASSIFY_MAX_ATTEMPTS` | 5 | **New.** Positive integer; task-level transient retries (D-TG-151) |
| `MODERATION_CLASSIFY_RETRY_BASE_S` | 30 | **New.** Positive; delay doubles per attempt |
| `MODERATION_PROMPT_VERSION` | `classify_v1` | **New (2026-10-01).** `classify_v1` or `classify_v2` only; blank = default; to `ai-classifier` and the tools container (`migrate`, which runs catch-up and the smoke test) (D-TG-163) |
| `GATEWAY_*` | M1's | **Exist.** Passed to `ai-classifier` as `${KEY:-default}`; `GATEWAY_CAPTURE_PAYLOADS` stays `false` |

The model's own bounds — context, output budget, temperature, reasoning — are **profile params**, edited in the
roster, not environment keys.

---

## §4 — What this milestone deliberately does not build

- The model opening, dismissing or closing any question item — the second clarification. `source = 'ai'` on
  `attention_items` stays reserved.
- A human verdict on a prediction, correction history, effective labels, reprocessing — TG-M8.
- Alerts of any kind, including for model-opened incidents — TG-M6.
- The overview and performance dashboards — TG-M7. The figures ship on this milestone's own page.
- A change to M1's fake provider (probe 7), to TG-M0's boundary check (Finding 3), or to TG-M3's accuracy
  query (probe 10).
- A fix for the assessment profile's reasoning cost (Finding 1) — M1/assessment.
- Any bot action, any deletion inference, any composite score, any average.

---

## §5 — Traceability

| Requirement group | Decisions |
|---|---|
| Which messages (FR-001…FR-006) | D-TG-137, D-TG-138, D-TG-139, D-TG-149, D-TG-150 |
| What the model is given (FR-007…FR-010) | D-TG-136, D-TG-138, D-TG-140, D-TG-162, D-TG-163 |
| The prediction (FR-011…FR-017) | D-TG-133, D-TG-135, D-TG-141, D-TG-142, D-TG-146, D-TG-147 |
| Running the model (FR-018…FR-025) | D-TG-129…D-TG-134, D-TG-148, D-TG-151, D-TG-152 |
| Routing (FR-026…FR-033) | D-TG-141, D-TG-142, D-TG-143 |
| Model-opened incidents (FR-034…FR-040) | D-TG-145, D-TG-153, D-TG-159 |
| Possible violations (FR-041…FR-045) | D-TG-145, D-TG-154, D-TG-155 |
| Measurement (FR-046…FR-051) | D-TG-146, D-TG-156, D-TG-159 |
| Screens (FR-052…FR-060) | D-TG-155…D-TG-158 |
| Commands (FR-061…FR-063) | D-TG-160, D-TG-161, D-TG-162 |
| Boundaries and continuity (FR-064…FR-070) | D-TG-132, D-TG-148, D-TG-149, D-TG-152 |

---

## §6 — Amendment 2026-10-01: the second instruction

The operator's end-to-end test put real messages through the live pipeline. Moderators had removed them, or
banned their senders, for promotion. The live classifier recorded a greeting-led institute advert as CHITCHAT,
with needs-moderation false at confidence 1.000: no incident, nothing listed. The same message sent straight
through the smoke test gave the same answer. Ingestion, normalisation, redaction, first-posted text and
routing all did what they were designed to do. The model, reading `classify_v1`, judged it not a violation.
The operator's 12-message real benchmark reproduced the problem: 9/12, with all three misses being violations
predicted as needing no moderation. Those messages stay outside the repository.

### ⚠ Finding 7 — `classify_v1` decides "advert" on surface cues, so adverts wrapped in a greeting or emoji, and services offered through a private contact, are missed.

Probe 11 compares each miss with the wording of `classify_v1` (§2 of the pipeline contract):

- **A greeting or emoji decides the category.** `classify_v1` defines CHITCHAT as "greetings, thanks, emoji,
  social talk". A medical-excuse advert opening with 🩺✅ came back CHITCHAT; so did the institute advert
  opening with a welcome. The held-out set did the same thing twice: a survey ending in 🙏, and a "good
  morning 🌸" that promotes a Telegram group.
- **An offer without a sale word is not recognised.** SPAM_OR_AD names "service" only generically.
  `classify_v1` never says an offer needs no price, link or "sale", and never names the call to action ("contact
  on WhatsApp «رقم»"). Two adverts from the same sender share the same opening. The one that says يتوفر
  ("available") is caught; the one that describes the service without that word is classified OTHER, needing no
  moderation.
- **No rule, so no violation.** needs-moderation is defined only as "a moderator should act against the
  message itself (SPAM_OR_AD and ABUSE usually do)". An informational outside announcement whose only fault is
  a student-posted link is correctly "OTHER, needs no moderation" under `classify_v1`. That rule is
  deterministic and is not the model's to infer (spec clarification session 2026-10-01).
- **Ruled out.** Length: adverts of 1,698 and 604 characters are caught, misses are 102–144. Obfuscation: NFKC,
  the Cf strip and tashkeel removal already turn presentation forms, ZWNJ and sukun into plain letters before
  the model sees them. The taxonomy: every case is expressible, and OTHER with needs-moderation is consistent
  under R8. Confidence: every wrong answer came back at 0.80–1.00 (Finding 2 still holds).

**Resolution (D-TG-162, D-TG-163).** A second instruction, `classify_v2`, opt-in. `classify_v1` is untouched.

### ⚠ Finding 8 — The runtime does not apply the profile's `num_ctx`; a long emoji-heavy message already approaches 2,048 tokens under `classify_v1`.

The Ollama server runs with `OLLAMA_CONTEXT_LENGTH=8192`, and its log shows `n_ctx_slot = 8192` for every one of
645 recorded slots, including the moderation profile's calls. Those calls ask for `options.num_ctx: 2048` through
the OpenAI-compatible endpoint, and the request is not honoured. Separately, probe 4's "4,096 characters fits
2,048" holds for plain text only. An emoji-heavy advert of about 4,000 characters is 1,937 prompt tokens under
`classify_v1` and about 2,190 under `classify_v2`; the log reports `truncated = 0` at 2,423. Nothing is lost
today. It would be lost if the server's context were set below about 2,300, or if the profile's value began to be
honoured. **Not resolved here:** it is M1 and runtime configuration, recorded so the profile's 2048 is not
mistaken for the effective limit.

### Probe 11 — v1 against candidate wordings

The real provider and profile params were driven against local Ollama. The input was normalised and redacted
exactly as in P1–P2, and routes were computed by `route_prediction` itself. Each set was run in identical
rounds and was deterministic.

There were five sets, 89 messages in all:
- the operator's 12 real messages, outside the repository;
- the live institute advert;
- the 12 shipped synthetic fixtures;
- 40 synthetic policy cases and near-misses;
- 24 synthetic held-out messages, written after the wording was frozen.

The 64 synthetic policy cases ship as `moderation_smoke_policy_fixtures.jsonl`, with fake numbers and handles.

The candidate wordings, counted on needs-moderation. v1, v2-A and v2-D ran on all 89 messages. v2-B, v2-C and
v2-E were dropped before the held-out set was written, so they ran on the first 65:

| Wording | Missed violations | False alarms | Note |
|---|---|---|---|
| `classify_v1` | 11 | 0 | the pattern in Finding 7 |
| v2-A: group rule, purpose over opener, explicit offers | 0 | 1 | "does anyone have the STEP collections file?" opened an **incident** |
| v2-B: A + "asking for something is not offering it" | 2 | 1 | the carve-out contradicts "surveys asking for participation" |
| v2-C: A + "a member asking for a file … is not SPAM_OR_AD" | 0 | 1 | the same false incident |
| **v2-D: A + "a question asking whether anyone has a file or summary is a question"** | **1** | **0** | the miss is a terse synthetic survey; the real survey and the held-out survey are caught |
| v2-E: D + "studies asking readers to take part" | 1 | 1 | worse on both |

**What v2-D does across the sets:**
- On the 12 real messages: 12/12 needs-moderation, 11/12 exact. The one category miss is the outside
  announcement, predicted SPAM_OR_AD instead of OTHER; its moderation decision is right.
- On the 24 held-out messages: 24/24.
- One legitimate question ("how do I get a sick note from the health app?") came back SPAM_OR_AD, needs no
  moderation. That combination is inconsistent, so it is **listed**, not opened.
- Every caught violation routes to `incident`.

**Cost:**
- about 250 more prompt tokens;
- no measurable latency change (median about 0.85 s against v1's 1.28 s).

**Smaller wordings flip borderline cases.** That brittleness is the model's (a 2B model leaning on lexical
cues). The wording mitigates it but does not remove it, and the pilot's false-positive rate of model-opened
incidents stays the gate (operator item 3).

Re-run through `make smoke-moderation` after implementation, giving the same per-fixture answers:

| Fixture set | `classify_v1` | `classify_v2` |
|---|---|---|
| Real 12 | 9/12 matched, needs-moderation 9/12, false negatives #1 #3 #12, 0 false positives | 11/12 matched, needs-moderation 12/12, 0 false negatives, 0 false positives |
| Policy 64 | needs-moderation 57/64, 7 false negatives, 0 false positives | needs-moderation 63/64, 1 false negative (#17), 0 false positives, 1 legitimate fixture listed (#4) |
| Shipped 12 | needs-moderation 12/12 | needs-moderation 12/12 |

**D-TG-162 — `classify_v2` is v2-D, word for word, and the smoke test reports misses apart from mismatches.**
FR-009, FR-063. The wording is §2a of the pipeline contract. It quotes none of the benchmark messages. It
describes the kinds of offer the operator's group removes: outside courses and tutors; files and study
material; services, medical excuses included; other groups and channels; surveys and outside projects;
income offers; and a private-contact call to action. It adds one carve-out, for a question asking whether
anyone has a file. v2-D was chosen over v2-A, which missed nothing, because a false incident counts against a
moderator until someone closes it, and a missed advert can still be flagged by hand (operator decision
2026-10-01). `taxonomy_version` stays 1.

The smoke test now prints each fixture's line number and live route (via `route_prediction`, N7). Its summary
adds category agreement, needs-moderation agreement, the false negatives and false positives with their line
numbers, and the route tallies. The "n/total matched" line and the exit code are unchanged.

**D-TG-163 — The instruction is chosen by `MODERATION_PROMPT_VERSION`, default `classify_v1`.** FR-009, FR-013.
An allowlist (`ModerationPromptVersion` in `app/infrastructure/config.py`) is the one definition of what may be
sent. A test keeps it, the files on disk and the pinned SHA-256s as one set. The classifier, catch-up and the
smoke test read it; `--prompt` overrides it for the smoke test only.

**Why a setting.** The operator decides when an instruction is trusted, as with activating a profile
(D-TG-129). The smoke test compares both on the operator's own labels first, and a rollback is an env change.

**What a switch does.** It revisits nothing (FR-015, FR-017). Each prediction keeps its version, and K3 already
keeps every figure apart by `(model, prompt_version, taxonomy_version)`; the panel shows the version on
Possible Violations and on the incident page.

**What it leaves alone.** No routing, threshold, eligibility, schema or panel change.

