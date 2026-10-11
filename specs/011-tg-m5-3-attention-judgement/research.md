# Research: TG-M5.3 — A Separate Attention Judgement

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Date**: 2026-10-07 · **Plan of record**:
`docs/plan/telegram/tg-m5-3-attention-judgement-plan.md` (approved 2026-10-06; amendments approved 2026-10-07)

The spec has no open clarification. This file records:
- what was measured in the repository before designing (§0);
- the decisions that turn the plan into code-level choices (§1);
- the qualification runs, which are filled during implementation (§2).

Decision numbers continue from 010 (D-TG-181), and finding numbers from 010 (Finding 13).

## §0 — Findings

**Finding 14: rule set v1 already opens the operator's peer questions and the greeting-led burst** (probe,
2026-10-07, `evaluate` on `normalize()`d text, booleans only).
- «يا شباب مين اختبر اليوم؟» and «يا أحمد كيف حليت السؤال 15؟» open by rule (`مين`, `كيف`, `؟`). So does the first
  one without `؟`.
- «السلام عليكم» + «متى موعد الاختبار؟» opens on the second member, with or without `؟`.
- «… بس الرابط مش شغال» opens on its own: `مش شغال` is a v1 literal.
- Variants ending «بايظ», «مش راضي يفتح», «لا يعمل» or «ما فتح معي» decline.
- **A trap for fixture writers:** `من` is a v1 literal. «من امبارح» opens a burst that looks rule-declined.

*Consequence:*
- The `discussion` intent can only decide peer questions with no v1 signal.
- Most peer-discussion volume is rule-opened, so it is reachable only by a dismissal reason (D-TG-182).
- Every fixture meant to be rule-declined must be checked with `evaluate` (D-TG-193).

**Finding 15: every dismissal-based figure counts `status = 'dismissed'` regardless of reason, and the panel says
otherwise.**
- `ClassificationMetrics::classificationModelOpenedQuestions` (C9) and `classificationRuleBaseline` (C7) filter on
  status only. So do TG-M3's §3 and §5 SQL.
- `classification-accuracy.blade.php:145` prints "dismissed as not a real question", and
  `ModelOpenedQuestionsTest.php:132` asserts that sentence.
- **On the development database** (read-only count, 2026-10-07), 10 items are dismissed: 9 `message_removed` and
  1 `not_a_question`. Most dismissals the label describes are not what it says.

**Finding 16: a third dismissal reason needs no schema change.**
- `attention_items.close_reason` is `varchar(40)` with no CHECK (revision `0005`).
- TG-M3 FR-051 requires "at minimum" two reasons.
- No Python code branches on a reason's value. Only expiry writes one: `expired`.

**Finding 17: the prompt pin test would reject a second instruction family.**
- `test_prompt_pinned.py` asserts that the `*.md` files under `app/prompts/moderation/` equal the pinned
  `classify_*` set.
- An `attention_v1.md` beside them fails it until the test knows about two allowlists (D-TG-189).

**Finding 18: Dramatiq orders a worker's fetched messages by actor priority.**
- Dramatiq 2.2.1 (`worker.py`) puts every fetched message on a `PriorityQueue` keyed by `actor.priority`:
  lower runs first, FIFO among equals.
- `ai-classifier` runs one process with one thread. With both queues consumed by it, an attention actor with a
  lower priority number runs before a waiting classification.
- This is the configuration that carries the current scheduling policy (D-TG-187).

**Finding 19: every existing `attention_items` row already satisfies the new link check.**
- On the development database (read-only, 2026-10-07):
  - the 1 `ai` item carries `message_classification_id`;
  - the 22 `rule` and `operator` items carry none.
- `ck_attention_ai_link` (data-model §3) can therefore be added without touching a row.
- The schema is at `0007`.

## §1 — Decisions

**D-TG-182: Story 1 ships first and alone.**
- **What it is:** the `member_discussion` reason, the per-reason breakdowns on C7 and C9, and the wording
  corrections.
- **What it does not touch:** any table created by this milestone, the model, and every switch.
- **Why:** Finding 14 says most peer questions are rule-opened, and Finding 15 says the figures already
  misdescribe dismissals. Both are true today, without any model work.
- **Rejected:** shipping it with the revision, which would delay a fix the operator needs now. Also rejected:
  applying it outside 011, which the operator declined on 2026-10-07.

**D-TG-183: dismissal counts keep counting every reason. The breakdown is additive.**
- Every existing figure (TG-M3 §3 and §5, C1, C7, C9 and the M24 gate) keeps its definition.
- C7 and C9 gain four columns:
  - `dismissed_not_a_question`, `dismissed_member_discussion` and `dismissed_message_removed`;
  - `dismissed_other`, for operator free text or any other value.
- A test asserts the parts sum to the count.
- **Rejected:** excluding `message_removed` or `member_discussion` from the false-positive numerators. That
  would change shipped figures and the pilot gate's meaning mid-history, and the operator said no.

**D-TG-184: the attention judgement has its own record, typed and insert-only.**
- **The tables:** `message_attention_judgements` and `message_attention_attempts`, mirroring revision `0007` §2–§3
  (data-model §1–§2).
- **Rejected:** a generic `ai_judgements` table with a jsonb output (no CHECK, and two patterns anyway); a `task`
  column on `message_classifications` (every C1–C9 query would change); columns added to the classification row
  (it would be updated).

**D-TG-185: the output is `{"intent": …}`, one of six. Needs-response is derived in the domain.**
- `app/domain/moderation/attention_judgement.py` holds `INTENTS`, `needs_response_for(intent)` and the
  eligibility skip (D-TG-186). It is pure and imports only the standard library and
  `app.domain.moderation.{attention,classification}`.
- The stored `needs_response` comes from this function. No CHECK restates the mapping (008 data-model §2's
  "no second definition").

**D-TG-186: eligibility is the classification's, plus one rule skip.**
- **AE1:** `classification.eligibility(facts)`, with the same `MessageFacts` from the same `load_facts`, so the
  reasons are the eight E1–E8 values.
- **AE2:** `evaluate([normalize(first_posted_text)])` is true, so the message is excluded as `rule_opens`.
  - **Why this skip is exact:** if a message's own words open, it is not an acknowledgement, so every burst
    containing it opens by rule and the judgement can never be read.
  - **The one gap:** an edit inside the settle window that removes the signal (plan §3). It is stated in the
    contract's limitations.

**D-TG-187: dispatch, queue and the current scheduling policy.**
- **Dispatch:** `derive_message` sends `judge_attention(chat_pk, message_id)` for every newly inserted message,
  **before** `classify_message` and under the same condition (Q1). The judgement records exclusions itself,
  moderators' included, like the classifier.
- **The actor:** a new `judge_attention`, on its own queue `moderation_attention`.
- **The current deployment** (`infra/docker-compose.yml`):
  - `ai-classifier` consumes `moderation_attention` and `moderation_classify` with 1 process and 1 thread;
  - the attention actor has `priority=0` and `classify_message` gets `priority=10`.
  - With Finding 18, Attention runs first whenever both wait on this worker.
- **Changeable without a contract change:** separate services, more threads or a concurrent serving stack are
  compose and gateway lane settings only.
- **Rejected:**
  - the same queue, which loses per-task accounting and makes priority impossible;
  - a second one-thread service on the development Mac, which adds a process and still competes for the single
    `llm` lane in arrival order.

**D-TG-188: the gateway call.**
- The call is `generate_structured(StructuredRequest(messages, schema_model=AttentionJudgementResult),
  role="attention")`, on a per-task `Gateway(max_retries=0)`, as Finding 6 requires.
- The input is `[system = attention_vN.md, user = redact(first-posted text)]`. The redacted string is bound only
  to `redacted_text` (check 4).
- `AttentionJudgementResult` is a pydantic model with one field, `intent: Literal[...]`. Anything else raises
  `StructuredOutputInvalidError`, a recorded `structured_output_invalid` failure.

**D-TG-189: instruction files, allowlists and pins.**
- **The allowlist is a tuple:** `ATTENTION_PROMPT_VERSIONS: tuple[str, ...]` in `app/infrastructure/config.py`.
  It is **empty until the freeze**, then `("attention_v1",)`.
  - **The setting:** `MODERATION_ATTENTION_PROMPT_VERSION: str | None = None`, with a validator that refuses any
    value outside the tuple and names the variable (the fail-fast pattern). Blank means no attention calls.
  - **Why not a `Literal` like `ModerationPromptVersion`:** a `Literal` cannot be empty. A provisional
    `attention_v1.md` written before selection would repeat TG-M5.2's provisional-file mistake, and the
    candidates must stay outside the repository until frozen (D-TG-196).
