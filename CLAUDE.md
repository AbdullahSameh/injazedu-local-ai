<!-- SPECKIT START -->
Active feature: **TG-M5 — AI Classification** (`specs/008-tg-m5-ai-classification/`)

Read before working on this feature:

- `specs/008-tg-m5-ai-classification/plan.md` — implementation plan, Constitution Check, the four operator items (**all approved 2026-09-27**)
- `specs/008-tg-m5-ai-classification/spec.md` — requirements (FR-001…FR-070), success criteria, clarifications (2026-09-27 ×2, 2026-10-01 ×3)
- `specs/008-tg-m5-ai-classification/research.md` — 35 decisions (D-TG-129…D-TG-163), 11 probes, **8 findings** (7–8 in the §6 amendment, 2026-10-01)
- `specs/008-tg-m5-ai-classification/data-model.md` — revision `0007`: two tables, the incident links, the `moderation` role
- `specs/008-tg-m5-ai-classification/contracts/classification-pipeline.md` — **the** TG-M5 contract: enqueue (Q1–Q4), the instructions `classify_v1` (§2) and `classify_v2` (§2a, opt-in), byte for byte, eligibility (E1–E10), input (P1–P5), the call (O1–O6), routing (R1–R13), opening (A1–A6), failure (F1–F6), idempotency (I1–I4), commands (C1–C5), what may never happen (N1–N10)
- `specs/008-tg-m5-ai-classification/contracts/classification-metrics.md` — the exact SQL behind every classification figure (C1–C8, M1–M22)
- `specs/008-tg-m5-ai-classification/contracts/control-panel-classification.md` — the model's view, Possible Violations, Classification Accuracy, the words
- `specs/008-tg-m5-ai-classification/quickstart.md` — smoke first, switch on, the live check, reading the figures, 16 known limitations

This is the sixth milestone of a **second bounded domain**. Its source plan of record is
`docs/plan/telegram/telegram-moderation-intelligence.md` (TG-M0…TG-M10); the operator's human steps are
`docs/runbooks/tg-operator-prerequisites.md` — **§C's TG-M5 row (Ollama running; 5–10 real Arabic messages
with known labels, kept outside the repo) is the smoke-test prerequisite**. Every automated test runs with the
model scripted and no runtime, credential or network.

TG-M5 puts **the first model** in front of the domain: each eligible message gets one immutable prediction
(category, needs-response, needs-moderation, severity, self-reported confidence). A confident, coherent violation
opens a TG-M4 incident (`source='ai'`); an uncertain or self-contradicting one is listed on **Possible
Violations**; below the floor it waits for TG-M8. **The model opens no question and closes nothing.** Still no
alert, no outbound message, no bot action. Alembic revision `0007` is consumed; `0008`–`0009` stay reserved.

The rules that carry this milestone:

- **A prediction is a claim.** Recorded once, with model, `prompt_version`, `taxonomy_version`, `model_run_id`,
  route and the thresholds in force — **never updated, never deleted** (`message_classifications`, no text).
- **The model sees words, never people.** The first-posted text is re-extracted from the message's own captured
  event, normalised, **redacted before the gateway**; the request is `system` = the configured instruction
  (`MODERATION_PROMPT_VERSION`: `classify_v1` default, `classify_v2` opt-in) + `user` = redacted text, nothing
  else. Never log text or the model's raw output.
- **One definition each.** Eligibility (E1–E8) and routing (R1–R6) are pure functions in
  `app/domain/moderation/classification.py`; the panel reads their stored outputs and never recomputes them.
- **The model never touches the lifecycle.** A prediction is not evidence; a model-opened incident goes through
  TG-M4's own `insert_incident`, in the same transaction as its prediction, and then lives exactly like any other.
- **Two conservative readings, approved** (operator item 4): consistency is judged both ways (an advert with
  needs-moderation false is *inconsistent* and listed); the group's linked channel's automatic forwards are excluded.
- **Catch-up is measurement only.** `classify_chat` and anything re-derived never open an incident or list anything.
- TG-M4's rules all still hold: seeing is not acting; nothing is called a deletion; incident state is derived from
  the views; human acts are guarded inserts under `pg_advisory_xact_lock(hashtext('moderation:incidents'))`;
  `moderation_actions` is append-only.

