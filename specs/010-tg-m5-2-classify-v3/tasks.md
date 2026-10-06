# Tasks: TG-M5.2 — classify_v3 and Model Qualification

**Input**: `specs/010-tg-m5-2-classify-v3/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: these are required (plan's Constitution Check §1) and are written first. Each must fail before its
implementation exists. Every automated test is scripted: no model runtime, credential or network. Database
tests use `injaz_ai_test` only.

**Git**: none by the agent (constitution IV). Tasks marked *(operator)* are the operator's.

> **Stopped under FR-216 (2026-10-06).** T024's second round failed, so `classify_v3` never froze.
> - **Removed 2026-10-06:** `classify_v3.md`, its allowlist entry and pin, and its v3-only tests. Kept: the
>   every-instruction G4 test.
> - **Development runtime restored:** the e2b profile active, `classify_v2`. The e4b profile stays registered,
>   inactive, and its model stays installed.
> - **Not run:** Phase 5 (no freeze), T028, T032–T034 and T037 (all v3-specific).
> - **Still valid, carried to TG-M5.3:** T029 (the label review of shipped #11), T030 (the no-link rule exit)
>   and T031 (external annotations and the fresh sample).
> - **Next:** `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`.

**Paths**: `apps/ai-api/…`. Tests live under `apps/ai-api/tests/moderation/classification/`. Run them with
`cd apps/ai-api && uv run pytest <path>`.

## Phase 1: Setup

- [X] T001 Run `make check` with Ollama quit, and record that the suite is green before any change (baseline
  for SC-208). Repository root, no file change.
  - *Done 2026-10-04, with Ollama running. Not green: 4 pre-existing `test_secret_scan.py` failures. See
    research §2 "Baseline before any change".*

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: the qualification command, the freeze and the held-out run all depend on one per-fixture judgement
path (D-TG-178) and on validated fixture keys (data-model §1).

- [X] T002 [P] Write failing tests for fixture-key validation in
  `apps/ai-api/tests/moderation/classification/test_qualification_fixtures.py`:
  - a missing `label_class` defaults to `clear`; `ambiguous` is accepted;
  - an unknown `label_class` or `tracked` value is refused, and the error names the set and line but never the
    text;
  - `label_class` on a moderation fixture is refused;
  - `tracked` ∈ {`no-link-rule`, `label-review`};
  - blank lines are skipped, and numbering matches the smokes' `#N`.
- [X] T003 [P] Extract `async judge_attention_fixture(gateway, fixture, *, line, prompt_version, floor,
  threshold) -> tuple[AttentionRow, int | None]` from `_run` in `apps/ai-api/app/scripts/smoke_attention.py`.
  - The calls stay the same, in the same order: normalise, `evaluate`, `eligibility`, model, `route_prediction`
    (live), `proposes_attention`.
  - The function returns the row and `latency_ms`. `_run` keeps its printing and exit code byte-for-byte.
  - `test_attention_smoke_scoring.py` must stay green.
- [X] T004 [P] Extract `async judge_moderation_fixture(gateway, fixture, *, line, prompt_version, floor,
  threshold) -> tuple[SmokeRow, int | None]` from `_run` in `apps/ai-api/app/scripts/smoke_moderation.py`, the
  same way. `test_smoke_scoring.py` must stay green.
- [X] T005 Implement fixture loading and validation:
  - `load_fixture_lines(path, kind) -> list[tuple[int, dict]]` and `FixtureError` in
    `apps/ai-api/app/scripts/qualify_moderation.py`, a new module with only these at this point;
  - the constants `LABEL_CLASSES = ("clear", "ambiguous")`, `TRACKED_DISPOSITIONS = ("no-link-rule",
    "label-review")` and `TRACKED_LIMIT = 2`.

  Make T002 pass.
- [X] T006 [P] Annotate the shipped synthetic sets. Add keys only, never change a label (D-TG-177):
  - `apps/ai-api/app/scripts/attention_smoke_fixtures.jsonl` #4, #5, #6: add `"label_class": "ambiguous"`;
  - `apps/ai-api/app/scripts/moderation_smoke_fixtures.jsonl` #11: add `"tracked": "label-review"`.

  Then confirm that `make smoke-attention` and `make smoke-moderation` still load both files.
  - *Done: both smokes, on the rebuilt image and pinned to e2b + `classify_v2`, judged all 15 and 12 lines.*

**Checkpoint**: the smokes are unchanged in behaviour, the shared judgement is reusable, and the fixture keys
are validated.

---