- **The pin test** becomes: every file under `app/prompts/moderation/` is in exactly one of `PROMPT_VERSIONS` and
  `ATTENTION_PROMPT_VERSIONS`, and each allowlist equals its pinned set. The attention pin set is empty until the
  freeze. The G4 sentence test stays on `classify_*` only.
- **Tests before the freeze:**
  - `judge_one` takes an optional `instructions` mapping (default: the loaded pinned files), so tests pass a
    test-only instruction;
  - `Settings.model_copy(update=…)` sets its version without the validator.
- **At the freeze,** in one change: `attention_v1.md`, its tuple entry and its pin.

**D-TG-190: the model role is `attention`.**
- **What changes:**
  - `Role` and `GenerationRole` gain `"attention"`;
  - `ck_model_profiles_role` gains `'attention'`;
  - the panel's role select and filter gain the option;
  - `registry.resolve("attention")`.
- **The seed roster** gains `ollama-gemma4-e2b-attention` and `ollama-gemma4-e4b-attention`, both inactive, with
  the moderation params (`num_ctx 2048`, `num_predict 128`, `temperature 0`, `reasoning_effort none`).
- Profiles 14 and 17 are untouched, and `gemma4:e4b-it-qat` stays installed.

**D-TG-191: opening reads attention judgements. The classification-sourced proposal is removed.**
- **The domain:** `proposes_attention` becomes `judgement_proposes(path, needs_response)`, which is A1–A2.
  `within_attention_window` is unchanged (G5–G6).
- **The veto:** a new pure `vetoed(category)`, true for `SPAM_OR_AD` and `ABUSE`. It replaces G4 and the
  `NO_RESPONSE_CATEGORIES` gate.
- **`open_item`:** `_model_proposal` now reads `message_attention_judgements`, joined to the member's current
  classification for the veto, and writes `attention_judgement_id`.
- **`classify_one`** no longer calls `request_rejudgement`. **`judge_one`** calls it in the same transaction as
  its insert, when the judgement is live, its needs-response is true and the switch is set.
- **Removed:** `proposes_attention` and `NO_RESPONSE_CATEGORIES`, with no second home. Their callers are
  `open_item`, `classify_one`, `smoke_attention.py`, `qualify_moderation.py`, `test_attention_gate.py` and
  `test_ai_attention.py`, and all are re-pointed (D-TG-195).
- **Kept:** the G4 sentence test in `test_prompt_pinned.py`. It reads the `classify_*` prompt text, not the
  constant, and `classify_v2` still carries the sentence.

**D-TG-192: the revision is `0008_moderation_attention_judgement`.**
- It takes the next free number.
- The roadmap's reservation in `docs/plan/telegram/telegram-moderation-intelligence.md` gets a dated note: the
  revision table row and the "Alembic numbering" paragraph. Alerts and reviews move to the next free numbers,
  and assessment continues after them.
- **Why this is safe:** the chain is linear, and "whichever ships first wins" is the roadmap's own rule.

**D-TG-193: fixture keys and validation.**
- **The keys:**
  - `intent`: one of six; it must equal `asking` exactly when `needs_response` is true;
  - `peer: true`;
  - `burst`: a list of 2–5 texts, which replaces `text`;
  - `expected_opener`: required on burst lines, and allowed only there.
- **An unknown or disagreeing key is a `FixtureError`**, so the run is `INCOMPLETE`.
- **`test_attention_fixture_files.py`** asserts that every `peer` line in the in-repo validation and held-out
  files is rule-declined, using `evaluate([normalize(text)])`.

**D-TG-194: the qualification core and suites.**
- **The layout:** `app/scripts/qualification/` holds:
  - `core.py`: sets, keys, repeat, latency, gate table, verdict, exit code and the no-text formatter;
  - `moderation.py` and `attention.py`: the two suites;
  - `__main__.py`, run as `python -m app.scripts.qualification --task attention|moderation`.
- **The old entry point:** `qualify_moderation.py` stays as a thin wrapper, and `make qualify-moderation` stays
  an alias of `make qualify TASK=moderation`.
- **What moves:**
  - the moderation suite keeps Q5–Q7, Q11 and Q12, with repeat;
  - Q1–Q4, Q9 and Q10 move to the attention suite as A1–A5 and A8, with the new A6, A7 and A9.
- **Rejected:** one combined command. Each switch is per task.

**D-TG-195: the attention suite's per-fixture judgement is the live path.**
- **One-message lines:** `normalize`, then `evaluate([text])` (the opener is `rule`, and AE2 means no call), then
  `eligibility` (`excluded`), then the gateway with `role="attention"`, then `needs_response_for`.
  - The opener is `model` when the line's needs-response is true; otherwise `none`.
  - A6 runs the same function on every moderation-set line whose label has needs-moderation true, with no veto
    applied.
- **Burst lines:**
  - `evaluate(all members)` gives `rule`;
  - otherwise each member goes through AE1, AE2 and the model, and the first `asking` member gives `model`,
    with its index;
  - otherwise `none`.
  - Reported only.
- **`smoke_attention.py`** keeps its role as the quick single-file check (`make smoke-attention`). It now calls
  the attention suite's per-fixture function, `judge_attention_line`. The classification-based judgement it ran
  for TG-M5.1 is removed with `proposes_attention`, so there is one benchmark path, not two (N7).

**D-TG-196: candidate wordings are files outside the repository until frozen.**
- `--candidate-file PATH` (read-only fixtures mount) replaces the pinned instruction for a run. It prints
  `CANDIDATE` and the SHA-256 of the file, and the verdict can never be `QUALIFIED`.
- The three candidates' hashes are recorded in §2 before the first run.

**D-TG-197: the metrics.**
- **C9 becomes a union of two eras,** each grouped by its own opening record:
  - classification-linked (TG-M5.1), grouped by `(model, prompt_version, taxonomy_version)`;
  - attention-linked (TG-M5.3), grouped by `(model, prompt_version)`.
- **C10 is new** (`contracts/attention-metrics.md`): attention status per eligible message, judgements by intent,
  timeliness, and operator-added items split by anchor status and burst size.
- **Timeliness:** a live judgement is on time when `created_at ≤ sent_at + MODERATION_BURST_GAP_S`, the instant
  its message's own delayed judgement runs. The panel reads `MODERATION_BURST_GAP_S` through
  `config/moderation.php`, as it already reads two other moderation settings.
- **Not added:**
  - C1 and C2 attention rows: AE2 skips most rule-opened members, so these would be near-empty;
  - an intent on the C6 queue label: every model item is `asking` by construction.

  Both are deferred, not designed.

**D-TG-198: nothing reprocesses or backfills.**
- Historical TG-M5.1 items keep their classification link.
- Catch-up never judges attention: `classify_chat` is unchanged, and no attention catch-up command is added.

**D-TG-199: the opener is on only when both settings are set.**
- `ai_attention_from_settings` returns `None` unless `MODERATION_AI_ATTENTION_FROM` **and**
  `MODERATION_ATTENTION_PROMPT_VERSION` are set. It remains the one place every judgement path builds the
  switch (TG-M5.1 L2).
- **What this makes exact:** spec FR-322 ("instruction blank → no model item opens, even with the switch set")
  holds even when judgements recorded earlier are still inside the window.
- **Deployment consequence:** `ai-worker`, which runs `evaluate_attention` and the sweep, receives
  `MODERATION_ATTENTION_PROMPT_VERSION`, as `ai-classifier` does.

**D-TG-200: Policy D′, and `attention_v2` in a second cycle** *(2026-10-09)*.
`docs/plan/telegram/tg-m5-3-attention-v2-addendum.md` was approved with every recommended option.
- **Why:** the operator reviewed T077's real sample and found Policy D's D2, D5 and D7 too broad. Peer questions
  about outside institutions came out `asking` but need no moderator: admissions, national-exam registration,
  appointments and results, licence eligibility, and outside sites that hang. The operator chose option (a)
  (2026-10-08): outside institutions are not the team's.
- **The policy:** Policy D′ (spec FR-310; `contracts/attention-judgement.md` §5′).
  - D0 is new: the team's responsibility.
  - D1, D2, D3, D5 and D7 are amended, as are the `asking`, `discussion` and `informing` definitions and Policy
    S's scope.
  - D7 still leans to `asking` when it is unclear whose service a message means.
- **Why a new version:** `attention_v1` states the old D2, D5 and D7, so it no longer states the policy (P3, N5).
  - It stays frozen, pinned and allowlisted as history. Its T071–T077 evidence is valid under Policy D only.
  - The new wording is `attention_v2`, through W-1′ to W-7′ (`contracts/qualification.md` §8′).
- **The sets:**
  - T077's 37-line sample is relabelled under D′ and becomes tuning, never fresh again.
  - The v1 held-out set becomes a byte-identical validation set, and a scope validation set is added. A3 is
    judged per validation set.
  - A new held-out set is written after the freeze, on topics fixed now, and the operator supplies a new fresh
    sample.
