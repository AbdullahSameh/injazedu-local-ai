# Tasks: TG-M5.3 — A Separate Attention Judgement

**Input**: `specs/011-tg-m5-3-attention-judgement/` (plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md)

**Tests**: these are required by the plan's Constitution Check §1 and are written first. Each must fail before its
implementation exists.
- Every automated test is scripted: no model runtime, credential or network.
- Database tests use `injaz_ai_test` only.
- PHP tests use `DatabaseTransactions`, never `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh`.

**Git**: none by the agent (constitution IV). Tasks marked *(operator)* are the operator's.

**Text**: never print, log or commit real message text. Synthetic fixtures in the repository are the only Arabic
text written. Qualification output carries counts and line numbers only.

**Running tests:**
- Python: `cd apps/ai-api && uv run pytest <path>`.
- PHP: `cd apps/ai-control && vendor/bin/phpunit --testsuite=Feature --filter <Test>`.
- Everything: `make check` (with Ollama quit for the final run).

**Story order** (plan "Implementation order"):
- **US1 ships first and alone.** It needs no schema, no model and no switch.
- **The other stories depend on Phase 3** (Foundational).
- **US6 (selection and freeze) runs last.** It needs the attention suite (US5) and the fixtures (US4, US7).

---

## Phase 1: Setup

- [X] T001 Run `make check` with Ollama quit and record the result in
  `specs/011-tg-m5-3-attention-judgement/research.md` §2 under "Baseline before any change". It is the baseline
  for SC-310.
  - The 4 pre-existing `test_secret_scan.py` failures are known (010 research §2) and must not be "fixed" here.