## Phase 3: User Story 4 — The operator qualifies a model on any host (Priority: P1) 🎯 MVP enabler

**Goal**: one read-only command judges a profile-and-instruction pair over every set and prints the Q1–Q12 gate
and a verdict (`contracts/qualification.md`). Every later story is measured through it.

**Independent Test**: run it for the inactive e4b profile with `classify_v2`. It writes no row, prints no text,
prints every gate line, and exits 1, 2 or 0 to match its verdict.

### Tests for User Story 4

- [X] T007 [P] [US4] Write failing pure tests for scoring S1–S6 in
  `apps/ai-api/tests/moderation/classification/test_qualification_scoring.py`. Build scripted
  `AttentionRow`/`SmokeRow` lists and cover:
  - clear positives with no opener, counting `none` and `excluded` as missed;
  - clear negatives with the `model` opener;
  - rule-declined clear positives;
  - ambiguous "answered true" and agreement, never in a gate count;
  - tracked moderation lines removed from false negatives, false positives and routes, and reported with
    pass/fail;
  - the repeat comparison, counting differing lines over needs-response, needs-moderation, category and route;
  - median and p95 latency.
- [X] T008 [P] [US4] Write failing pure tests for the gate and verdict in the same file:
  - each of Q1–Q12 at its boundary: Q2 at 1 vs 2, Q4 at 1 vs 2, Q7 at false negatives 1 vs 2, Q10 at
    10,000 vs 10,001 ms, Q12 at 2 vs 3 tracked lines;
  - `NOT RUN` when a required set is missing, giving `INCOMPLETE`;
  - `FAIL` taking precedence over `NOT RUN`;
  - `--repeat 1` never `QUALIFIED`;
  - exit codes 0, 1 and 2;
  - `format_report()` lines carrying no fixture text: feed a sentinel text and assert it never appears.

### Implementation for User Story 4

- [X] T009 [US4] Implement the pure parts in `apps/ai-api/app/scripts/qualify_moderation.py`:
  - the `SetSpec`, `SetResult`, `ClassSplit`, `TrackedLine` and `GateLine` dataclasses;
  - `split_by_label_class()`, `moderation_gated()`, `compare_runs()`, `latency_percentiles()`,
    `evaluate_gate()`, `verdict()` and `format_report()`, exactly as `contracts/qualification.md` §3–§5 says.

  Make T007 and T008 pass.
- [X] T010 [US4] Implement `discover_sets(fixtures_dir) -> list[SetSpec]` in the same file, per data-model §2:
  - `real-attention*.jsonl` (sorted) and the shipped attention set → tuning;
  - `attention_smoke_heldout_fixtures.jsonl` → held-out, required;
  - `fresh-attention.jsonl` → fresh sample, required for `QUALIFIED`;
  - `real-moderation.jsonl`, `moderation_smoke_fixtures.jsonl` and `moderation_smoke_policy_fixtures.jsonl` →
    moderation.

  Add a pure test to `test_qualification_fixtures.py` over a temporary directory, covering both present and
  missing sets.
- [X] T011 [US4] Implement `async _run(argv)` and `main()` in the same file.
  - **Arguments:** `--profile` (required), `--prompt` (an allowlist choice, default the configured one),
    `--fixtures-dir` and `--repeat` (default 2).
  - **Wiring:** resolve with `_PinnedRegistry`; reuse `_fail_if_unreachable` from `smoke_moderation`; use a
    bare `Gateway(registry)`, which records no accounting (C2).
  - **Judging:** every set, `--repeat` times, through `judge_attention_fixture` and
    `judge_moderation_fixture`.
  - **Output:** the smokes' per-line format for run 1 only, then `format_report()`, then the exit code (C5).
  - No text in any output (C3).
- [X] T012 [US4] Add a `qualify-moderation` target to `Makefile`:

  ```sh
  $(COMPOSE) --profile tools run --rm -T -v "$(FIXTURES_DIR)":/fixtures:ro migrate \
    python -m app.scripts.qualify_moderation --profile $(PROFILE) --prompt $(PROMPT) \
    --fixtures-dir /fixtures --repeat $(or $(REPEAT),2)
  ```

  Add it to `.PHONY` with a `##` help line, and refuse to run when `PROFILE` or `FIXTURES_DIR` is empty.