- **What it does not change:** the schema, PHP, the panel, dispatch, opening, V, or the six intents and their
  single derivation.
  - The panel's figures already split by `prompt_version`.
  - Rule-opened outside-institution questions still open by rule (7 of the operator's 8 examples) and are
    dismissed as "Member discussion". A rule-set change would be its own milestone.

## §2 — Qualification runs

*Filled during implementation, as counts only. The candidate hashes are recorded before the first run.*

| Run | Pair | Sets | Result |
|---|---|---|---|
| T002 moderation baseline (2026-10-07) | e2b (`gemma4:e2b-it-qat`) + `classify_v2` | 010's six sets; held-out and fresh missing | `NOT QUALIFIED` (exit 1), as in 010 |

### Baseline before any change (T001, 2026-10-07)

`make check` before the first edit, with Ollama **running**: the live development stack (`ai-classifier`) was
using it, so it was not quit. No automated test calls a model, so this does not change the outcome.
- ruff, the architecture and domain-boundary checks (1–4), and mypy: green.
- pytest: 1011 passed, 3 skipped, 2 deselected, **4 failed**, all in `tests/moderation/test_secret_scan.py`. They are
  010's known failures (010 research §2): the `*_KEY = …` heuristic flags `by_key = {…}` at
  `tests/moderation/classification/test_metrics_model_opened.py:129`. Not fixed here (T001).
- `make check` stops at pytest, so the last three steps were run by hand, with the test schema restored to head
  first (as `check.sh` does):
  - PHP Feature suite: OK, 129 tests, 594 assertions.
  - Secret scan: FAILED on the same single line, `test_metrics_model_opened.py:129`.

### Moderation baseline: e2b + `classify_v2` (T002, 2026-10-07)

`make qualify-moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`

This is SC-305's "before". It ran before any code change.
- **Run:** floor 0.600, threshold 0.850, `--repeat 2`, 300 calls, 4 min 47 s.
- **External sets:** still not annotated (010's T031), so every real attention line counts as `clear` and real
  moderation #1 is not tracked.
- **Text:** none in the output. No Arabic character appeared.

| Gate | Status | Counts |
|---|---|---|
| Q1 | FAIL | 14: `real-attention-extra.jsonl` #13, #15, #16, #17, #19, #20, #21, #22, #23, #24; `real-attention.jsonl` #18, #21, #22; shipped attention #10 |
| Q2 | NOT RUN | no held-out set |
| Q3 | FAIL | 2: `real-attention-extra.jsonl` #2, #5 |
| Q4 | NOT RUN | no held-out set |
| Q5 | PASS | real moderation: needs-moderation 12/12, false negatives 0, false positives 0 |
| Q6 | PASS | shipped moderation: false negatives 0, false positives 0; tracked #11 `label-review` PASS |
| Q7 | PASS | policy: false negatives 1 (#17), false positives 0, legitimate → incident 0 |
| Q8 | PASS | 0 differing lines between the two runs |
| Q9 | NOT RUN | no `fresh-attention.jsonl` |
| Q10 | PASS | p95 1,190 ms, median 884 ms |
| Q11 | PASS | 0 errors |
| Q12 | PASS | 1 tracked line: shipped moderation #11 |

**Every line's status (run 1; run 2 identical):**
- `real-attention-extra.jsonl` (24): FN #2, #5; FP #13, #15, #16, #17, #19, #20, #21, #22, #23, #24; the other 12 OK.
- `real-attention.jsonl` (24): FP #18, #21, #22; the other 21 OK.
- `attention_smoke_fixtures.jsonl` (15): FP #10; #15 excluded before the model; the other 13 OK.
- `real-moderation.jsonl` (12): 11 OK. #1 is a category mismatch only (expected OTHER, predicted SPAM_OR_AD); it needs
  moderation on both sides, so it is not an FN or FP.
- `moderation_smoke_fixtures.jsonl` (12): 11 OK. #12 is a category mismatch only (OTHER vs CHITCHAT; neither needs
  moderation).
- `moderation_smoke_policy_fixtures.jsonl` (64): 59 OK. FN #17 (needs moderation, read as not). Category mismatches only:
  #4 (read SPAM_OR_AD without needing moderation, so it routed `possible_violation/inconsistent`), #22, #32, #54.

The gate statuses and line numbers match 010's T013 baseline exactly. Only the latency moved (p95 977 → 1,190 ms).

### After Story 1 (T013, 2026-10-07)

Story 1 (T003–T012) changed no existing dismissal figure (SC-301):
- **The SQL:** in `metrics.py` and `ClassificationMetrics.php`, the only changed lines of C7/TG-M3 §5 and C9 are
  `rule_version` and `… AS model_unanswered`, each gaining a trailing comma. The four breakdown columns are
  appended after them.
- **The values:** every pre-existing assertion on `rule_dismissed`, precision, `model_dismissed`, `model_kept` and
  the other C9 counts passes unchanged (`test_metrics.py`, `test_accuracy.py`, `test_metrics_model_opened.py`). The
  one exception is the PHP sentence assertion: its text changed (K11), and its value (1 / 3) did not.
- **The checks:** `make check` gives the same result as T001, with one more test. ruff, the checks 1–4 and mypy are
  green. pytest: 1012 passed, 3 skipped, 2 deselected; the same 4 `test_secret_scan.py` failures.
- **By hand, on a test schema emptied and migrated to head:** PHP Feature OK, 134 tests (129 + 5 new), 639
  assertions. The secret scan flags only the same known line, now `test_metrics_model_opened.py:144`, because a helper
  was added above it.
- **A test-database note:** `make test-db-reset` drops only `users` and `alembic_version`, so on a schema at head it
  fails with `DuplicateTable`. The schema was emptied with `test_migrations.py`'s own drop list instead. That script
  predates TG-M1 and is left to the operator.

### After Phase 3, Foundational (T026, 2026-10-07)

Revision `0008`, the `attention` role, the setting and the pure domain module are in. No model is called.
- **The checks:** `make check` gives the same result as T013. ruff, the checks 1–4 and mypy are green. pytest: 1071
  passed (+59), 4 skipped (+1: the attention pin test has no parameters until the freeze), 2 deselected; the same
  4 `test_secret_scan.py` failures. `injaz_ai_test` is at `0008 (head)`.
- **By hand, on a test schema emptied and migrated to head:** PHP Feature OK, 134 tests. The secret scan flags only
  the same known line, now `test_metrics_model_opened.py:136`.
- **Not applicable in T020:** `app/infrastructure/models.py` declares no `model_profiles` constraint at all (0007
  added none there either), so there is no `ck_model_profiles_role` to mirror. The role check lives in the
  revisions only.
- **Knock-on test changes,** none of them a behaviour change:
  - every older migration test's drop list names the two new tables (`test_migrations.py`,
    `test_migration_0002.py` … `test_migration_0007.py`), or a schema at `0008` would not empty cleanly;
  - `ck_attention_ai_link` refuses an `ai` item without its link at insert. `insert_attention_item` now takes
    `message_classification_id` and `attention_judgement_id`, `test_metrics_model_opened.py` passes the link at
    insert instead of updating it afterwards, and `LiveAttentionQueueTest.php` gives its model item a TG-M5.1-era
    prediction;
  - the classification conftest's schema guard checks `message_attention_judgements`, so a test database left at
    `0007` is brought to head;
  - `test_boundary_checks.py` gains the purity test for `app/domain/moderation/attention_judgement.py`, as its
    three siblings have.
- **Operator note:** `tests/gateway/test_seed.py` seeds the `attention` rows, so `injaz_ai_test` must be at `0008`
  before `tests/gateway` runs. A full run reaches it through `test_db_privileges.py`'s upgrade.

### After Phase 6, qualification version 2 (T062, 2026-10-07)

The qualification is split into `app/scripts/qualification/` (`core.py`, `attention.py`, `moderation.py`,
`__main__.py`); `qualify_moderation.py` is a thin alias and `smoke_attention.py` calls the attention suite's
`judge_attention_line`. T048's deletion of `proposes_attention` and `NO_RESPONSE_CATEGORIES` landed with T060. No
model was run: every result below is scripted.
- **The checks:** ruff and mypy (94 files) green; the architecture and domain-boundary checks 1–4 OK. pytest: 1239
  passed, 4 skipped, with `test_secret_scan.py` run apart: the same 4 known failures, and the scan flags only the
  same known line, now `test_metrics_model_opened.py:150`.
- **SC-305, version 1's moderation output:** checked against `qualify_moderation.py` at `HEAD` on the three
  synthetic moderation sets with a scripted gateway (errors, out-of-range confidences and run-to-run differences
  included). The per-line detail, the error lines, every moderation set block and the Q5–Q8, Q11 and Q12 gate lines
  are byte-identical. Only the gate table's rows change: Q1–Q4, Q9 and Q10 moved to the attention suite (A1–A5,
  A8).