- [X] T002 Run the moderation qualification once on the development pair, **before any code change**:
  `make qualify-moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`.
  - Record the gate table and every line's status (`#N [OK|FN|FP]`, no text) in research §2 under "Moderation
    baseline". This is SC-305's "before".
  - It needs Ollama running. *(operator may run it, or the agent with the operator's go-ahead)*

---

## Phase 2: User Story 1 — Member discussion, and figures that say why (Priority: P1) 🎯 MVP

**Goal**: implement `contracts/dismissal-reasons.md` K1–K12: a "Member discussion" dismissal, per-reason
breakdowns beside unchanged dismissal counts, and "dismissed (any reason)" wording. **No dependency on Phase 3.**

**Independent Test**: on a fixed scenario with dismissals of every reason:
- every existing dismissal count has the same value as before;
- each breakdown sums to its count;
- the page never says "dismissed as not a real question".

### Tests for User Story 1

- [X] T003 [P] [US1] Extend `apps/ai-control/tests/Feature/AttentionDismissTest.php`:
  - `test_dismissing_member_discussion_records_that_reason`: status `dismissed`, `close_reason =
    'member_discussion'`, `closed_by_user_id` is the actor, `closed_at` is set, and the item leaves the open table;
  - `test_a_second_dismissal_after_member_discussion_changes_nothing`: the first reason, account and moment are
    kept;
  - a test that the action's confirmation text contains all three meanings (K2).
- [X] T004 [P] [US1] In `apps/ai-control/tests/Feature/ModelViewDisplayTest.php` (near line 207), add
  `->assertTableActionExists('dismiss_member_discussion')` beside the two existing assertions.
- [X] T005 [P] [US1] Create `apps/ai-control/tests/Feature/DismissalBreakdownTest.php` (`DatabaseTransactions`). It
  builds one hand-computed scenario:
  - **Rule items:** dismissed as `not_a_question`, `member_discussion`, `message_removed`, operator free text
    (`"spam bot"`) and `NULL`, plus one answered.
  - **TG-M5.1 model items** (`source='ai'` with `message_classification_id`): dismissed as `member_discussion` and
    `message_removed`, plus one open.

  It asserts:
  - `ruleBaseline()`: `rule_opened` and `rule_dismissed` keep their pre-change values, the four breakdown keys are
    exact, their sum equals `rule_dismissed`, and precision is unchanged;
  - `blocks()[…]['model_questions']`: `dismissed` is unchanged, the four breakdown keys are exact, and they sum to
    it;
  - the HTML contains "Rule-dismissed (any reason)" and "Model-opened, dismissed (any reason): 2 / 3";
  - the breakdown line reads "not a real question 0 · member discussion 1 · message removed 1 · other 0";
  - the HTML contains no "dismissed as not a real question" and no `%`.
- [X] T006 [P] [US1] Update `apps/ai-control/tests/Feature/ModelOpenedQuestionsTest.php` (lines 124–132):
  - the expected `model_questions` array gains `dismissed_not_a_question`, `dismissed_member_discussion`,
    `dismissed_message_removed` and `dismissed_other` (dismissal reason of the fixture item: set it explicitly to
    `not_a_question`);
  - the sentence assertion becomes `dismissed (any reason): 1 / 3`;
  - add `assertStringNotContainsString('dismissed as not a real question', $html)`.
- [X] T007 [P] [US1] Add the breakdown to the Python figure tests, keeping every existing assertion unchanged:
  - `apps/ai-api/tests/moderation/classification/test_metrics_model_opened.py`: run C9 with the four columns of
    `dismissal-reasons.md` §3 (with `ai.` prefixes), and assert the hand-computed values and that they sum to
    `model_dismissed`;
  - `apps/ai-api/tests/moderation/classification/test_metrics.py`, the C7 block (lines 367–378): add the four
    columns (`source = 'rule'` filters), set the scenario's dismissed rule item's `close_reason` explicitly, and
    assert the parts sum to `rule_dismissed`;
  - `apps/ai-api/tests/moderation/attention/test_accuracy.py` (TG-M3 §5's statement, line 25): add the same
    columns, and assert the sum and that precision is unchanged.

### Implementation for User Story 1

- [X] T008 [US1] In `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`, add
  `Action::make('dismiss_member_discussion')`:
  - label "Member discussion", `Heroicon::OutlinedChatBubbleLeftRight`, gray, `requiresConfirmation()`;
  - `->action(fn (AttentionItem $record) => self::dismiss($record, 'member_discussion'))`, placed between the two
    existing dismiss actions;
  - give all three dismiss actions the same `modalDescription()`, stating the three meanings of K2 in English.

  Update the class docblock ("two dismiss row actions" becomes three). This makes T003 and T004 pass.
- [X] T009 [US1] In `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php`, add the four breakdown
  columns verbatim from `contracts/dismissal-reasons.md` §3:
  - `classificationRuleBaseline()`: each filter also has `source = 'rule'`;
  - `classificationModelOpenedQuestions()`: `ai.status` and `ai.close_reason`.

  Existing columns and grouping stay unchanged. Update the docblocks to cite K7 and K8.
- [X] T010 [US1] In `apps/ai-control/app/Filament/Pages/ClassificationAccuracy.php`, carry the four keys:
  - in `ruleBaseline()` rows;
  - in each block's `model_questions` array: `dismissed_not_a_question`, `dismissed_member_discussion`,
    `dismissed_message_removed` and `dismissed_other`, cast to int.

  No arithmetic is computed in PHP beyond reading the columns.
- [X] T011 [US1] Update `apps/ai-control/resources/views/filament/pages/classification-accuracy.blade.php`:
  - the "Rule-dismissed" header becomes "Rule-dismissed (any reason)";
  - under the baseline table, one line per row: "not a real question a · member discussion b · message removed c ·
    other d";
  - line 145 becomes "Model-opened, dismissed (any reason): n / N", followed by the same breakdown line (counts,
    never ratios);
  - the comment at line 141 cites K10.

  This makes T005–T006 pass.
- [X] T012 [P] [US1] Write the dated "Amended by TG-M5.3 (2026-10-…)" notes listed in
  `contracts/dismissal-reasons.md` §5, keeping the history:
  - `specs/006-tg-m3-response-tracking/spec.md` (FR-051);
  - `specs/006-tg-m3-response-tracking/data-model.md` (`close_reason` row);
  - `specs/006-tg-m3-response-tracking/contracts/control-panel-attention.md` §2;
  - `specs/006-tg-m3-response-tracking/contracts/attention-metrics.md` (§3 M10, §5);
  - `specs/008-tg-m5-ai-classification/contracts/classification-metrics.md` (C7, §8a);
  - `specs/008-tg-m5-ai-classification/contracts/control-panel-classification.md` §4;
  - `specs/009-tg-m5-1-ai-attention/quickstart.md` §5.
- [X] T013 [US1] Run the PHP Feature suite and the Python metric tests. Confirm every pre-existing dismissal figure
  value is unchanged (SC-301).

**Checkpoint**: Story 1 is complete and deployable alone (quickstart §1).

---

## Phase 3: Foundational (blocks US2–US7; not US1)

**Purpose**: revision `0008`, the role, the setting and the pure domain module, which every attention story
needs.

- [X] T014 Create `apps/ai-api/tests/moderation/attention_judgement/__init__.py` and `conftest.py`.
  - The conftest re-exports the classification fixtures it needs, by explicit import from
    `tests.moderation.classification.conftest`: `classification_session_factory`, `insert_chat`, `insert_user`,
    `insert_message`, `insert_prediction`, `insert_attention_item`, `fetch_attention_item`,
    `classification_redis`, `scripted_gateway`, `classification_settings`, `insert_moderator` and
    `insert_assignment`.
  - It adds `insert_attention_judgement(…, intent, path='live', created_at=None, model_profile_id=None)`, which
    derives `needs_response` by calling `needs_response_for`, never a literal.
  - It adds `insert_attention_attempt(…)` and `seeded_attention_profile` (an inactive or active `role='attention'`
    fake profile, mirroring `classification_seeded_profile`).

### Tests for Foundational

- [X] T015 [P] Create `apps/ai-api/tests/moderation/attention_judgement/test_migration_0008.py`, modelled on
  `tests/moderation/classification/test_migration_0007.py`. Each planted violation runs inside `BEGIN … ROLLBACK`
  on `injaz_ai_test` and is rejected by the constraint named in data-model §1–§4:
  - an unknown `intent`;
  - `path = 'x'`;
  - a second current judgement for one message;
  - a second exclusion for one message;
  - a `failed` attempt without a profile, and an `excluded` attempt with one;
  - an unknown exclusion or failure reason, and `confidence_out_of_range` as a failure reason;
  - an `ai` item with no link, and an `ai` item with both links;
  - a `rule` item with `attention_judgement_id`, and an `operator` item with `message_classification_id`;
  - a second active `attention` profile.

  These must be accepted: `role = 'attention'`; `rule_opens` as an exclusion. Finally, the downgrade drops
  exactly what the upgrade added, with no attention rows present.
- [X] T016 [P] Create `apps/ai-api/tests/moderation/attention_judgement/test_domain.py`, pure, with named cases and
  no computed expectations:
  - `INTENTS` is exactly the six of data-model §9;
  - `needs_response_for` is true only for `asking`, parametrised over all six;
  - `attention_exclusion` returns each E1–E8 reason through `MessageFacts` (one case each, in E1–E8 order);
  - `attention_exclusion` returns `"rule_opens"` for `normalize("متى موعد الاختبار؟")` and for
    `normalize("بس الرابط مش شغال")`, and `None` for `normalize("حد خلص الواجب")`;
  - `"شكرا"` is `acknowledgement`, not `rule_opens`: E8 precedes AE2;
  - `judgement_proposes` is true only for `("live", True)`;
  - `vetoed` is true for `SPAM_OR_AD` and `ABUSE` only, over all seven categories.
- [X] T017 [P] Create `apps/ai-api/tests/moderation/attention_judgement/test_config_attention.py`:
  - unset or blank `MODERATION_ATTENTION_PROMPT_VERSION` gives `None`;
  - a non-empty value outside `ATTENTION_PROMPT_VERSIONS` exits naming the variable, with no stack trace, the same
    pattern as `test_config_classification.py`;
  - with `ATTENTION_PROMPT_VERSIONS` monkeypatched to `("attention_test",)`, `"attention_test"` is accepted.
- [X] T018 [P] Generalise `apps/ai-api/tests/moderation/classification/test_prompt_pinned.py` (D-TG-189):
  - add `_PINNED_ATTENTION_SHA256: dict[str, str] = {}`;
  - `test_selectable_versions_files_and_pins_are_one_set` asserts each `*.md` stem is in exactly one of
    `PROMPT_VERSIONS` / `ATTENTION_PROMPT_VERSIONS`;
  - `set(PROMPT_VERSIONS) == set(_PINNED_SHA256)` and `set(ATTENTION_PROMPT_VERSIONS) ==
    set(_PINNED_ATTENTION_SHA256)`;
  - a parametrised hash test for attention pins, empty for now;
  - the G4 test stays on `_PINNED_SHA256` only;
  - update the docstring.

### Implementation for Foundational

- [X] T019 Create `apps/ai-api/alembic/versions/0008_moderation_attention_judgement.py` (revision `"0008"`,
  down_revision `"0007"`):
  - **upgrade:** exactly data-model §1–§4;
  - **downgrade:** exactly §6;
  - **docstring:** in 0007's style, citing D-TG-184, D-TG-190, D-TG-192 and Finding 19, with no `GRANT` and no
    view.

  This makes T015 pass after T020.
- [X] T020 [P] Add the ORM metadata:
  - `apps/ai-api/app/infrastructure/models_moderation.py`: the `message_attention_judgements` and
    `message_attention_attempts` tables, and `attention_judgement_id` plus `ck_attention_ai_link` on
    `attention_items`, all mirroring the migration;
  - `apps/ai-api/app/infrastructure/models.py`: `ck_model_profiles_role` with `'attention'`.
- [X] T021 [P] Add `"attention"` to `Role` and `GenerationRole` in `apps/ai-api/app/domain/model_profile.py`, and
  update the comment.
- [X] T022 [P] Create `apps/ai-api/app/domain/moderation/attention_judgement.py`.
  - **It is pure:** stdlib plus `app.domain.moderation.attention.evaluate` and
    `app.domain.moderation.classification.{MessageFacts, eligibility}`.
  - **It holds:** `INTENTS`, `needs_response_for`, `attention_exclusion(facts)` (it uses `facts.text`, already
    normalised by `load_facts`), `judgement_proposes` and `vetoed`.
  - **Its docstring** states the single-derivation rule (S2).

  This makes T016 pass.
- [X] T023 [P] In `apps/ai-api/app/infrastructure/config.py`:
  - add `ATTENTION_PROMPT_VERSIONS: tuple[str, ...] = ()` and `moderation_attention_prompt_version: str | None`
    (alias `MODERATION_ATTENTION_PROMPT_VERSION`, default `None`);
  - add the field name to `_empty_classification_setting_is_default`'s list;
  - add an `after` validator refusing a value outside `ATTENTION_PROMPT_VERSIONS` with a message naming the
    variable;
  - export `ATTENTION_PROMPT_VERSIONS` for `test_prompt_pinned.py`.

  This makes T017 and T018 pass.
- [X] T024 [P] Add `ollama-gemma4-e2b-attention` (`gemma4:e2b-it-qat`) and `ollama-gemma4-e4b-attention`
  (`gemma4:e4b-it-qat`) to `apps/ai-api/app/scripts/seed_profiles.py`.
  - Both use `role="attention"` and `is_active=False`, with the moderation params (data-model §4).
  - Add a comment citing D-TG-190.
- [X] T025 [P] Add `'attention' => 'attention'` to the role options in
  `apps/ai-control/app/Filament/Resources/ModelProfiles/Schemas/ModelProfileForm.php` (line 25) and
  `apps/ai-control/app/Filament/Resources/ModelProfiles/Tables/ModelProfilesTable.php` (line 29).
- [X] T026 Run `uv run pytest tests/moderation` and confirm:
  - the new foundational tests pass;
  - every existing suite is green;
  - the schema reaches `0008` on `injaz_ai_test`.

**Checkpoint**: the schema, role, setting and domain exist. Nothing calls a model yet.

---

## Phase 4: User Story 2 — Every eligible message gets its own judgement (Priority: P1)

**Goal**: `contracts/attention-judgement.md` §1–§3, §4, §7 (W1, W4), §8 and §9: dispatch, eligibility, the
call, the record, failure, retry and live only. Plus C10a and C10b to watch shadow mode.

**Independent Test**: with a test instruction and an active fake attention profile, and the opening switch
blank, ingesting messages gives:
- exactly one judgement or one exclusion per message;
- nothing new on a replay;
- classification unchanged;
- no item opened.

### Tests for User Story 2

- [X] T027 [P] [US2] Create `apps/ai-api/tests/moderation/attention_judgement/test_judge_one.py`. Use a scripted
  gateway answering `{"intent": …}`, `instructions={"attention_test": "TEST"}`, and settings via
  `model_copy(update={"moderation_attention_prompt_version": "attention_test"})`. Cover:
  - one row with that intent, `needs_response` from `needs_response_for`, the profile id, `prompt_version`,
    `model_run_id` and `path='live'`; the outcome is `"judged"`;
  - a replay returns `"already_judged"` and adds no row;
  - own words open (`«متى موعد الاختبار؟»`): one `excluded/rule_opens` attempt, **zero gateway calls**, and once
    only on a replay;
  - a moderator's message and an acknowledgement: `excluded` with `moderator` / `acknowledgement`;
  - the gateway raises `StructuredOutputInvalidError` or `ModelTruncatedError`: one `failed` row naming the
    profile, and no judgement;
  - `ProviderUnreachableError` is re-raised and nothing is recorded;
  - prompt blank: outcome `"no_prompt"`, no claim, no call, no row;
  - no active attention profile: `"no_active_model"`;
  - the claim is held elsewhere: `"claimed_elsewhere"`;
  - the request is `[system = "TEST", user = redact(first-posted text)]`, and a URL in the text arrives as
    `«رابط»`;
  - after an edit, the judged text is the captured first-posted text (Finding 5);
  - `caplog` contains no message text.
- [X] T028 [P] [US2] Create `apps/ai-api/tests/moderation/attention_judgement/test_judge_attention_retry.py`,
  mirroring `tests/moderation/classification/test_task_retry.py`:
  - a transient error reschedules `judge_attention` with `attempt + 1` and delay `base × 2^(attempt−1)`;
  - the last attempt records one `failed` row with the error's category.
- [X] T029 [P] [US2] Extend `apps/ai-api/tests/moderation/classification/test_enqueue.py`, or create
  `tests/moderation/attention_judgement/test_dispatch.py`:
  - `derive_message` sends `judge_attention(chat_pk, message_id)` **before** `classify_message`, each exactly once
    per newly inserted message, after commit;
  - a duplicate delivery sends neither;
  - a moderator's message sends both;
  - `schedule_classification=False` and `rederive_chat` send neither (L1).
- [X] T030 [P] [US2] Extend `apps/ai-api/tests/moderation/classification/test_queue_isolation.py`:
  - `judge_attention` is on queue `moderation_attention`;
  - `judge_attention.priority < classify_message.priority` (0 and 10);
  - compose runs `ai-classifier` with `--queues moderation_attention moderation_classify --processes 1
    --threads 1`;
  - `ai-worker` stays on `default`;
  - `MODERATION_ATTENTION_PROMPT_VERSION` is passed to both services.
- [X] T031 [P] [US2] Create `apps/ai-api/tests/moderation/attention_judgement/test_independence.py`:
  - with no active moderation profile, and with a moderation gateway that always fails, `judge_one` still records
    its judgement;
  - with no active attention profile, and with an attention gateway that always fails, `classify_one` still
    records the same prediction as with a working one;
  - the claim keys differ (`ai:mod:classify:msg` and `ai:mod:attention:msg`).
- [X] T032 [P] [US2] Create `apps/ai-api/tests/moderation/attention_judgement/test_metrics_attention.py`, the C10a
  and C10b part. On a hand-computed scenario, run `contracts/attention-metrics.md` C10a and C10b verbatim:
  - the four outcomes partition the messages;
  - exclusions by reason, including `rule_opens`;
  - the **latest** failure wins;
  - intents are counted;
  - `on_time` is computed with `:gap_s = 90`, with a judgement at exactly `sent_at + 90 s` counted and one at
    `+91 s` not.
- [X] T033 [P] [US2] Create `apps/ai-control/tests/Feature/AttentionJudgementFiguresTest.php`, the C10a and C10b
  part. The same scenario through the Classification Accuracy page:
  - "Attention judgements: what happened to every message" numbers;
  - a per `(model, attention prompt)` block with the intent counts and `on_time / judged`;
  - no `%`.

### Implementation for User Story 2

- [X] T034 [US2] Create `apps/ai-api/app/application/moderation/attention_judgement.py`:
  - **`AttentionJudgementResult`:** `intent: Literal[…]`, the six values;
  - **instructions:** `_ATTENTION_INSTRUCTIONS` loaded from `ATTENTION_PROMPT_VERSIONS` (empty for now);
  - **`build_attention_input(text, *, instruction)`:** binds `redacted_text` only (check 4);
  - **helpers:** `_already_judged`, `_insert_attention_exclusion` (`ON CONFLICT … WHERE outcome='excluded' DO
    NOTHING`), `record_attention_failure` (appended), and `_insert_judgement` (`ON CONFLICT (chat, message)
    WHERE is_current DO NOTHING RETURNING id`);
  - **`judge_one(session_factory, gateway, registry, redis, settings, *, chat_pk, message_id, path="live",
    attempt=1, instructions=None) -> str`:**
    - outcome labels: `no_prompt`, `no_active_model`, `claimed_elsewhere`, `already_judged`, `excluded`,
      `failed`, `judged`;
    - it reuses `classification.load_facts` and `classification.claim(…, prefix="ai:mod:attention:msg")`;
    - it calls `generate_structured(…, role="attention")`;
    - transient errors are re-raised (`_TRANSIENT_ERRORS`).

  **No `request_rejudgement` yet** (US3, T046). This makes T027 and T031's attention half pass.
- [X] T035 [US2] Create `apps/ai-api/app/workers/tasks/moderation/judge_attention.py`:
  - `@dramatiq.actor(queue_name="moderation_attention", max_retries=3, priority=0)`;
  - `judge_attention_once` wires a per-task `Gateway(max_retries=0)`, exactly as `classify_message_once` does;
  - `_judge_with_retry` uses `MODERATION_CLASSIFY_MAX_ATTEMPTS` and `MODERATION_CLASSIFY_RETRY_BASE_S`, with
    `record_attention_failure` on the last attempt.

  Also:
  - in `apps/ai-api/app/workers/main.py`, register the actor;
  - in `apps/ai-api/app/workers/tasks/moderation/classify_message.py`, set `priority=10` on the actor, with a
    comment citing D-TG-187.

  This makes T028 pass.
- [X] T036 [US2] In `apps/ai-api/app/application/moderation/messages.py`, send `judge_attention.send(chat_pk,
  body["message_id"])` immediately **before** `classify_message.send(...)`, under the same condition (J1). Update
  the docstring. This makes T029 pass.
- [X] T037 [US2] Update the deployment files:
  - `infra/docker-compose.yml`:
    - `ai-classifier` command `["dramatiq", "app.workers.main", "--queues", "moderation_attention",
      "moderation_classify", "--processes", "1", "--threads", "1"]`;
    - `MODERATION_ATTENTION_PROMPT_VERSION: ${MODERATION_ATTENTION_PROMPT_VERSION:-}` on `ai-classifier` and
      `ai-worker`;
    - `MODERATION_BURST_GAP_S: ${MODERATION_BURST_GAP_S:-90}` on `ai-control`;
  - `.env.example`: a blank `MODERATION_ATTENTION_PROMPT_VERSION=`, with a comment citing FR-307 and D-TG-189.

  This makes T030 pass.
- [X] T038 [US2] Add the panel side of C10a and C10b:
  - `apps/ai-control/config/moderation.php`: `'burst_gap_s' => filled($v = env('MODERATION_BURST_GAP_S')) ? (int) $v
    : 90`;
  - `apps/ai-control/app/Filament/Pages/Concerns/AttentionJudgementMetrics.php` (new trait): C10a and C10b SQL
    verbatim from `contracts/attention-metrics.md`, with the period, chat and `:gap_s` bindings;
  - `ClassificationAccuracy.php` and the blade: the "Attention judgements: what happened to every message" section,
    and one block per `(model, attention prompt)` with intents and `on_time / judged`, with M27 and M29's notes.

  This makes T033 pass.
- [X] T039 [US2] Run the US2 tests plus the full `tests/moderation` suite.

**Checkpoint**: shadow mode works: judgements are recorded and nothing opens.

---

## Phase 5: User Story 3 — A question the rules miss is opened from the attention judgement (Priority: P1)

**Goal**: `contracts/attention-judgement.md` §6 and §7 (W2, W3), D-TG-191 and D-TG-199, and C9′ (two eras).

**Independent Test**: with scripted judgements, check:
- rules first;
- an `ai` item linked to its judgement;
- V;
- the window;
- Case A and Case B;
- prompt blank with the switch set opens nothing.

### Tests for User Story 3

- [X] T040 [P] [US3] Rewrite `apps/ai-api/tests/moderation/classification/test_attention_gate.py` as the
  attention gate:
  - A1/A2 via `judgement_proposes`;
  - V via `vetoed`;
  - keep every G5/G6 case of `within_attention_window` unchanged;
  - delete the G1–G4 cases, since `proposes_attention` is removed.

  Update the docstring.
- [X] T041 [P] [US3] Create `apps/ai-api/tests/moderation/attention_judgement/test_opening.py`. Use
  `insert_attention_judgement`, the switch, and the test prompt set by `model_copy`. Cover:
  1. a rule-signalled burst opens `source='rule'` and ignores an `asking` judgement;
  2. a rule-declined burst whose second member is `asking` opens `source='ai'`:
     - `attention_judgement_id` is that judgement and `message_classification_id` is NULL;
     - the anchor is the earliest member and `opened_at` is its `sent_at`;
     - `responsible_moderator_id = responsible_at(opened_at)`;
  3. a member whose current classification is `SPAM_OR_AD` or `ABUSE` is skipped, and a later unvetoed `asking`
     member opens;
  4. `CHITCHAT` and a missing classification do not veto;
  5. a judgement before `MODERATION_AI_ATTENTION_FROM`, or older than `MODERATION_ITEM_MAX_AGE_S`, opens
     nothing;
  6. a `catch_up` row opens nothing;
  7. the switch set but `MODERATION_ATTENTION_PROMPT_VERSION` blank opens nothing (D-TG-199);
  8. **Case A:** judged before the settle, the settle opens;
  9. **Case B:** `judge_one` after the burst was judged clears `attention_evaluated_at` in the same transaction,
     and the sweep opens;
  10. replays converge on one item;
  11. a historical TG-M5.1 item keeps its classification link.
- [X] T042 [P] [US3] Update `apps/ai-api/tests/moderation/classification/test_config_ai_attention.py`:
  - the "switches on" test also sets the prompt (monkeypatched allowlist);
  - add "switch set, prompt blank → `None`";
  - add "prompt set, switch blank → `None`".
- [X] T043 [P] [US3] Add a case to `apps/ai-api/tests/moderation/classification/test_classify_one.py`: with the
  switch set, a live `needs_response=True` prediction leaves `attention_evaluated_at` untouched (W3).
- [X] T044 [P] [US3] Re-point `apps/ai-api/tests/moderation/classification/test_ai_attention.py` to attention
  judgements:
  - every scenario keeps its name and meaning where it holds (Case A/B, answered before the late judgement, the
    edit/E3 clock, owner at question time, moderator answers, rederive never reaching back), using
    `insert_attention_judgement` instead of `insert_prediction` as the proposal;
  - delete tests that only exercised G3/G4 (`…the_gate_rejects…`, below-floor, CHITCHAT contradiction);
  - rewrite `test_a_dual_purpose_prediction_opens_both_units_independently` as "an incident from the
    classification and a question item from the attention judgement, on one message".
- [X] T045 [P] [US3] C9′ in tests:
  - extend `apps/ai-api/tests/moderation/classification/test_metrics_model_opened.py` with the
    `attention-metrics.md` §1 union: one classification-era item and two attention-era items under two attention
    models. Assert the separate rows, the breakdowns and the M19 kept count across rows;
  - extend `apps/ai-control/tests/Feature/ModelOpenedQuestionsTest.php` with an attention-era item shown in its
    attention block.

### Implementation for User Story 3

- [X] T046 [US3] In `apps/ai-api/app/application/moderation/attention_judgement.py` `judge_one` (W2): after a live
  insert with `needs_response` true, when `ai_attention_from_settings(settings)` is not `None`, call
  `request_rejudgement(session, telegram_chat_id=chat_pk, message_id=message_id)` before commit.
- [X] T047 [US3] In `apps/ai-api/app/application/moderation/attention.py`:
  - `ai_attention_from_settings` returns `None` unless both settings are set (D-TG-199);
  - `_model_proposal` reads the burst members' current `message_attention_judgements`, left-joins each member's
    current `message_classifications.category`, and returns the first judgement id in `(sent_at, message_id)`
    order passing `judgement_proposes`, `within_attention_window` and `not vetoed(category)`;
  - `open_item` writes `attention_judgement_id` and leaves `message_classification_id` NULL;
  - update the module docstring and `open_item`'s docstring (TG-M5.3).
- [X] T048 [US3] Remove `proposes_attention`, `NO_RESPONSE_CATEGORIES` and its comment from
  `apps/ai-api/app/domain/moderation/classification.py`, and update the module docstring.
  - **Deferred to Phase 6 by the operator (2026-10-07), done there with T060.** Deleting the two
    names would have broken `app/scripts/smoke_attention.py` (their last caller), and through it
    `qualify_moderation.py` and `test_qualification_fixtures.py`, until T060 re-pointed the script.
    `grep -rn "proposes_attention\|NO_RESPONSE_CATEGORIES" apps/ai-api` now finds only notes.
- [X] T049 [US3] Remove the `request_rejudgement` block and the unused imports (`proposes_attention`,
  `request_rejudgement`) from `apps/ai-api/app/application/moderation/classification.py` (W3), and update the
  `classify_one` docstring.
- [X] T050 [US3] C9′ in the panel:
  - in `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php`, change
    `classificationModelOpenedQuestions()` to the `attention-metrics.md` §1 union, with the breakdown columns and
    an `era` column;
  - in `ClassificationAccuracy.php`, route `classification` rows to the classification blocks and `attention` rows
    to the attention blocks (T038). `modelKeptQuestions()` sums `model_kept` over both;
  - update the blade.

  This makes T045 pass.
- [X] T051 [US3] Run `uv run pytest tests/moderation` and the PHP Feature suite until green. Every TG-M3, TG-M4 and
  TG-M5 suite must be unchanged in outcome.

**Checkpoint**: AI-assisted opening runs on the attention judgement. The classification's needs-response is
measurement only.

---

## Phase 6: User Story 5 — Qualification, version 2 (Priority: P1)

**Goal**: `contracts/qualification.md` version 2: the core plus the attention and moderation suites, candidate
mode, the new keys, S1/S1b scoring, the reported lines, `make qualify`, and the smoke re-pointed.

**Independent Test**: with a scripted gateway, the attention suite:
- writes nothing and prints no Arabic character;
- prints every gate and reported line;
- returns `CANDIDATE` (exit 3) for a candidate file, never `QUALIFIED`.

### Tests for User Story 5

- [X] T052 [P] [US5] Update `apps/ai-api/tests/moderation/classification/test_qualification_fixtures.py`. Import
  from `app.scripts.qualification.core`, and keep every existing case. Add:
  - `intent` outside the six → `FixtureError`;
  - `intent="asking"` with `needs_response=false` → `FixtureError`, and `discussion` with `true` likewise;
  - `peer` accepted only as `true`;
  - `burst` accepted only in the burst set, as 2–5 strings, with no `text`;
  - `expected_opener` required in the burst set (`rule` | `model` | `none`) and refused elsewhere;
  - errors name the set and line, never the text.
- [X] T053 [P] [US5] Update `apps/ai-api/tests/moderation/classification/test_qualification_scoring.py` and add
  `test_qualification_attention.py` beside it. Cover:
  - **S1:** a rule-opening line makes no gateway call and has opener `rule`; `excluded`; `model` vs `none` from the
    intent;
  - **S1b:** `evaluate` over all members gives `rule`; the first `asking` member's index; `none`;
  - **S2:** A6 lines have no rule step and no veto;
  - **S5:** the signature is opener + intent;
  - **A1–A9 at every boundary:** A4 needs at least 10 rule-declined positives; A7 needs `--repeat` ≥ 2;
  - **Q5–Q12** unchanged;
  - **verdicts,** including `CANDIDATE` and exit code 3;
  - **R-ambiguous, R-intent, R-discussion** (the four counts with lines), **R-rule** (peer apart) and **R-burst**;
  - **the per-message estimate:** sum, max and "not computed";
  - **output:** no Arabic character in the formatted report.
- [X] T054 [P] [US5] Re-point `apps/ai-api/tests/moderation/classification/test_attention_smoke_scoring.py` to the
  rows `judge_attention_line` returns: opener tallies by label, and the intent in place of category, confidence
  and route.

### Implementation for User Story 5

- [X] T055 [US5] Create `apps/ai-api/app/scripts/qualification/core.py` by **moving** these from
  `apps/ai-api/app/scripts/qualify_moderation.py`, with no behaviour change:
  - `FixtureError`, `load_fixture_lines` (plus the V1–V3 keys), `LABEL_CLASSES`, `TRACKED_*`;
  - `SetSpec`, `SetResult`, `ClassSplit`, `GateLine`;
  - `compare_runs`, `latency_percentiles`, `verdict` (plus `CANDIDATE`) and `exit_code_for` (plus 3);
  - the formatting helpers.

  Also create `apps/ai-api/app/scripts/qualification/__init__.py`.
- [X] T056 [US5] Create `apps/ai-api/app/scripts/qualification/moderation.py`: moderation set discovery and gates
  Q5–Q8, Q11 and Q12, through `judge_moderation_fixture`. The report and verdict must be byte-for-byte what
  `qualify_moderation.py` printed for the moderation part.
- [X] T057 [US5] Create `apps/ai-api/app/scripts/qualification/attention.py`:
  - `judge_attention_line(gateway, fixture, *, line, instruction)` (S1);
  - `judge_attention_burst(…)` (S1b) and the A6 judge (S2);
  - attention set discovery (contract §2 order);
  - gates A1–A9 and the reported lines (§6);
  - candidate handling: read the file and print its SHA-256.

  It uses the domain functions only (N2).
- [X] T058 [US5] Create `apps/ai-api/app/scripts/qualification/__main__.py`. Its arguments:
  - `--task attention|moderation`;
  - `--profile`: the role must match the task; `_PinnedRegistry` from `smoke_moderation.py` resolves by name;
  - `--prompt`: the task's allowlist; or `--candidate-file`: attention only, and the path must be under
    `--fixtures-dir`;
  - `--fixtures-dir`, `--repeat`, `--moderation-p95-ms` and `--serving single|concurrent`.

  It uses a bare `Gateway` (no accounting), reuses the `_fail_if_unreachable` probe, and applies the exit codes
  of contract C5.
- [X] T059 [US5] Reduce `apps/ai-api/app/scripts/qualify_moderation.py` to a thin wrapper:
  `main()` → `qualification.__main__` with `--task moderation`, accepting its old flags unchanged. Update its
  docstring to point at version 2.
- [X] T060 [US5] Re-point `apps/ai-api/app/scripts/smoke_attention.py` to `judge_attention_line`, with role
  `attention` and a `--prompt` from `ATTENTION_PROMPT_VERSIONS` or `--candidate-file`.
  - Remove `proposes_attention`, `route_prediction` and the classification schema from it.
  - Then delete `proposes_attention` and `NO_RESPONSE_CATEGORIES` from the domain (T048, deferred
    here), and confirm `grep -rn "proposes_attention\|NO_RESPONSE_CATEGORIES" apps/ai-api` finds
    nothing but notes.
  - Keep stdin input, text-free output and the non-zero exit on a mismatch.

  This makes T054 pass.
- [X] T061 [US5] Update the `Makefile`:
  - add `qualify` (usage error unless `TASK`, `PROFILE` and `FIXTURES_DIR` are set; mount `FIXTURES_DIR`
    read-only at `/fixtures`; pass `--candidate-file /fixtures/$(CANDIDATE)` when `CANDIDATE` is set) to the
    `.PHONY` list;
  - make `qualify-moderation` call `python -m app.scripts.qualification --task moderation …` with its existing
    interface;
  - update `smoke-attention`'s help text (TG-M5.3).
- [X] T062 [US5] Run every qualification and smoke test, plus `uv run ruff check` and `uv run mypy` on
  `app/scripts/qualification/`.

**Checkpoint**: `make qualify TASK=attention …` and `make qualify TASK=moderation …` both run. Version 1's
moderation output is unchanged.

---

## Phase 7: User Story 4 — Member discussion is told apart from questions for the team (Priority: P2)

**Goal**: the validation set with Policy D peer lines, all rule-declined, written **before** the selection round,
plus its fixture test. The six-intent schema exists (T022) and the R-discussion line exists (T057).

**Independent Test**: `test_attention_fixture_files.py` passes. A scripted attention-suite run over the
validation set prints R-discussion with the four counts.

- [X] T063 [P] [US4] Create `apps/ai-api/tests/moderation/attention_judgement/test_attention_fixture_files.py`:
  - every in-repo attention fixture file (`attention_validation_fixtures.jsonl`, `attention_burst_fixtures.jsonl`,
    and `attention_heldout_fixtures.jsonl` when present) loads through `load_fixture_lines` with no
    `FixtureError`;
  - every `peer` line in the validation and held-out files is rule-declined: `evaluate([normalize(text)])` is
    false;
  - **validation minimums:** at least 6 lines with `peer` and `intent="discussion"` and `label_class` clear; at
    least 4 with `peer` and `intent="asking"` (D2 + D5); at least 2 `label_class="ambiguous"` without `peer`
    (D6); 35–45 lines in all;
  - no validation line contains a held-out topic word from plan §9 ("شهاده", "درجات", "تسليم الواجب", "ايصال",
    "رابط الجروب", "قاعه", "زوم", "جدول"), checked on the normalised text.
- [X] T064 [US4] Write `apps/ai-api/app/scripts/attention_validation_fixtures.jsonl`: about 40 synthetic lines.
  - **Topics:** plan §8.3's validation list only (app installation, attendance/absence, study-plan changes,
    mock-exam access, audio/video quality, account name change, refund status, mentor contact).
  - **Phrasing:** Saudi and Egyptian, and mostly without question marks.
  - **Lines:** about 14 rule-declined clear positives; about 14 clear negatives (informing, social, offering,
    resolved status); 1–2 injection-shaped lines labelled by their real function; and the peer lines:
    - at least 6 D3 `discussion` negatives;
    - at least 3 D2 peer-addressed service `asking`;
    - at least 1 D5 peer problem check;
    - at least 2 D6 unaddressed course-content lines (`asking`, ambiguous).
  - **Keys** on every line: `text`, `needs_response`, `intent`, `label_class`, and `peer` where it applies.
  - **The `من` trap** (research Finding 14): check every peer line and every rule-declined positive with
    `evaluate`, and rewrite any that the rules open.

  This makes T063 pass. **No real message text.**

**Checkpoint**: the peer distinction is testable, and the validation set is fixed before any wording runs.

---

## Phase 8: User Story 7 — Bursts stay as they are, and the remaining gap is measured (Priority: P3)

**Goal**: burst fixtures (reported) and C10c, the operator-added split by anchor status and burst size. No TG-M3
change.

**Independent Test**: R-burst prints each burst line's opener and member index. C10c splits operator-added items
into single- and multi-message, exactly.

- [X] T065 [P] [US7] Extend `apps/ai-api/tests/moderation/attention_judgement/test_attention_fixture_files.py` for
  `attention_burst_fixtures.jsonl`:
  - 6–10 lines, each a `burst` of 2–5 with `expected_opener`;
  - every `expected_opener: "rule"` line opens by `evaluate` over all members;
  - every `"model"` and `"none"` line is rule-declined as a whole burst, and so is each of its members;
  - at least 2 lines have `needs_response: true` with `expected_opener: "none"` (L-B1), and at least 3 have
    `expected_opener: "model"`.
- [X] T066 [US7] Write `apps/ai-api/app/scripts/attention_burst_fixtures.jsonl`. Every line carries `burst`,
  `needs_response` (the human label) and `expected_opener`:
  1. «السلام عليكم» + «متى موعد الاختبار؟» → `rule`;
  2. «السلام عليكم» + «كنت بحاول أدخل الاختبار» + «بس الرابط مش شغال» → `rule`;
  3. at least 3 variants with no v1 literal in any member, such as «بس الرابط بايظ», «والرابط مش راضي يفتح» and «بس
     الرابط لا يعمل» → `model` (the opening member's index is reported, not checked);
  4. at least 2 L-B1 lines, such as «كنت بحاول أدخل الاختبار» + «امبارح وبرضه النهارده» + «😢» → `needs_response`
     true, `none`;
  5. 1 greeting + a rule-declined peer discussion → `needs_response` false, `none`.

  Check every line with `evaluate`. This makes T065 pass.
- [X] T067 [P] [US7] Extend `apps/ai-api/tests/moderation/attention_judgement/test_metrics_attention.py` with C10c.
  Operator-added items whose anchors are:
  - judged `asking`, judged `discussion`, excluded `rule_opens`, failed, and none;
  - a single message, a message with a same-sender, same-thread neighbour at exactly 90 s (multi), one at 91 s
    (single), a neighbour in another thread (single), and a `sender_chat` anchor (single).

  Assert each `(anchor_status, multi_message)` count.
- [X] T068 [P] [US7] Extend `apps/ai-control/tests/Feature/AttentionJudgementFiguresTest.php` with the C10c section's
  numbers on the same scenario.
- [X] T069 [US7] Add C10c, verbatim from `contracts/attention-metrics.md`, to
  `apps/ai-control/app/Filament/Pages/Concerns/AttentionJudgementMetrics.php`. Render it beneath C10a in the blade
  with M31's note ("review multi-message rows by hand"). This makes T067 and T068 pass.

**Checkpoint**: L-B1 is measurable before the pilot (R-burst) and during it (C10c).

---

## Phase 9: User Story 6 — The wording is chosen without fitting the benchmark (Priority: P2)

**Goal**: `contracts/qualification.md` §8 W-1 to W-7: the selection round, at most one revision, the freeze,
the held-out run once, and the fresh sample. **Prerequisites: Phases 6–8 done, and T070.**

- [X] T070 [US6] *(operator)* Prerequisites:
  - ✅ confirm Policy D (spec FR-310), or edit it through `/speckit-clarify`. **Done 2026-10-07:** D1–D8
    confirmed, D1 reworded ("the expected answerer decides, not the addressee"); recorded in spec Clarifications,
    FR-310, `contracts/attention-judgement.md` §5 and plan §5a;
  - finish T031 (carried from 010) on `~/Projects/injaz-m5-fixtures/real-attention*.jsonl`: `label_class`, real
    moderation #1 `"tracked": "no-link-rule"`, and `intent` + `"peer": true` on peer lines;
    - *2026-10-07, validated by the agent (no text printed):* both `real-attention*.jsonl` files load with no
      `FixtureError`; every line carries a valid `intent` and a `label_class`, with `asking` exactly on
      `needs_response` true; `text`, `needs_response` and `category` are unchanged from the `.before-t070` copies.
      Ambiguous lines: original #5–#13, paired #1–#12. No peer lines, so no `peer`.
    - *2026-10-07, operator-confirmed:* `real-moderation.jsonl` #1 carries `"tracked": "no-link-rule"`, added by
      the agent on the operator's word (only that key; the original is kept as
      `real-moderation.before-t070.jsonl`, which no suite reads). Tracked lines in the moderation suite: 2 (this
      and shipped #11), at Q12's limit.
    - *2026-10-07:* the operator moved the two `real-attention*.before-t070.jsonl` copies out of the
      `real-attention*.jsonl` glob; only the two annotated files match it now;
  - rebuild the `migrate` tool image whenever it may be stale (quickstart §2:
    `docker compose -f infra/docker-compose.yml --env-file .env --profile tools build migrate`), then run
    `make migrate` and `make seed-profiles` on development, and check `make profiles`.
    - *2026-10-07:* the first run used a `migrate` image built on 2026-10-05, so it stayed at `0007` and seeded
      no attention profile. After the rebuild: development is at `0008`, both `message_attention_*` tables
      exist, and `ollama-gemma4-e2b-attention` and `ollama-gemma4-e4b-attention` are listed, `role=attention`,
      inactive.
- [X] T071 [US6] Write the three candidates (W-1) to `~/Projects/injaz-m5-fixtures/attention-candidate-w1.md`,
  `-w2.md` and `-w3.md`. These are outside the repository and contain no message text.
  - **The shared block, identical bytes in all three:** the task sentence, the six intent definitions
    (`contracts/attention-judgement.md` S3), Policy D D1–D7, and the output instruction (`{"intent": …}` only).
  - **W1:** the generic asking/informing/mixed/Policy S paragraphs, with no domain nouns.
  - **W2:** P2's measured asking and informing paragraphs from 010 research §2, adapted to one task.
  - **W3:** W1 plus one service glossary sentence.

  Record each SHA-256 in research §2 **before any run**.
- [X] T072 [US6] Run the matrix (W-2), six runs in sequence with Ollama running and only one model loaded at a
  time: `make qualify TASK=attention PROFILE=ollama-gemma4-{e2b,e4b}-attention CANDIDATE=attention-candidate-w{1,2,3}.md
  FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`.
  - Record the counts only in research §2: the gates, R-discussion, R-rule, R-burst, and latency.
- [X] T073 [US6] Apply W-3, and record the decision and the noun-memorisation reading in research §2.
  - **If no candidate passes,** allow one revision (W-4) of the failing sentence only, re-run that candidate on
    both models, and record it.
  - **If still none passes, STOP (W-7):** record "stopped" in research §2, plan.md Progress and spec Status, and
    skip T074–T077.
- [X] T074 [US6] Freeze, in one change:
  - write the chosen text to `apps/ai-api/app/prompts/moderation/attention_v1.md`;
  - set `ATTENTION_PROMPT_VERSIONS = ("attention_v1",)` in `apps/ai-api/app/infrastructure/config.py`;
  - add its SHA-256 to `_PINNED_ATTENTION_SHA256` in
    `apps/ai-api/tests/moderation/classification/test_prompt_pinned.py`.

  Run the pin and config tests.
- [X] T075 [US6] **After T074 only**, write `apps/ai-api/app/scripts/attention_heldout_fixtures.jsonl` (W-5):
  - plan §9's topics and grid;
  - at least 10 rule-declined clear positives, at least 80% without a question mark;
  - at least 3 rule-declined peer-discussion negatives and at least 2 peer-addressed positives;
  - every line checked with `evaluate`, synthetic only.

  Extend T063's minimums to it.
- [X] T076 [US6] Run once: `make qualify TASK=attention PROFILE=<chosen> PROMPT=attention_v1
  FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`.
  - Record the counts in research §2.
  - **A held-out failure is reported as it stands.** `attention_v1.md` is never edited.
  - If only the fresh sample is missing, the expected verdict is `INCOMPLETE`.
- [X] T077 [US6] *(operator)* Add `fresh-attention.jsonl` (20–30 real messages, labelled with `intent` before any
  run), re-run T076's command for `QUALIFIED`, and run the moderation suite again to compare with T002 (SC-305).
  - *(2026-10-08)* e4b + `attention_v1` is `QUALIFIED` (A5: 1 opened, 0 missed). e2b + `classify_v2` is
    `QUALIFIED`, with per-line status identical to T002, so SC-305 holds (research §2).
  - The file holds 37 lines, against the 30 reported; the operator is to confirm. 27 of them open by rule, so A5
    rests on 8 clear negatives and 1 clear positive.
  - *(2026-10-08, confirmed by the operator)* The run read the 37-line version, now at
    `backup/fresh-attention-all-37-reviewed.jsonl`. The active file was then cut back to 30 lines. The evidence is
    historical, valid under Policy D only, and the sample is not reused as a fresh sample (research §2).

**Checkpoint**: `attention_v1` is frozen and qualified, or the milestone stopped with the evidence recorded.

---

## Phase 9b: User Story 6, second cycle — Policy D′ and `attention_v2` (added 2026-10-09)

**Goal:** `docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`, approved 2026-10-09 with every recommended option.
- **What changes:** Policy D′ (spec FR-310; outside institutions are not the team's), and `attention_v2` through
  W-1′ to W-7′ (`contracts/qualification.md` §8′).
- **What stays:** `attention_v1` frozen, pinned and allowlisted as history, and its T071–T077 evidence as
  recorded. `MODERATION_AI_ATTENTION_FROM` stays blank throughout.

**Independent test:** `make qualify TASK=attention PROFILE=<chosen> PROMPT=attention_v2 …` gives `QUALIFIED` on
the second cycle's sets, or the cycle stops with the evidence recorded.

### Policy and fixtures

- [X] T083 [US6] Record Policy D′ and the addendum. No code. *(2026-10-09)* Done:
  - **the spec:**
    - `spec.md`: Status, the Clarifications session 2026-10-08/09, FR-307, FR-309, FR-310 (D′, with Policy D as
      history), FR-325 A3, FR-330, FR-331, FR-333 and SC-302;
  - **the contracts:**
    - `contracts/attention-judgement.md`: P3, §4 S3, and §5′ (Policy D′), with §5 kept as history;
    - `contracts/qualification.md`: §2's second-cycle sets, A3 per validation set, and §8′ (W-1′ to W-7′);
  - **the plan of record:** dated notes in §5a, §8.3, §8.4 and §9, and the header pointer;
  - **the rest:**
    - `research.md` D-TG-200;
    - `data-model.md` §8's second-cycle sets;
    - quickstart §5a and the §6 note;
    - the addendum's status.
- [X] T084 [US6] *(operator)* Relabel the used fresh sample and take it out of the fresh role:
  - relabel T077's 37-line sample (`backup/fresh-attention-all-37-reviewed.jsonl`) under Policy D′: `intent`,
    `needs_response`, `label_class` and `peer`;
  - save it as `~/Projects/injaz-m5-fixtures/real-attention-fresh-v1.jsonl`;
  - move the 30-line `fresh-attention.jsonl` out of the fixtures directory;
  - confirm that `real-attention.jsonl` and `real-attention-extra.jsonl` need no D′ change.
- [X] T085 [US6] Validate T084 by counts only, with no text printed:
  - the keys are present;
  - `intent == "asking"` iff `needs_response`;
  - the rule-declined counts;
  - no `fresh-attention.jsonl` is left in the fixtures directory.

  Record the result in research §2.
  - *(2026-10-09)* Valid: 37 lines; 24 relabelled from `asking`; 3 left `asking`, all consistent with D′; no
    disputed label. 10 lines are rule-declined: 8 clear negatives and 1 clear positive. It loads as tuning, and
    A5 is `NOT RUN` until T095 (research §2).
- [X] T086 [US6] Keep the v1 held-out set as a validation set, unchanged, and judge A3 per validation set:
  - rename `apps/ai-api/app/scripts/attention_heldout_fixtures.jsonl` to `attention_heldout_v1_fixtures.jsonl`,
    byte-identical, and pin its SHA-256 in `tests/moderation/attention_judgement/test_attention_fixture_files.py`;
  - in `apps/ai-api/app/scripts/qualification/attention.py`:
    - `discover_attention_sets` reads it and `attention_validation_scope_fixtures.jsonl` as validation;
    - A3 is judged per validation set, and its gate line lists each set's counts;
  - tests first: set discovery, and A3 failing on one set while passing on another.
  - *(2026-10-09)* Done; no model run. The file was renamed with its SHA-256 unchanged (`0178e64e…ae820`). A3 is
    `_per_set_gate`, and its detail lists each set's counts. A4 and A5 are unchanged. pytest 1273 passed, ruff
    and mypy green (research §2).
- [X] T087 [US6] Write `apps/ai-api/app/scripts/attention_validation_scope_fixtures.jsonl` (addendum §6.2) **before
  any v2 candidate exists**, and extend `test_attention_fixture_files.py`:
  - about 18 synthetic lines, every one rule-declined, on the validation outside topics: Jadarah (جدارة),
    scholarships (ابتعاث), university placement (تنسيق), unified admission (القبول الموحد);
  - **the minimums:**
    - ≥ 6 outside-institution clear negatives;
    - ≥ 4 own-service clear positives with the same surface words, ≥ 2 of them peer-addressed;
    - ≥ 2 D7 lines, ambiguous;
    - ≥ 1 exam-content line, ambiguous;
  - **the tests:**
    - the scope minimums;
    - the v2 held-out topic words (addendum §6.6) absent from every in-repo validation and tuning file;
    - the peer rule check over every validation file;
    - the v1 held-out hash.
  - *(2026-10-09)* Done; no model run. The set has 18 lines:
    - 8 outside-institution negatives;
    - 5 own-service positives, 2 of them peer-addressed;
    - 2 D7 lines and 2 exam-content lines, ambiguous;
    - 1 own-service informing line.

    It has no held-out-v2 or tuning-institution word. The new tests each fail on a broken copy. pytest 1284
    passed (research §2).
- [X] T088 [US6] Run the full check suite with no model runtime (SC-310) and record it in research §2.
  - *(2026-10-09)* Same outcome as T001's baseline:
    - ruff, the checks 1–4 and mypy are green;
    - pytest: 1285 passed, 9 skipped, and the 4 known `test_secret_scan.py` failures;
    - PHP Feature: OK, 139 tests;
    - the secret scan flags only the known line.

    Ollama was left running; no test calls a model.

### Selection and freeze

- [X] T089 [US6] W-1′: write the three candidates into the fixtures directory as
  `attention-candidate-v2-{a,b,c}.md`, each `attention_v1.md` with Policy D′'s sentences (qualification §8′).
  Record each SHA-256 in research §2 **before any run**.
  - *(2026-10-09)* V2-A `47ed0625…`, V2-B `f0d492fc…`, V2-C `6aae2877…` (research §2), all recorded before any run.
- [X] T090 [US6] W-2′: run the six runs in sequence, with Ollama running and one model loaded at a time:
  `make qualify TASK=attention PROFILE=ollama-gemma4-{e2b,e4b}-attention CANDIDATE=attention-candidate-v2-{a,b,c}.md
  FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`.
  - Record the counts only in research §2: the gates (A3 per set), R-discussion, R-rule, R-burst, and latency.
  - *(2026-10-09)* Done: no candidate passes. The closest, e4b × V2-A, fails A1 (extra #15) and A3 (base: #4, #27 missed; scope: #5, #7 opened) (research §2).
- [X] T091 [US6] Apply W-3′.
  - **If no candidate passes:** allow one revision (W-4′) of the failing sentence, never a policy sentence.
  - **If still none passes, STOP (W-7′):** record "stopped" in research §2, plan.md Progress and the spec
    Status, and skip T092–T095. `attention_v1` stays unqualified under D′, and opening stays rules-only.
  - *(2026-10-09)* **Stopped (W-7′).** No candidate passed W-3′. The operator chose the one revision: V2-AR, the
    Informing paragraph's last sentence (`fbe98d5f…`). It changed no gated line on e4b and also failed on e2b.
    T092–T095 are skipped, and `attention_v2` is not created (research §2).
- [ ] T092 [US6] *(skipped: the cycle stopped under W-7′, 2026-10-09)* Freeze, in one change:
  - write the chosen text to `apps/ai-api/app/prompts/moderation/attention_v2.md`;
  - set `ATTENTION_PROMPT_VERSIONS = ("attention_v1", "attention_v2")`;
  - add the SHA-256 to `_PINNED_ATTENTION_SHA256`;
  - update the allowlist tests (`test_config_attention.py`, `test_qualification_fixtures.py`).

  `attention_v1.md` and its pin stay unchanged. Run the pin and config tests.

### Held-out and fresh

- [ ] T093 [US6] *(skipped: the cycle stopped under W-7′, 2026-10-09)* **After T092 only,** write the new `apps/ai-api/app/scripts/attention_heldout_fixtures.jsonl`
  (addendum §6.6) on the fixed topics, synthetic only, with every line checked with `evaluate`. Extend the
  held-out minimums in `test_attention_fixture_files.py`.
- [ ] T094 [US6] *(skipped: the cycle stopped under W-7′, 2026-10-09)* Run once: `make qualify TASK=attention PROFILE=<chosen> PROMPT=attention_v2
  FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2`.
  - Record the counts in research §2. A held-out failure is reported as it stands.
  - With no fresh sample yet, the expected verdict is `INCOMPLETE`.
- [ ] T095 [US6] *(skipped: the cycle stopped under W-7′, 2026-10-09)* *(operator)* Add a new `fresh-attention.jsonl` and qualify:
  - 20–30 real messages, none of them in T077's sample, labelled under D′ before any run;
  - re-run T094's command for `QUALIFIED`;
  - run the moderation suite again and compare it with T002 (SC-305).

**Checkpoint**: `attention_v2` is frozen and qualified under Policy D′, or the cycle stopped with the evidence
recorded. Shadow follows quickstart §6 with `attention_v2`.

*(2026-10-09)* **Outcome: the cycle stopped with the evidence recorded** (research §2). `attention_v1` stays frozen
history, unqualified under D′, and opening stays rules-only.

---

## Phase 10: Polish & Cross-Cutting

- [X] T078 [P] Write the dated "Amended by TG-M5.3" notes not covered by T012, keeping the history:
  - `specs/008-tg-m5-ai-classification/contracts/classification-pipeline.md` (R13, N1, F6: the classifier no
    longer requests re-judgement; needs-response is measurement only);
  - `specs/008-tg-m5-ai-classification/data-model.md` (the `attention` role; the item's second link);
  - `specs/006-tg-m3-response-tracking/data-model.md` (`attention_items.attention_judgement_id`,
    `ck_attention_ai_link`);
  - `specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md` (§1–§3 superseded by
    `011/contracts/attention-judgement.md` §6–§7; O3's link; I1's caller; §9 L-B1);
  - `specs/009-tg-m5-1-ai-attention/quickstart.md` (the switch needs both settings);
  - `specs/010-tg-m5-2-classify-v3/contracts/qualification.md` (superseded by 011's version 2; the alias is
    kept).
- [X] T079 [P] Add a dated note to the revision reservation in
  `docs/plan/telegram/telegram-moderation-intelligence.md`: the revision table row and the "Alembic numbering"
  paragraph. TG-M5.3 took `0008` (D-TG-192), and later moderation revisions take the next free numbers.
- [X] T080 [P] Add a **TG-M5.3** row to `docs/runbooks/tg-operator-prerequisites.md` §C, after the TG-M5.1 row:
  - confirm Policy D, then T031 with intents, then the fresh sample;
  - `make qualify TASK=attention …`;
  - shadow (activate the attention profile, set `MODERATION_ATTENTION_PROMPT_VERSION`, recreate `ai-worker` and
    `ai-classifier`);
  - the switch and the pilot.

  Cross-reference `specs/011-…/quickstart.md`.
- [X] T081 Update `CLAUDE.md`'s status line and `specs/011-tg-m5-3-attention-judgement/plan.md` Progress to the
  actual outcome. Mark finished tasks `[X]` here.
- [X] T082 Run `make check` with Ollama quit. Everything must pass, apart from T001's recorded baseline
  failures. Confirm in particular:
  - check 4 (no text in logs) and the import boundaries pass;
  - the `classify_v1`/`classify_v2` hashes are unchanged (SC-310).

  Record the result in research §2.
  - *(2026-10-09)* T001's baseline outcome:
    - ruff, the checks 1–4 (check 4 included) and mypy are green;
    - pytest: 1285 passed and the 4 known secret-scan failures;
    - PHP Feature: OK, 139 tests;
    - the secret scan flags only the known line;
    - the prompt pins pass.

    Ollama was left running; no test calls a model (research §2).

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: none. T002 needs Ollama.
- **Phase 2 (US1)**: needs only T001. **It is independent of Phase 3 and can ship alone.**
- **Phase 3 (Foundational)**: needs T001. It blocks Phases 4–9.
- **Phase 4 (US2)**: needs Phase 3.
- **Phase 5 (US3)**: needs Phase 4 (`judge_one` exists, for W2). C9′ (T050) also needs T009 from US1.
- **Phase 6 (US5)**: needs Phase 3; its tests are independent of US2 and US3 code. T057 uses the domain only.
- **Phase 7 (US4)**: needs T055 (key validation) for T063.
- **Phase 8 (US7)**: needs T055 (burst key), T038 (the C10 trait) and Phase 3 tables for C10c.
- **Phase 9 (US6)**: needs Phases 6–8 and the operator's T070. It is strictly sequential, T071 → T077.
- **Phase 9b (US6, second cycle)**: needs Phase 9 and the approved addendum. It is strictly sequential, T083 →
  T095. T089 needs T087 (validation before candidates); T093 needs T092 (held-out after the freeze).
- **Phase 10**: after the stories it documents, Phase 9b included. T082 is last.

### Within stories

- Tests come first and fail first.
- Domain before application, application before actor and wiring, SQL before panel.
- The T034 → T046 order matters: `judge_one` exists before it gains W2.

### Parallel opportunities

- **US1:** T003–T007 together; then T008–T011 in sequence (shared page); T012 alongside.
- **Foundational:** T015–T018 together; then T020–T025 together; T019 after T020's metadata review.
- **US2:** T027–T033 together.
- **US3:** T040–T045 together.
- **US5:** T052–T054 together.
- **US7:** T065, T067 and T068 together.
- **Polish:** T078–T080 together.
- **US5 (Phase 6) can run alongside US2/US3** (Phases 4–5) once Phase 3 is done. They touch different files,
  apart from `smoke_attention.py`, which is US5's only.

## Parallel Example: User Story 2

```text
Task: "T027 test_judge_one.py — record, replay, rule_opens, exclusions, failures, prompt blank, claim, input, logs"
Task: "T028 test_judge_attention_retry.py — doubling backoff, final failure row"
Task: "T029 test_dispatch.py — judge_attention before classify_message, once, after commit"
Task: "T030 test_queue_isolation.py — moderation_attention queue, priority 0 < 10, compose"
Task: "T031 test_independence.py — each judgement with the other absent or failing"
Task: "T032 test_metrics_attention.py — C10a partition, C10b intents and on_time"
Task: "T033 AttentionJudgementFiguresTest.php — the C10a/C10b panel numbers"
```

## Implementation Strategy

### MVP first: User Story 1 alone

1. T001, then Phase 2 (T003–T013).
2. **STOP and validate:** dismissal values are unchanged, the breakdowns sum, the wording is fixed.
3. Deploy the panel only (quickstart §1).

### Then the judgement, in increments

1. Phase 3, then US2: shadow-capable, nothing opens.
2. US3: opening switched to the judgement. Development AI opening stays paused until the prompt is set
   (D-TG-199).
3. US5: qualification version 2. US4 and US7: the fixtures and C10c.
4. US6: selection, freeze, held-out, then the operator's fresh sample and pilot.

### Stop conditions

- **T073 (W-7):** no candidate passes after one revision. Record and stop; do not iterate further.
- **T076:** a held-out failure is reported as it stands, and the frozen version is never edited.

## Notes

- `[P]` means a different file with no dependency on an incomplete task.
- `[USn]` maps to the spec's user stories, in priority order: US1, US2, US3, US5 (P1), then US4, US6 (P2), then US7
  (P3). US6 runs last by dependency.
- *(operator)* tasks are never done by the agent: T070, T077, T084, T095, and the shadow/pilot steps in the
  quickstart.
- Commits are the operator's after any checkpoint.