- [X] T013 [US4] Rebuild the tools image and run the development baseline:

  ```sh
  make qualify-moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures
  ```

  Expected: `NOT QUALIFIED`. Q1 fails at about 12 tuning clear negatives, and the held-out set and fresh sample
  are `NOT RUN`. Record the counts only in `specs/010-tg-m5-2-classify-v3/research.md` §2.
  - Until the operator annotates the external sets (T031), their lines count as `clear`. Note that in the
    record.
  - *Done 2026-10-04: `NOT QUALIFIED`. Q1 fails at 14, Q3 at 2, and Q2, Q4 and Q9 are `NOT RUN` (research
    §2).*

**Checkpoint**: qualification works end to end and writes nothing. US1–US3 can now be measured.

---

## Phase 4: User Stories 1–3 — classify_v3: informing does not open, implicit questions still do, adverts preserved (Priority: P1)

**Goal**: freeze `classify_v3` per `contracts/classify-v3.md` §3, in at most two measured rounds. One
instruction serves all three stories, so one phase holds them, and each story's acceptance is a separate gate
reading.

**Independent Test**: qualification of e4b with `classify_v3`.
- US1 is Q1, tuning clear negatives model-opened = 0.
- US2 is Q3 = 0, plus the ambiguous count, reported.
- US3 is Q5–Q7, with the tracked lines reported.

### Tests for User Stories 1–3

- [X] T014 [P] [US1] Write failing tests in `apps/ai-api/tests/moderation/classification/test_prompt_pinned.py`:
  - `classify_v3` is in `PROMPT_VERSIONS` and has a file and a pin;
  - the v1 and v2 pins are unchanged;
  - **every** pinned instruction contains `Always false for SPAM_OR_AD, ABUSE and CHITCHAT.` verbatim (V4).
- [X] T015 [P] [US1] Write failing tests in `test_prompt_version.py` and `test_config_classification.py`:
  - `MODERATION_PROMPT_VERSION=classify_v3` is accepted;
  - the default is still `classify_v1`, and blank means the default;
  - an unknown value is refused at startup.
- [X] T016 [P] [US1] Write failing tests in `test_model_input.py` and `test_classify_one.py`:
  - with `classify_v3` configured, `system` equals `classify_v3.md`'s bytes, `user` is the redacted text, and
    nothing else is sent;
  - a live prediction stores `prompt_version='classify_v3'` (on `injaz_ai_test`);
  - catch-up under v3 is still `measurement_only`.
- [X] T017 [P] [US3] Write a failing test in `test_prompt_pinned.py` that every v2 line V3 names (intro, group
  rule, "Judge what the whole message is for…", COMPLAINT, CHITCHAT, SPAM_OR_AD, ABUSE, needs_moderation,
  severity, confidence and the final line) appears byte-identically in `classify_v3.md`.
- [X] T018 [P] [US1] Write a failing test that `classify_v3.md` is at most `len(classify_v2.md) + 1200`
  characters (V6), in `test_prompt_pinned.py`.

### Implementation for User Stories 1–3

- [X] T019 [US1] Create `apps/ai-api/app/prompts/moderation/classify_v3.md` as the F1 starting draft: v2's text
  with exactly the insertion and four replacements listed in `contracts/classify-v3.md` §2. Use no other edit,
  and build it from v2's bytes by script, not by retyping.
- [X] T020 [US1] Add `"classify_v3"` to `ModerationPromptVersion` in `apps/ai-api/app/infrastructure/config.py`,
  leaving the default `classify_v1`. Pin v3's SHA-256 **provisionally** in `test_prompt_pinned.py`. Make
  T014–T018 pass.