- **Choices the contract left open, recorded here:**
  - the attention header is `qualify-attention: profile=… model=… prompt=<version | CANDIDATE sha256> repeat=…`;
    the moderation header is version 1's, unchanged;
  - a burst's opening member is reported 1-based; a burst with a failed member and no proposing member has opener
    `error`, and its calls count towards A7–A9 though the set is never gated;
  - R-discussion's "peer lines correct" means opened exactly as the label says (needs-response agreement); intent
    agreement is R-intent's;
  - tracked attention lines stay out of A1–A5 and are printed per set (N3), with no gate of their own;
  - a candidate run withholds the held-out and fresh sets (`NOT RUN: withheld in candidate mode`, W-2, N5);
  - `make qualify` also passes `MODERATION_P95_MS` and `SERVING` through to the per-message estimate (S6).

### After Phases 7–8, the validation and burst fixtures and C10c (T063–T069, 2026-10-07)

Two synthetic sets are in `app/scripts/`, written before any candidate wording exists. No model was run, and no
validation result has been seen.
- **`attention_validation_fixtures.jsonl`, 42 lines.** Every line carries `text`, `needs_response`, `intent` and
  `label_class`. Topics are plan §8.3's validation list only; no line carries a held-out topic word from plan §9.
  - 13 non-peer clear positives (12 service questions or problems, 1 injection-shaped), all rule-declined, plus 1
    rule-opened positive (#13, carrying `؟`), which never reaches the model;
  - 12 non-peer clear negatives (8 `informing` including a D4 answer and a resolved status, 2 `social`,
    1 `offering`, 1 injection-shaped `informing`), all rule-declined, plus 1 rule-opened `social` line (#25), R-rule's
    baseline;
  - 13 `peer` lines, all rule-declined: 7 D3 `discussion` (#28–#34), 4 D2 and 2 D5 `asking` (#35–#40);
  - 2 D6 lines, `asking`, `label_class: ambiguous`, no `peer` (#41, #42).

  So A3 reads 19 rule-declined clear positives and 20 clear negatives. Every line, and every peer line in
  particular, was checked with `evaluate` while it was written (the `من`, `ابي`/`ابغي` and `مشكله` traps avoided).
- **`attention_burst_fixtures.jsonl`, 8 lines,** each with `burst`, `needs_response`, `intent` and
  `expected_opener`: #1–#2 `rule` (plan §3a's first and third bursts); #3–#5 `model` (the «بايظ», «مش راضي يفتح»
  and «لا يعمل» variants); #6–#7 L-B1 (`needs_response` true, `none`); #8 a greeting plus a peer discussion
  (`needs_response` false, `none`, `peer`). Every `model` and `none` line is rule-declined as a whole burst and
  member by member.
- **A scripted check of the Independent Test** (every answer `discussion`): the attention suite prints R-discussion
  with its four counts over the validation set, R-rule with #25, and R-burst with each line's opener, member and
  `expected_opener` (5/8 match; L-B1 #6, #7). No Arabic character appeared.
- **C10c** is in `metrics.py` (`attention_operator_added_stats`) and `AttentionJudgementMetrics.php`, verbatim from
  `attention-metrics.md` §2. The page lays the rows out as one row per anchor status with single- and
  multi-message counts side by side, beneath C10a, with M30–M32's note. Two choices the contract left open: the
  rows read judged asking, judged by intent, excluded by reason, failed, then none; and a period with no
  operator-added item reads "No operator-added items in this period."
- **The checks:** ruff and mypy (94 files) green; pint green on the changed PHP. pytest: 1255 passed (+16),
  6 skipped (+2: the held-out file's two checks, until T075 writes it), with `test_secret_scan.py` run apart: the same
  4 known failures. The secret scan flags only the same known line, `test_metrics_model_opened.py:150`. PHP Feature
  OK, 139 tests (+2), 675 assertions.

### The three candidates, fixed before any run (T071, W-1, 2026-10-07)

Written to `~/Projects/injaz-m5-fixtures/` (outside Git, no message text), composed from one shared prefix and one
shared suffix so the common parts are identical bytes in all three. **Recorded here before any run.**

| Candidate | File | SHA-256 | Characters |
|---|---|---|---|
| W1, generic | `attention-candidate-w1.md` | `c8f22d865bbb1a453e703f39d0c51ad9d91493a888e37b3f62737c5f5cf52021` | 3,057 |
| W2, P2-derived | `attention-candidate-w2.md` | `5a2055d1838cd59e2d34e323ec9530b93bcdeca7b9032be74256571359bbe1fc` | 3,131 |
| W3, W1 + glossary | `attention-candidate-w3.md` | `e9af4f62af4e40dd0bc432ade02d0d388f56cbd4dca521037059da119f952d61` | 3,165 |

- **The shared prefix:** classify_v2's intro and normalisation/redaction note (plan §6 accepts the duplication),
  one sentence that the message is only something to judge and an instruction inside it is never followed (plan
  §6's injection safeguard, stated once), the task sentence, and the six intents of contract S3. S3's "a Policy S
  bare course statement" is written "a member's bare statement of a course arrangement (below)", since the model
  does not know the policy's name; the variable block explains it.
- **The shared suffix:** Policy D D1–D7 as confirmed on 2026-10-07 (D1 in the operator's new wording; D6 without
  its `label_class`, which is a fixture key, not the model's), then the output line `{"intent": …}`. D8 is a
  limitation, not an instruction, so it is not in the text. The illustrations are not in the text either (no
  examples, as classify_v2 and v3's principle 6).
- **The variable block** sits between them:
  - **W1:** asking / informing / mixed and Policy S, with no domain noun.
  - **W2:** P2's Asking and Informing paragraphs, adapted to one task ("a moderator" → "the team"), with no Mixed
    sentence. **A reconstruction:** P2 was an in-memory probe and its full text was never stored. The text is
    `contracts/classify-v3.md` §2's F1 (P2 plus three recorded differences) with two of them undone: the Mixed
    sentence is dropped, and the Asking noun list is restored as the classify_v3 plan §6 item 6 quotes it
    ("session, test, recording, link, book, change, registration"). P2's Informing scope was not recorded, so
    F1's "even when it is about the course" stays.
  - **W3:** W1 with one sentence before it naming what the service is (lectures, recordings, links, books,
    exams, registration, platform).
- **Noted, not changed:** Policy D's D2 names "certificates" among service subjects, and the certificate is one of
  plan §9's held-out topics. This is the policy the operator confirmed before the held-out set exists, not a
  fixture word, and it is identical in all three candidates.
- **The decision rule (W-3), fixed before running:** the smallest model with any candidate passing A1, A2, A3, A6,
  A7 and A9; among those, W1, then W3, then W2. If W2 or W3 wins only on tuning lines and not on validation, it is
  recorded as noun memorisation.

### The selection matrix (T072, W-2, 2026-10-07)

`make qualify TASK=attention PROFILE=ollama-gemma4-{e2b,e4b}-attention CANDIDATE=attention-candidate-w{1,2,3}.md
FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`, six runs in sequence. Only one chat model was loaded at a
time (e2b was stopped before the e4b runs). Each run made 294 calls. Every run printed `CANDIDATE` (exit 3), and no
Arabic character appeared in any output. Held-out and fresh were withheld (`NOT RUN`), as W-2 requires.

| Run | A1 tuning negatives opened | A2 | A3 validation (opened / missed of 19) | A6 violations answered asking | A7 | A8 p95 / median | A9 |
|---|---|---|---|---|---|---|---|
| e2b × W1 | FAIL 1: extra #15 | PASS 0 | FAIL: 1 (#29) / 2 (#4, #27) | FAIL 4: real #5; policy #13, #17, #40 | PASS 0 | 251 / 207 ms | PASS |
| e2b × W2 | FAIL 2: extra #15, #23 | PASS 0 | FAIL: 1 (#29) / 2 (#4, #27) | FAIL 5: real #5; policy #13, #17, #40, #45 | **FAIL 1**: real moderation #4 | 250 / 203 ms | PASS |
| e2b × W3 | FAIL 1: extra #15 | PASS 0 | FAIL: 1 (#29) / 2 (#4, #27) | FAIL 4: real #5; policy #13, #17, #40 | PASS 0 | 255 / 204 ms | PASS |
| e4b × W1 | FAIL 3: extra #13, #15, #16 | PASS 0 | PASS: 0 / 1 (#4) | PASS 1: policy #17 | PASS 0 | 414 / 329 ms | PASS |
| e4b × W2 | **FAIL 1: extra #15** | PASS 0 | PASS: 0 / 1 (#4) | PASS 1: policy #17 | PASS 0 | 418 / 333 ms | PASS |
| e4b × W3 | FAIL 3: extra #13, #15, #16 | PASS 0 | PASS: 0 / 1 (#4) | PASS 1: policy #17 | PASS 0 | 448 / 337 ms | PASS |

The reported lines:
- **R-discussion (validation).** e2b, all three: label asking answered discussion 1 (#27, the injection-shaped
  positive); label discussion answered asking 1 (#29); peer lines correct 12 of 13. e4b, all three: 0, 0, and
  13 of 13.
- **R-rule.** Validation #25 is rule-opened on every run (no peer line). No tuning negative is rule-opened.
- **R-ambiguous** (answered true): extra 10/12 on e2b, 9 (W1) or 8 (W2, W3) on e4b; original 4/9, 5/9 on
  e4b × W3; shipped 1/3; validation 2/2 everywhere.
- **R-burst.** e2b: 5/8; #6 and #7 (L-B1) open on member 1, and #8 (a greeting plus a peer discussion) opens on
  member 2. e4b: 6/8; #6 and #7 open on member 1, and #8 stays `none` (social, discussion). In #6 and #7 the
  model reads the first member alone as `asking`, so on these lines the remaining gap does not show: the burst is
  opened, which is what its human label (`needs_response` true) asks for.
- **Tuning lines common to every run:** extra #15 (a clear negative, `informing`) is answered `asking` by all three
  wordings on both models. It is the same line classify_v3's F1 and F2 failed on e4b (Q1, 010 research §2), and
  that 010's P2 did not.

**W-3 applied: no candidate passes.** A1 fails on all six runs; e2b also fails A3 and A6 on all three wordings.
- **The best candidate is e4b × W2.** It fails only A1, by one line (extra #15).
- **Noun-memorisation reading:** on validation the three wordings tie on e4b (0 opened, 1 missed, peer 13/13), and
  W2 wins only on tuning lines (extra #13 and #16, which W1 and W3 open). Under W-3's rule that reads as noun
  memorisation. But W1 and W2 also differ in non-noun wording: W2's Informing bullet carries the generic cues
  "(the time, day, place, deadline or where to find it)" and "even when it is about the course", and W2 has no
  Mixed sentence. So the cause is not isolated. The held-out set's new topics are the test of it.

### The one revision (T073, W-4, 2026-10-07)

**The operator's choice:** revise the best candidate, e4b × W2, toward P2. One sentence changes, the last of the
Informing bullet: "…not asking, even when it is about the course." becomes "…not asking, even when it is about a
session, test, recording, link, book, change or registration." It restores P2's noun scope on the Informing side,
as its Asking side already had (the same list, quoted by the classify_v3 plan §6 item 6). Every other byte is W2's.

| Candidate | File | SHA-256 | Characters |
|---|---|---|---|
| W2R, W2 revised | `attention-candidate-w2r.md` | `a55308ca8cd1b3371c607120d5a076db6956eb315bd6a1c0b065396ee578748a` | 3,183 |

Recorded here before it ran. It runs once on each model; then the freeze, or the stop (W-7).

**W2R measured (2026-10-07),** `--repeat 2`, 294 calls each, `CANDIDATE` (exit 3), no Arabic character in either
output:

| Run | A1 | A2 | A3 (opened / missed of 19) | A6 | A7 | A8 p95 / median | A9 |
|---|---|---|---|---|---|---|---|
| e2b × W2R | PASS 0 | PASS 0 | FAIL: 1 (#29) / 2 (#4, #27) | FAIL 5: real #5; policy #13, #17, #40, #45 | PASS 0 | 513 / 223 ms | PASS |
| **e4b × W2R** | **PASS 0** | **PASS 0** | **PASS: 0 / 1 (#4)** | **PASS 1: policy #17** | **PASS 0** | 495 / 346 ms | **PASS** |

- e4b × W2R reported lines: R-discussion 0 / 0, peer 13 of 13; R-rule validation #25; R-ambiguous extra 8/12,
  original 4/9, shipped 1/3, validation 2/2; R-burst 6/8 (#6, #7 open on member 1, as in every e4b run).
- The revision moved only extra #15 (now `informing` on both models). On e4b nothing else changed against W2:
  the same validation miss (#4), the same A6 line, the same bursts.

**W-3's decision:** the smallest model with a passing candidate is **e4b**: e2b passes with none, before or after
the revision. The only passing candidate is W2R. **Chosen pair: `ollama-gemma4-e4b-attention` + W2R**, frozen as
`attention_v1` (T074).
- **The noun-memorisation reading stands:** the frozen text names P2's course nouns on both the Asking and the
  Informing side, and its advantage over W1 and W3 was on tuning lines only. The held-out set, on plan §9's
  topics, is where that shows.
- **A development consequence, not a design input (plan §7):** the moderation profile in development is e2b, and
  the attention pair is e4b. Two models on the 16 GB development Mac means Ollama swaps models (Finding 13).
  Production picks per task on its own host.

### The freeze and the held-out set (T074–T075, 2026-10-07)

- **T074, the freeze, in one change:** `app/prompts/moderation/attention_v1.md` is W2R byte for byte
  (`a55308ca…578748a`); `ATTENTION_PROMPT_VERSIONS = ("attention_v1",)`; the pin is in
  `_PINNED_ATTENTION_SHA256`. The pin and config tests pass, and the config tests gained "the frozen version is
  accepted" and "the frozen allowlist refuses anything else". `attention_v1.md` is never edited from here on.
- **T075, written after the freeze and before any run of it:** `app/scripts/attention_heldout_fixtures.jsonl`,
  55 synthetic lines on plan §9's topics only (certificate, grades, homework submission, payment receipt, group
  link, exam hall, meeting app, timetable file), following 010 data-model §3's grid:
  - 10 rule-declined clear positives (4 requests, 4 unresolved problems, 2 detail-plus-tag confirmations), plus
    2 peer-addressed positives (one D2, one D5), 3 mixed, 1 relapse and 1 question behind a social opener, all
    rule-declined: **17 rule-declined clear positives** in all;
  - 4 positives the rules catch (sanity);
  - 8 informing with detail, 5 resolved, 3 passing on an announcement, 3 social comments on a past event, 2
    acknowledgements (excluded by E8 before the model);
  - 10 ambiguous bare declaratives (Policy S, `asking`), each with its detailed twin among the clear lines;
  - 3 D3 peer-discussion negatives, rule-declined.

  2 of 55 lines carry a question mark (4%); 27 lines are Saudi and 28 Egyptian phrasing. Every line was checked
  with `evaluate` and E8 while it was written; one informing line hit the `من` trap and was reworded.
  `test_attention_fixture_files.py` now holds the held-out minimums (10 rule-declined clear positives, ≤ 20%
  question marks, 3 peer discussions, 2 peer positives) and its peer lines' rule check.

### The held-out run, once (T076, 2026-10-07)

`make qualify TASK=attention PROFILE=ollama-gemma4-e4b-attention PROMPT=attention_v1
FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`, after rebuilding the tools image (it then carried
`attention_v1.md` at `a55308ca…578748a` and the 55-line held-out set). 392 calls; no Arabic character in the output.
**Result: `INCOMPLETE` (exit 2)**: every gate passes, and A5 is `NOT RUN` because `fresh-attention.jsonl` does not
exist yet (T077).

| Gate | Status | Counts |
|---|---|---|
| A1 | PASS | tuning clear negatives model-opened 0 |
| A2 | PASS | tuning clear positives missed 0 |
| A3 | PASS | validation: opened 0; missed 1 (#4) of 19 |
| **A4** | **PASS** | **held-out: opened 0 of 24 clear negatives; missed 0 of 17 rule-declined clear positives** |
| A5 | NOT RUN | no fresh sample |
| A6 | PASS | violation lines answered asking 1 (policy #17) |
| A7 | PASS | 0 differing lines over 2 runs |
| A8 | PASS | p95 515 ms, median 374 ms |
| A9 | PASS | 0 errors |

- **Held-out reported lines:** R-discussion 0 / 0, peer lines correct 5 of 5 (#11, #12, #53–#55); R-ambiguous
  answered true 4 of 10 (#47, #49, #51, #52), the other six answered `informing`; R-intent 42/49 (the six ambiguous
  lines and #40, a social comment answered `informing`); R-rule 0.
- **The tuning, validation, burst and A6 lines are the same as the W2R selection run on e4b,** line for line.
- **The noun-memorisation reading, tested:** on plan §9's topics, which the frozen text's nouns do not name (apart
  from Policy D's "certificates"), the pair opened no clear negative and missed no rule-declined positive. The
  held-out set does not show the memorisation the selection round's reading warned of. Its bare declaratives
  (Policy S) lean `informing` (4 of 10 true), as the tuning sets' do.
- **`attention_v1.md` was not edited after this run, and the held-out set was not edited after it either** (W-5,
  N5).
- **Next, the operator's (T077):** `fresh-attention.jsonl`, 20–30 real messages labelled with `intent` before any
  run; then the same command for `QUALIFIED`, and the moderation suite again beside T002 (SC-305). Until then
  `MODERATION_AI_ATTENTION_FROM` stays as it is: the opener needs `MODERATION_ATTENTION_PROMPT_VERSION`, which is
  blank (D-TG-199), and R1 allows it only on a `QUALIFIED` pair.

### Qualified, and the moderation suite beside T002 (T077, 2026-10-08)

The operator's runs. The gate counts below are as the operator reported them. The fresh sample's shape was then
checked by counts only, with no text printed.

**Attention: `QUALIFIED`.** `make qualify TASK=attention PROFILE=ollama-gemma4-e4b-attention PROMPT=attention_v1
FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`. A1–A9 all pass. A5: model-opened 1, missed 0.

The fresh sample (`fresh-attention.jsonl`, real messages labelled before the run):
- **Size:** the file holds 37 lines on 2026-10-08. The operator reported 30, and plan §9 asks for 20–30. This is
  still to be confirmed by the operator: which file the run read.
- **Labels:**
  - intents: `asking` 27, `informing` 6, `discussion` 2, `offering` 1, `social` 1;
  - 33 `clear` and 4 `ambiguous`; no `tracked` line;
  - `intent == "asking"` iff `needs_response` on every line;
  - 11 `peer` lines.
- **What reached the model:** rule set v1 opens 27 lines (S1 step 1, no call), including all 11 peer lines and
  both `discussion` lines. The other 10 reach the model:
  - 8 clear negatives;
  - 1 clear positive (#20);
  - 1 ambiguous positive (#10).
- **So A5 is:**
  - 1 of 8 rule-declined clear negatives model-opened, which is at its limit;
  - 0 of 1 rule-declined clear positive missed.

  The fresh sample says little about misses. The miss evidence is the held-out set's 0 of 17 (A4).

**Moderation: `QUALIFIED`, and SC-305 is satisfied.** `make qualify TASK=moderation
PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`. Q5–Q8,
Q11 and Q12 pass.

| | T002 (before, 2026-10-07) | T077 (after, 2026-10-08) |
|---|---|---|
| Real moderation (Q5) | FN 0 / FP 0 | FN 0 / FP 0 |
| Shipped moderation (Q6) | FN 0 / FP 0 | FN 0 / FP 0 |
| Policy (Q7) | FN 1 (#17) / FP 0; legitimate → incident 0 | FN 1 (#17) / FP 0; legitimate → incident 0 |
| Repeat (Q8) | 0 differing lines | 0 differing lines |
| Errors (Q11) | 0 | 0 |
| Tracked (Q12) | 1 (shipped #11), PASS | 2, both PASS |

- **Per-line status (`#N [OK|FN|FP]`, T002's definition) is identical.** The false-negative and false-positive lines
  are the same on every set, so every other line is OK both before and after.
- **The second tracked line is a label change, not an output change.** Real moderation #1 was given
  `tracked: no-link-rule` in T070. At T002 it was already OK: a category mismatch only, needing moderation on both
  sides.
- **Not compared:** the category-only mismatches T002 lists (real #1, shipped #12, policy #4, #22, #32, #54) and
  policy #4's `possible_violation/inconsistent` route. They are outside the OK/FN/FP status, and the operator's
  summary did not include them.
- **Q1–Q4, Q9 and Q10 are no longer in the moderation suite** (T062). T002's Q1 and Q3 failures on the attention
  lines have no counterpart here; their successor is the attention suite above.

**Next, the operator's:** development shadow (quickstart §6). Activate `ollama-gemma4-e4b-attention`, set
`MODERATION_ATTENTION_PROMPT_VERSION=attention_v1`, and recreate `ai-worker` and `ai-classifier`.
`MODERATION_AI_ATTENTION_FROM` stays blank until SC-306 is read.

**The fresh sample's history** *(2026-10-08, the operator's account)*. This note does not change the record above.
1. The T077 `QUALIFIED` run read `fresh-attention.jsonl` when it held **37** lines. Every T077 count above, A5
   included, belongs to that version. It is kept outside the fixtures directory, in
   `backup/fresh-attention-all-37-reviewed.jsonl`.
2. Afterwards, the operator cut the active `fresh-attention.jsonl` back to **30** lines, to meet plan §9's 20–30.
   No run has read the 30-line version on its own.
3. The 37-line evidence stands as historical evidence only. It is evidence for `attention_v1` under Policy D
   (2026-10-07).
4. Policy D is being amended (Policy D′; operator's option (a), 2026-10-08;
   `docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`). Neither version of this sample is reused as a fresh
   sample in the `attention_v2` cycle. Every model run has now seen it.

### The used fresh sample, relabelled under Policy D′ (T084–T085, 2026-10-09)

The operator relabelled T077's 37-line sample under D′ (T084) and saved it as `real-attention-fresh-v1.jsonl` in the
fixtures directory. T085 checked it by counts and line numbers; no text was written to any file or log.
- **The file:** 37 lines, with the same texts line for line as `backup/fresh-attention-all-37-reviewed.jsonl`, the
  sample T077 ran. Line numbers below are this file's.
- **The checks:**
  - It loads through `load_fixture_lines` (V1–V4).
  - Every line carries `text`, `needs_response`, `intent` and `label_class`, and there is no unknown key.
  - `intent == "asking"` iff `needs_response` holds on every line.
  - No line is `tracked`. The 11 `peer` lines are unchanged.
- **Labels:**
  - intents: `discussion` 23, `informing` 9, `asking` 3, `offering` 1, `social` 1;
  - label classes: 32 `clear`, 5 `ambiguous`.
- **What changed since T077:** 24 lines went from `asking` to non-`asking` (21 `discussion`, 3 `informing`). #36
  also went from `clear` to `ambiguous`. The changed lines include:
  - all of the operator's eight examples (30-line #2, #3, #9, #10, #14, #21, #28 and #30 are lines #2, #3, #10,
    #11, #18, #28, #35 and #37 here);
  - every line the addendum's §4 listed;
  - 6 of the 7 lines that are only in the 37-line version.
- **Still `asking`:**
  - #14: the course platform's own certificate (rule-opened);
  - #20: whether the course runs live or recorded (rule-declined, clear);
  - #30: the content of the exam the course prepares for (D6, ambiguous, rule-opened).

  All three are consistent with D′, so no label is disputed (FR-332).
- **The rules:** 27 lines open by rule, as before. 10 are rule-declined:
  - 8 clear negatives: #5, #8, #17, #22, #29, #31, #33, #34;
  - 1 clear positive: #20;
  - 1 ambiguous `informing` line: #10.
- **What it means for the gates:** as tuning, the file adds A1 = 0 over those 8 negatives and A2 = 0 over #20.
  None of the 8 changed label, and they are the 8 that T077's A5 counted, where `attention_v1` opened one. A v2
  candidate must not open it.
- **Where each set now lands:**
  - Set discovery reads `real-attention-extra.jsonl`, `real-attention-fresh-v1.jsonl`, `real-attention.jsonl` and
    `attention_smoke_fixtures.jsonl` as tuning.
  - There is no `fresh-attention.jsonl` in the fixtures directory: the 30-line file is in `backup/`, outside the
    sets the suite reads. So A5 is `NOT RUN` until T095.
  - The two original real tuning sets are unchanged (file dates 2026-10-07), as the operator confirmed.

### The first cycle's held-out set as validation, and A3 per set (T086, 2026-10-09)

No model was run. Tests were written first and failed (8), then passed.
- **The rename:** `app/scripts/attention_heldout_fixtures.jsonl` became `attention_heldout_v1_fixtures.jsonl`, by a
  plain `mv` (Git stays the operator's). Its SHA-256 is the same before and after:
  `0178e64e09b99f4f1c017aaa92b7bc6b867a1ab17089a042d21016bf261ae820` (55 lines, 8,355 bytes). It is pinned in
  `test_attention_fixture_files.py`. The file is also checked to load, to carry every key, and to have
  rule-declined peer lines.
- **Discovery** (`qualification/attention.py`, `VALIDATION_SETS`): three validation sets, in reading order:
  - `attention_validation_fixtures.jsonl`;
  - `attention_validation_scope_fixtures.jsonl`, missing until T087;
  - `attention_heldout_v1_fixtures.jsonl`.

  All three are read in candidate mode too; only the held-out and fresh sets are withheld. The held-out role
  (`attention_heldout_fixtures.jsonl`) is now missing until T093.
- **A3 per set** (`_per_set_gate`):
  - it passes when every validation set has at most 1 clear negative model-opened and at most 1 rule-declined
    clear positive missed;
  - it fails on any set that ran and failed, even while another is missing;
  - it is `NOT RUN` while a set is missing and none failed.

  Its detail lists every set's counts in reading order, separated by ` | `, each as `<set>: model-opened N (#…);
  missed N (#…) of M`, or `<set>: NOT RUN (missing)`. A4 and A5 are unchanged and still read their role's sets
  together.
- **On the real fixtures directory today:**
  - tuning: `real-attention-extra`, `real-attention-fresh-v1`, `real-attention`, `attention_smoke`;
  - validation: the scope set missing;
  - held-out and fresh: missing (withheld in candidate mode).

  So a run now would report A3, A4 and A5 `NOT RUN`.
- **The checks:**
  - ruff and mypy (94 files) are green;
  - pytest: 1273 passed and 9 skipped, with the secret scan deselected. The new held-out set's tests skip until
    T093;
  - the secret scan flags only the known baseline line.

### The scope validation set (T087, 2026-10-09)

`app/scripts/attention_validation_scope_fixtures.jsonl`, 18 synthetic lines (SHA-256 `7d284147…40d8ce`). It was
written before any v2 candidate exists, and no model was run.
- **Every line:** carries `text`, `needs_response`, `intent` and `label_class`; is rule-declined (`evaluate`);
  passes eligibility (`attention_exclusion`, E8 included); has no question mark; and uses Saudi or Egyptian
  phrasing.

| Lines | What they are | Label |
|---|---|---|
| #1–#4 (peer), #5 | outside-institution questions: Jadarah, scholarships, university placement, unified admission | clear `discussion` (D3) |
| #6–#8 | outside-institution statements and complaints, including an outside site that will not load | clear `informing` (Policy S's scope) |
| #9, #12, #13; #10, #11 (peer) | the course's own registration, mock-test results, lecture time and platform. They share surface words with #3 and #5–#7: results, registration, "I'd like to know", a page that will not load | clear `asking` (D2, D5) |
| #14 | the course's own registration, resolved | clear `informing` |
| #15, #16 (peer) | unclear whose registration or results | `asking`, ambiguous (D7) |
| #17, #18 | the content of the exam the course prepares for | `asking`, ambiguous (D0, D6) |

The addendum's minimums are met: 8 outside-institution negatives (≥ 6), 5 own-service positives (≥ 4) with 2
peer-addressed (≥ 2), and 4 ambiguous lines (≥ 3).
- **No v2 held-out topic word** is in it, nor in any other in-repo validation or tuning file.
- **No institution the real tuning sets name** is in it: Qiyas, university, licence, master's.
- **The tests** (`test_attention_fixture_files.py`):
  - the scope set's size and minimums;
  - every scope line reaches the model;
  - no clear `asking` line names an outside institution;
  - the set stays off the tuning institutions;
  - the v2 held-out words are absent from every in-repo validation and tuning file;
  - the scope set loads, carries every key, and its peer lines are rule-declined.

  Each new test was shown to fail on a deliberately broken copy of the set. The fixture was written before its
  tests, so they did not fail first.
- **Set discovery** now reads all three validation sets, in candidate mode too.
- **The checks:**
  - ruff and mypy (94 files) are green;
  - pytest: 1284 passed and 9 skipped, with the secret scan deselected. The 6 tests for the new held-out set
    skip until T093;
  - the secret scan flags only the known baseline line.

### The check suite before any v2 candidate (T088, 2026-10-09)

`make check` was run after T083–T087, with no model call.
- **Ollama was left running.** As in T001, the operator's app was not quit. No automated test calls a model:
  every test uses a scripted gateway.
- **The outcome is the same as T001's baseline:**
  - ruff is green;
  - the architecture check and domain-boundary checks 1–4 are OK;
  - mypy is green (94 files);
  - pytest: 1285 passed, 9 skipped, 2 deselected, and **4 failed, all in `tests/moderation/test_secret_scan.py`**.
    These are the known failures (T001; 010 research §2), not fixed here.
- **The skips:** the 6 tests for the new held-out set skip until it is written after the `attention_v2` freeze
  (T093).
- **The last three steps, run by hand.** `make check` stops at pytest, so `check.sh`'s remaining steps were run
  as it would run them:
  - the test schema (`injaz_ai_test`) was restored to head;
  - PHP Feature: OK, 139 tests, 675 assertions;
  - the secret scan flags only the known line, `test_metrics_model_opened.py:150` (`by_key = …`).
- **SC-310 holds:**
  - the pins of `classify_v1`, `classify_v2` and `attention_v1` pass (`test_prompt_pinned.py`);
  - the first cycle's held-out set is byte-identical (`test_attention_fixture_files.py`);
  - every earlier suite keeps its outcome.

### The three v2 candidates, fixed before any run (T089, W-1′, 2026-10-09)

The candidates were written to the fixtures directory and are recorded here **before any v2 run**.
- **The base:** each is `attention_v1.md`'s bytes with only the policy-bound sentences replaced, word for word as
  contract §5′ and §4 S3 give them:
  - the `asking`, `discussion` and `informing` definitions;
  - the Asking paragraph's scope ("about the course's own service", "with it", "the course's own session, …");
  - the policy list, D0 to D7. D1 to D7 replace v1's seven lines.
- **What stays the same:** everything else is byte-identical to `attention_v1`, including W2R's Informing nouns,
  the injection guard and the output line.
- **What no candidate names:** Qiyas, a specific university, a licence, or any institution or topic word of the
  addendum's §6.2 or §6.6 lists.

| Candidate | D0's place | SHA-256 | Characters |
|---|---|---|---|
| `attention-candidate-v2-a.md`, V2-A, in place | first item of the "Questions between members" list | `47ed062576c1d5877b05b908f3202305c75e00f443d8d5f694c9e256cfa96e5b` | 4,320 |
| `attention-candidate-v2-b.md`, V2-B, scope first | its own paragraph, right after "The question: …" | `f0d492fcfba2a1dd90f77dab822c6443937e64c944044ecfbfbdc371d980fa53` | 4,319 |
| `attention-candidate-v2-c.md`, V2-C | V2-B, plus "The same kind of question can be either: what decides is whose service it is." | `6aae28777cd8d5b3697587d83bb7ccb5a305b98f8029f109c0100fe50fe296e6` | 4,397 |

The decision rule (W-3′) was fixed in the addendum before this:
- take the smallest model with any candidate passing A1, A2, A3 (every validation set), A6, A7 and A9;
- among those, prefer V2-A, then V2-B, then V2-C.

### The v2 selection matrix (T090, W-2′, 2026-10-09)

Six candidate-mode runs, `--repeat 2`, after the tools image was rebuilt with T086–T087.
- **The size:** 448 calls per run.
- **No text in the output:** no Arabic character in any report line.
- **Every run's verdict:** `CANDIDATE` (exit 2 from `make`, i.e. the script's 3).

The three validation sets are listed in the order *base* (`attention_validation_fixtures.jsonl`, 19 rule-declined
clear positives), *scope* (5) and *v1 held-out* (17). Each cell is "model-opened / missed".

| Pair | A1 tuning negatives opened | A2 | A3 base | A3 scope | A3 v1 held-out | A6 | A7, A9 | p95 / median |
|---|---|---|---|---|---|---|---|---|
| e2b × V2-A | **5** (extra #15, #23; fresh-v1 #8, #17, #33) | 0 | 0 / **2** (#4, #27) | **6** (#2, #3, #5, #6, #7, #8) / 0 | **3** (#30, #33, #53) / 1 (#11) | **6** | 0, 0 | 284 / 221 ms |
| e2b × V2-B | **5** (extra #15, #16; fresh-v1 #8, #17, #33) | 0 | **2** (#19, #26) / **2** (#4, #27) | **5** (#2, #3, #5, #6, #7) / 0 | **3** / 1 (#11) | **4** | 0, 0 | 250 / 210 ms |
| e2b × V2-C | **4** (extra #17; fresh-v1 #8, #17, #33) | 0 | **2** (#19, #26) / **2** (#4, #27) | **6** / 0 | **3** / 1 (#11) | **4** | 0, 0 | 270 / 214 ms |
| e4b × V2-A | **1** (extra #15) | 0 | 0 / **2** (#4, #27) | **2** (#5, #7) / 0 | 0 / 0 | 1 (#17) | 0, 0 | 510 / 342 ms |
| e4b × V2-B | **1** (extra #15) | 0 | 0 / **2** (#4, #27) | **2** (#5, #7) / 0 | 1 (#53) / 0 | 1 (#17) | 0, 0 | 413 / 335 ms |
| e4b × V2-C | **1** (extra #15) | 0 | 0 / **3** (#4, #27, #38) | **2** (#5, #7) / 0 | 0 / 0 | 1 (#17) | 0, 0 | 429 / 338 ms |

- **R-burst:** 5/8 on e2b and 6/8 on e4b, as in the first cycle. **R-discussion on the scope set (e4b × V2-A):**
  - label `asking` answered `discussion`: #17, the ambiguous exam-content line;
  - label `discussion` answered `asking`: #5;
  - peer lines correct: 7 of 7.
- **W-3′: no candidate passes on either model.** e4b × V2-A is the closest. It fails A1 on one line and A3 on two
  sets, and passes A2, A6, A7, A8 and A9 and the v1 held-out set (0 / 0).
- **e4b × V2-A against `attention_v1` (W2R, e4b) on the lines they share:**
  - **Regressions:**
    - real-attention-extra #15 (a registration statement that gives its deadline, `informing`) is now answered
      `asking`;
    - validation #27 (an injection-shaped line telling the model to answer `discussion`, about a locked
      account, `asking`) is now answered `discussion`.
  - **Persistent:** validation #4 (an absence excuse) is answered `informing`, as under v1.
  - **The new boundary:** scope #1–#4, #6 and #8 are right, and #5 (an unaddressed question about an outside
    programme's documents) and #7 (a complaint about an outside site) are answered `asking`.
  - **The real sample:** no clear negative in `real-attention-fresh-v1.jsonl` is opened on e4b. That includes the
    line `attention_v1` opened at T077.

### The one revision (T091, W-4′, 2026-10-09)

The operator chose to spend the one revision, on the closest pair's candidate, V2-A, and approved the sentence.
- **The sentence:** the Informing paragraph's last sentence, which is not a policy sentence. It is the sentence
  the first cycle's revision used for the same tuning line, real-attention-extra #15.
- **Before:** "Telling the group something is not asking, even when it is about a session, test, recording,
  link, book, change or registration."
- **After:** "…, link, book, change or registration, **and even when it does not say whose it is.**"
- **What it targets:** A1's one line, #15, a registration statement giving its deadline. D7's new "unclear whose"
  clause probably drew it to `asking`.
- **What it was not expected to fix:** base validation #4 and #27, and scope #5.
- **The result:** `attention-candidate-v2-ar.md`, V2-AR, SHA-256
  `fbe98d5fc9edc8ace1fea6793498af99d856a986421487ff11c4a24c926c2280`, 4,363 characters. Its diff from V2-A is that
  one sentence. It was recorded here **before its runs**, and is run on both models (W-4′).
- **If it still fails, the cycle stops (W-7′).**

### V2-AR measured, and the second cycle stopped (T091, W-7′, 2026-10-09)

| Pair | A1 | A2 | A3 base | A3 scope | A3 v1 held-out | A6 | A7, A9 | p95 / median |
|---|---|---|---|---|---|---|---|---|
| e2b × V2-AR | **5** (extra #15, #23; fresh-v1 #8, #17, #33) | 0 | **1** (#29) / **2** (#4, #27) | **7** (#1, #2, #3, #5, #6, #7, #8) / 0 | **4** (#30, #33, #53, #54) / 1 (#11) | **6** | 0, 0 | 249 / 204 ms |
| e4b × V2-AR | **1** (extra #15) | 0 | 0 / **2** (#4, #27) | **2** (#5, #7) / 0 | 0 / 0 | 1 (#17) | 0, 0 | 422 / 332 ms |

- **On e4b the revision changed no gated line.** Every gated answer is V2-A's, line for line. The one difference
  is v1 held-out #45, an ambiguous line, reported only, which is now `asking`. Real-attention-extra #15 is still
  answered `asking`. So the cause is not the Informing sentence: it is most likely in the policy-bound sentences
  (D7's new "unclear whose" clause, or the Asking paragraph's new scope), which W-4′ may not revise.
- **W-7′: the second cycle stops.** No candidate passes W-3′ after the one revision. There are no further rounds.
  - **`attention_v2` is not created.** No file, pin or allowlist entry exists, and `ATTENTION_PROMPT_VERSIONS`
    stays `("attention_v1",)`.
  - **The held-out set v2 is not written.** T093 and T094 are skipped, and T095 lapses. The held-out topics of
    addendum §6.6 stay fixed and unseen.
  - **`attention_v1` stays frozen history.** It is qualified under Policy D (2026-10-07), not under D′, so R1
    bars it from opening.
  - **Opening stays rules-only.** `MODERATION_AI_ATTENTION_FROM` is blank in development, and the opener needs it
    (D-TG-199).
  - **Shadow may be running on `attention_v1`.** Development's `.env` has
    `MODERATION_ATTENTION_PROMPT_VERSION=attention_v1`, so `attention_v1` shadow judgements may be recording.
    Those rows keep their version, are historical, and open nothing. Whether to blank the setting is the
    operator's call.
    - *(2026-10-09, later)* The operator blanked it in `.env`. The running `ai-worker` and `ai-classifier` still
      carried `attention_v1` until they were recreated (quickstart §8: blank the setting, then recreate). Both were
      recreated the same day, and both now see `MODERATION_ATTENTION_PROMPT_VERSION` and
      `MODERATION_AI_ATTENTION_FROM` blank. No attention call is made, and no new judgement is recorded.
  - **The candidate files stay in the fixtures directory, outside the repository.** They are the record of this
    round, with their hashes above.
- **What the evidence says, for any later decision:**
  - **e4b learns most of D′.**
    - 6 of the scope set's 8 outside-institution negatives are right, and every peer line in all three
      validation sets is right.
    - The v1 held-out set is 0 / 0, and A6 allows 1.
    - Under every V2 candidate, none of the real sample's rule-declined clear negatives was opened. That includes
      the one `attention_v1` opened at T077.
  - **What blocks it is five lines:**
    - two regressions against `attention_v1`: extra #15, a registration statement giving its deadline; and
      validation #27, where the model now obeys the line's "answer discussion" instruction about a locked
      account;
    - one persistent miss: validation #4, an absence excuse;
    - two new-boundary errors: scope #5, an unaddressed question about an outside programme, and scope #7, a
      complaint about an outside site.
  - **e2b** is far from passing, as in the first cycle (A1 4–5, A6 4–6).

### Phase 10 and the final check (T078–T082, 2026-10-09)

- **T078: dated "Amended by TG-M5.3" notes,** keeping the history:
  - 008: `classification-pipeline.md` (header, R13, F6, N1) and `data-model.md` (header, §1's role, §5's second
    link);
  - 006: `data-model.md` (the revision reservation; `attention_judgement_id`, `ck_attention_ai_link`);
  - 009: `attention-opening.md` (header; §1–§3 superseded, O2′ and O3's link, I1's caller; §9's L-B1 and "the
    attention model down") and `quickstart.md` (both settings needed; rollback);
  - 010: `qualification.md` (superseded by version 2; the alias is kept).

  T012's wording notes were already in place.
- **T079:** the moderation plan's revision row and "Alembic numbering" paragraph. TG-M5.3 took `0008`, and later
  moderation revisions take the next free numbers.
- **T080:** the operator runbook §C gains a TG-M5.3 row covering policy, labels, fresh sample, `make qualify`,
  shadow, switch and pilot, and the 2026-10-09 stop. The TG-M5.1 row is marked superseded.
- **T082: `make check`, after Phase 10,** with Ollama left running; no test calls a model. The outcome is
  T001's baseline:
  - ruff is green;
  - the architecture check and checks 1–4 are OK, including check 4 (no text in logs) and the import
    boundaries;
  - mypy is green (94 files);
  - pytest: 1285 passed, 9 skipped, 2 deselected, and the 4 known `test_secret_scan.py` failures;
  - by hand: the test schema was restored, PHP Feature is OK (139 tests, 675 assertions), and the secret scan
    flags only the known `test_metrics_model_opened.py:150` line;
  - `test_prompt_pinned.py` passes (6): the hashes of `classify_v1`, `classify_v2` and `attention_v1` are
    unchanged (SC-310).

**TG-M5.3's outcome:**
- **Story 1 is complete and deployable:** the "Member discussion" dismissal, the per-reason breakdowns, and
  "dismissed (any reason)".
- **The attention judgement is complete and switched off:** revision `0008`, the `attention` role, shadow
  dispatch, opening from the judgement with V, qualification version 2, and the C10a–c figures.
- **`attention_v1`** was frozen and qualified under Policy D (2026-10-07). Under Policy D′ (2026-10-09) no
  instruction is qualified, because the second cycle stopped (W-7′).
- **Today:** AI-assisted opening is off, and the rules alone open question items. Both attention settings are
  blank in development, and the services were recreated.