Eight measured facts that drive this design (see research.md §0 and §6):

1. ⚠ **The model reasons before answering** — at the plan's 128 tokens every answer was cut off.
   `reasoning_effort: "none"` (profile param, forwarded by the provider) → complete, ~1 s, deterministic. Operator item 1, **approved**.
2. ⚠ **Confidence barely moves** — 0.90–1.00 on everything. The band will be nearly empty; the model's
   false-positive count (C3) is the real control. Operator item 3, **decided**: keep 0.60 / 0.85, never treat
   confidence as a safety signal; the **pilot false-positive rate of model-opened incidents is the operational gate**.
3. ⚠ **Moderation cannot import `app.providers.llm`** — the gateway package exports the request types. Operator item 1, **approved**.
4. ⚠ **A classification waiting for the lane holds a worker thread** — own queue `moderation_classify`, own
   one-thread `ai-classifier` service, `ai-worker --queues default`. Operator item 2, **approved**.
5. ⚠ **An edit overwrites the stored words** — the model reads the captured event, not `telegram_messages`.
6. ⚠ **The gateway retries cut-off answers and returns no call id** — classifier gateway `max_retries=0`,
   task-level transient retry; responses carry `model_run_id`. Operator item 1, **approved**.
7. ⚠ **`classify_v1` decides "advert" on surface cues** — greeting- or emoji-wrapped adverts and private-contact
   service offers came back needing no moderation at 0.90–1.00 (real benchmark 9/12). **Decided 2026-10-01**:
   opt-in `classify_v2` (D-TG-162/163; 12/12 needs-moderation on the real set); thresholds unchanged; the
   students-may-not-post-links rule is deterministic and deferred to its own milestone, never put in a prompt.
8. ⚠ **The runtime ignores the profile's `num_ctx`** — Ollama runs at `OLLAMA_CONTEXT_LENGTH` (8192); keep it ≥
   4096 (a long emoji-heavy advert is ~2,200 tokens under `classify_v2`). Not fixed here: M1/runtime territory.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1); moderation reaches a model **only**
  through `app.application.gateway`;
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/`, and `app/`-root files such as `app/telegram_main.py` — are exempt **by directory**);
- **no Telegram SDK** outside `app/providers/telegram/`, and the provider exposes **no** ban / restrict /
  delete / react method;
- **no message text in any log line** (check 4). Correlation keys: `incident_id`, `message_id`,
  `update_id`, `chat_id` — never `message` (TG-M0's D-TG-24);
- **`app/domain/moderation/{attention,incident,classification}.py` stay pure**: no I/O, no clock, no session;
- **every `classify_vN.md` is pinned by its SHA-256** — a new wording is a new file, a new version and a new
  `ModerationPromptVersion` entry; the allowlist, the files and the pins are one set (tested).

Panel rules: Alembic owns the schema — **no migration from Filament**; no platform call, **no model call**,
no bulk action, **no average and no composite score anywhere** (tested); **no state, route or eligibility
computed in PHP**. Confidence is always "self-reported", never a percentage or a probability. Feature tests use
`DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase`, `DatabaseMigrations` or
`migrate:fresh`. No `GRANT` in a migration: the migrator's default ACL reaches `ai_control` and `ai_app` for new
tables and views. Arabic content keeps `dir="auto"` **per field**; the panel locale and chrome stay English and LTR.

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`,
`specs/002-m1-model-gateway/`, `specs/003-tg-m0-moderation-foundation/`,
`specs/004-tg-m1-telegram-ingestion/`, `specs/005-tg-m2-groups-and-ownership/`,
`specs/006-tg-m3-response-tracking/`, `specs/007-tg-m4-policy-incidents/`. The M1 gateway gains four additive
extensions (operator item 1) and nothing else. Consumed here: M1's gateway, lane, breaker, accounting and fake
provider; TG-M0's normaliser and redactor; TG-M2's `derive_message` and `rederive_chat.py`; TG-M3's stoplist,
accuracy figures and Live Attention Queue (one column added); TG-M4's incidents, views, `openOn`, figures table
and incident pages.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