- [X] T021 [US1] F1. Rebuild the tools image and run:

  ```sh
  make qualify-moderation PROFILE=ollama-gemma4-e4b-moderation PROMPT=classify_v3 FIXTURES_DIR=~/Projects/injaz-m5-fixtures
  ```

  Run the same with `PROFILE=ollama-gemma4-e2b-moderation`, for information only. Record the counts in
  `research.md` §2: Q1, Q3, Q5–Q8, Q10, Q11, the ambiguous count and the tracked lines.
  - *Done 2026-10-04 (research §2 "F1"): e4b `NOT QUALIFIED`. Q1 fails at 1 (extra #15). Under plan §13's
    proposed annotations, every other tuning gate passes. e2b `NOT QUALIFIED`, for information.*
- [X] T022 [US2] Read F1 for US2. Q3 = 0 on e4b, and the ambiguous "answered true" count is recorded beside P2's
  15/23. If Q3 fails where P2 passed, mark F2 as needed.
  - *Done: Q3 = 0 under the proposed annotations (all 7 misses are proposed-ambiguous); ambiguous 14/23.*
- [X] T023 [US3] Read F1 for US3:
  - Q5–Q7 on e4b pass, with real moderation #1 and shipped #11 shown as tracked;
  - no legitimate line is routed to `incident`.

  If any of these fails where P2 passed, mark F2 as needed.
  - *Done: Q5–Q7 pass with #1 and #11 tracked; no legitimate line → `incident`.*
- [X] T024 [US1] Decide: freeze, or run F2.
  - If F1's tuning gates pass on e4b, the provisional pin is final.
  - Otherwise make **one** F2 edit to `classify_v3.md` that only moves the failing sentence back toward P2's
    measured text (plan §16), re-pin, re-run T021, and freeze if it passes.
  - If F2 also fails, **stop** and report per FR-216, with no further rounds.

  Record the decision and the final SHA-256 in `research.md` §2.
  - *Done 2026-10-04: **stopped under FR-216.** F1 failed Q1. F2, the operator's choice of edit (drop the
    mixed sentence), failed Q1 (extra #15) and Q6 (shipped #12 → `incident`). No hash is final: the working
    tree held F2 under a provisional pin only; it was removed on 2026-10-06 (contract §3 step 1). See
    research §2 "F2 and the stop" and "Closure".*

**Checkpoint**: `classify_v3` is frozen and pinned. US1–US3's tuning gates pass on e4b (or the milestone has
stopped under FR-216).

---

## Phase 5: User Story 5 — Checked on cases nobody tuned against (Priority: P2)

> **Blocked (2026-10-04):** T024 stopped under FR-216 and no hash is final, so the held-out set is not
> written. T025's test was drafted and then removed from the suite, because it fails while the file is
> absent. It can be restored when a freeze happens.

**Goal**: a held-out synthetic set written after the freeze and run once (FR-209, data-model §3).

**Independent Test**: the held-out file's composition test passes, and one qualification run reports Q2 and Q4.

- [ ] T025 [P] [US5] Write a failing test for the held-out set's composition in
  `apps/ai-api/tests/moderation/classification/test_heldout_fixtures.py`:
  - at least 38 `clear` lines and at least 8 `ambiguous` lines;
  - at least 10 clear-positive lines on which `evaluate([normalize(text)])` is False (rule-declined);
  - at least 80% of lines contain neither `؟` nor `?`;
  - every line passes `load_fixture_lines`;
  - no `tracked` key.
- [ ] T026 [US5] Write `apps/ai-api/app/scripts/attention_smoke_heldout_fixtures.jsonl` **only after T024's
  hash is final**:
  - about 50 synthetic lines following the data-model §3 grid;
  - topics apart from tuning: certificate, grades/results, homework submission, payment receipt, group link,
    exam hall/seat, meeting app, timetable file;
  - Saudi and Egyptian phrasing, and at least 8 near-pairs;
  - no real text, no names, no real numbers or links.

  Make T025 pass. Do not edit `classify_v3.md` afterwards (X2).
- [ ] T027 [US5] Rebuild the tools image and run the e4b qualification **once** with `classify_v3`. Record Q2,
  Q4 and the held-out ambiguous count in `research.md` §2. A failure is reported as it stands; there is no
  edit to v3 and no edit to the held-out labels (X4).

**Checkpoint**: e4b + v3 has a full development-reference result, `INCOMPLETE` only for want of the fresh
sample (Q9).

---

## Phase 6: User Story 6 — Known boundary cases tracked, not hidden (Priority: P3)

**Goal**: the closed list is visible on every run and has an exit path (FR-212, D-TG-176).

**Independent Test**: every qualification report shows exactly the two tracked lines with pass/fail, and a third
`tracked` line makes Q12 fail (covered by T008).

- [ ] T028 [US6] Check the T021 and T027 reports. Real moderation #1 (`no-link-rule`) and shipped moderation #11
  (`label-review`) each appear on the tracked line with pass/fail, and neither is in a Q5 or Q6 count. Note the
  result in `research.md` §2.
- [ ] T029 [US6] *(operator)* Review the label on shipped moderation #11. If ABUSE is confirmed, remove
  `tracked` from it, and it becomes a hard gate. If it should be COMPLAINT, instruct the single edit (FR-211).
- [ ] T030 [US6] *(operator, later)* When the deterministic no-link rule ships, remove `tracked` from real
  moderation #1 and re-qualify (quickstart §6).

---

## Phase 7: Polish and cross-cutting

- [ ] T031 *(operator)* Annotate the external fixtures in `~/Projects/injaz-m5-fixtures/` per quickstart §2:
  - `label_class: "ambiguous"` on the agreed lines;
  - `tracked: "no-link-rule"` on real moderation #1;
  - create `fresh-attention.jsonl`, 20–30 messages, labelled before any run.
- [ ] T032 [P] Amend `specs/008-tg-m5-ai-classification/contracts/classification-pipeline.md` with a dated
  note:
  - a §2b with `classify_v3` byte for byte, copied from the frozen file;
  - "Which one is sent" gains `classify_v3`;
  - the P3 and O5 mentions;
  - the measured table, counts only.

  Also amend `specs/008-tg-m5-ai-classification/data-model.md`: the `prompt_version` note gains
  `classify_v3`.
- [ ] T033 [P] Add dated pointer notes to 009, keeping history:
  - `specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md` G4: "both instructions" becomes "every
    instruction";
  - `specs/009-tg-m5-1-ai-attention/spec.md` and `specs/009-tg-m5-1-ai-attention/quickstart.md` §2 point to
    010's qualification;
  - `specs/009-tg-m5-1-ai-attention/research.md` Finding 9 is resolved by 010.
- [ ] T034 [P] Edit `.env.example`: the `MODERATION_PROMPT_VERSION` comment lists `classify_v3` (opt-in,
  qualify first). In `docs/runbooks/tg-operator-prerequisites.md` §C, add a TG-M5.2 row: annotations, fresh
  sample, production-host qualification and switch-on order (quickstart §4).
- [ ] T035 Run `make check` with Ollama quit. Everything is green: the new tests, the TG-M3, TG-M4, TG-M5 and
  TG-M5.1 suites untouched, and the v1 and v2 pins unchanged (SC-208).
- [ ] T036 Run a final self-review of the diff against `contracts/qualification.md` N1–N4 and
  `contracts/classify-v3.md` X1–X5 (no subagent unless the operator asks), and list any rulings made.
- [ ] T037 *(operator)* Production host: pull the candidates, register them inactive, run the qualification
  for each with `classify_v3`, pick the smallest `QUALIFIED` model, switch on in the quickstart §4 order, and
  run the C9 pilot (SC-206).

---

## Dependencies and execution order

- **Setup (T001)** comes first.
- **Foundational (T002–T006)** blocks everything.
  - T005 depends on T002 (tests first).
  - T003, T004 and T006 can run in parallel.
- **US4 (T007–T013)** depends on Foundational. T007 and T008 come before T009. T009 → T010 → T011 → T012 → T013.
- **US1–US3 (T014–T024)** depend on US4, because the freeze is measured through the command.
  - The tests T014–T018 come before T019 and T020.
  - T021 → T022, T023 → T024.
- **US5 (T025–T027)** depends on T024 (the hash is final). T025 → T026 → T027.
- **US6 (T028–T030)** depends on T021 and T027. T029 and T030 are the operator's, at any time after T021.
- **Polish:**
  - T032 needs T024 (the frozen bytes).
  - T033 and T034 can come at any time after T024.
  - T035 comes after all code tasks, and T036 last.
  - T031 and T037 are the operator's. T031 is needed before any `QUALIFIED` verdict; T037 is the production
    step.

### Parallel opportunities

- T003 ∥ T004 ∥ T006 (different files).
- T007 ∥ T008 (one file, written together).
- T014 ∥ T015 ∥ T016 ∥ T017 ∥ T018 (test files; T017 and T018 share `test_prompt_pinned.py` with T014, so
  write them together).
- T032 ∥ T033 ∥ T034 (different documents).

### Parallel example: Foundational

```text
T003 extract judge_attention_fixture   (smoke_attention.py)
T004 extract judge_moderation_fixture  (smoke_moderation.py)
T006 annotate shipped fixtures         (two .jsonl files)
```

## Implementation strategy

1. **MVP = Phase 2 + Phase 3 (US4).**
   - A working, read-only qualification command is useful on its own: it already shows e2b + v2 as
     `NOT QUALIFIED`, and it is what the production host needs.
2. **Then Phase 4:** freeze v3 in at most two rounds, or stop under FR-216.
3. **Then Phase 5:** held-out once.
4. **Phase 6 and Polish.**
5. **Production enablement (T037) is the operator's,** and only on a `QUALIFIED` pair.

## Notes

- **Stop conditions:** T024's second failure (FR-216), or any finding that needs a schema, TG-M5.1, rule or
  panel change (FR-214, FR-215). Stop and report; never work around them.
- **Never print, log or commit message text.** Real fixtures stay in `~/Projects/injaz-m5-fixtures/`.
