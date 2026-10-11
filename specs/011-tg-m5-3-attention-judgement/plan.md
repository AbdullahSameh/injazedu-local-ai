# Implementation Plan: TG-M5.3 — A Separate Attention Judgement

**Branch**: none created. Git is operator-owned (constitution IV), so the work sits on `m5/ai-classification`.
**Date**: 2026-10-07
**Spec**: `spec.md`
**Contracts**:
- `contracts/dismissal-reasons.md` (Story 1);
- `contracts/attention-judgement.md`;
- `contracts/attention-metrics.md`;
- `contracts/qualification.md` (version 2).

**Plan of record**: `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md` (approved 2026-10-06; amendments
approved 2026-10-07)

## Summary

TG-M5.3 gives the question "does this message need the team?" its own task. It ships in two independent parts.

1. **Story 1: dismissal reasons** (no schema, no model).
   - A "Member discussion" dismissal on the Live Attention Queue.
   - A per-reason breakdown beside every dismissal count on Classification Accuracy, with every existing value
     unchanged.
   - Corrected wording: "dismissed (any reason)".
2. **The attention judgement** (revision `0008`).
   - **Dispatch and recording:** at ingest, each message is dispatched to a separate, pinned instruction
     (`attention_v1`) on its own model role. Its intent is recorded, one of six: `asking`, `discussion`,
     `informing`, `social`, `offering`, `other`. Needs-response is derived as `intent == "asking"`.
   - **Opening:** `open_item` reads that judgement, never the classification's needs-response, after the rules
     decline. Members the classification calls an advert or abuse are vetoed.
   - **Qualification** is split into a task-agnostic core with an attention suite (A1–A9) and a moderation suite
     (010's advert gates). The wording is chosen by a fixed selection protocol, then a held-out run and the
     operator's fresh sample.
   - **Coverage and timeliness figures** (C10) measure shadow mode and the burst limitation L-B1.

**What is unchanged:**
- `classify_v2` stays byte-identical, along with routing, thresholds, incidents and TG-M4.
- TG-M3's rule set and bursts.
- The gateway and redaction.

## Technical Context

- **Language/Version:** Python 3.12 (`apps/ai-api`) and PHP ^8.2 / Laravel 12 / Filament 5 (`apps/ai-control`),
  both existing.
- **Primary Dependencies:**
  - SQLAlchemy async, Pydantic, Alembic and Dramatiq 2.2.1 (Redis broker);
  - the M1 gateway (`app.application.gateway`) and the Ollama provider.

  Nothing new is added.
- **Storage:** PostgreSQL. One additive revision, `0008_moderation_attention_judgement` (data-model §1–§4).
  Story 1 has no DDL.
- **Testing:**
  - pytest with the model scripted, on `injaz_ai_test`;
  - PHPUnit feature tests with `DatabaseTransactions` on `injaz_ai_test`;
  - `make check` with Ollama quit.

  Live qualification runs are evidence, recorded in `research.md` §2, not CI.
- **Target Platform:** Docker Compose on the 16 GB macOS development host, and a powerful Linux production host
  (not yet provisioned) that runs its own qualification.
- **Project Type:** a web service, workers and an operator CLI (`apps/ai-api`), plus an admin panel
  (`apps/ai-control`).
- **Performance Goals:**
  - A8: single attention call p95 ≤ 10 s;
  - SC-306: at least 95% of live judgements land by `sent_at + MODERATION_BURST_GAP_S`, under normal load.
- **Constraints:**
  - no message text in any log or report (check 4);
  - the qualification writes nothing;
  - local-first;
  - `classify_v1` and `classify_v2` hashes unchanged;
  - no burst-level model input;
  - concurrency and ordering are deployment configuration, not contract (D-TG-187).
- **Scale/Scope:**
  - about 2 model calls per eligible message, less the AE2 share (plan §10: about 5–25%);
  - the qualification matrix is 3 candidates × 2 models × 2 repeats over about 150 lines.

## Constitution Check

*GATE: it must pass before Phase 0, and again after the Phase 1 design. It passes both times.*

**1. Which behaviours need tests, and which are exempt (I)?**
- **Tested** (AI pipeline, idempotency, data integrity, business rules):
  - **The domain:** the intent derivation, AE1–AE2, A1–A2 and V (pure).
  - **`judge_one`:** exclusions recorded once; failures appended; transient retry; no call with the prompt
    blank or no profile; the idempotent insert; `request_rejudgement` only when live, needs-response true and the
    switch is set.
  - **`open_item`:** rules first; the attention link; the veto; G5–G6; reconciliation in Case A and Case B;
    `ck_attention_ai_link` rejecting zero or two links.
  - **Independence:** each judgement records and opens with the other absent, failed or late.
  - **The migration's constraints,** with planted violations.
  - **The pin test:** two allowlists, every file in exactly one.
  - **Fixture-key validation,** the rule-declined `peer` check, and S1/S1b scoring.
  - **The gates:** A1–A9 and the moderation gates at every boundary; the candidate verdict; the no-text output.
  - **The figures:** C9′, C10 and the breakdowns (sum of parts) in Python and PHP.
  - **The dismissal action:** recorded once, guarded.
- **Exempt:**
  - Make targets, compose wiring and the seed rows (configuration);
  - the panel's role option (framework);
  - live-model qualification runs (operator evidence).
- **Not tested here:** wording quality. That is the qualification's job.

**2. Do any tests touch a database (II)?** Yes.
- **Python:** the existing `injaz_ai_test` fixtures (`TEST_DATABASE_URL`, `.env.testing`).
- **PHP:** `DatabaseTransactions` against `injaz_ai_test`. Never `RefreshDatabase`, `DatabaseMigrations` or
  `migrate:fresh`.
- **Development database:** only read-only counts were taken (research Findings 15 and 19).

**3. Anything inside `injazedu/` (III)?** No.

**4. Any Git actions (IV)?** None by the agent. Spec Kit's commit hooks are surfaced only, and no branch is
created.

**5. Is every task traceable to the spec (V)?**

| Work | Traces to |
|---|---|
| Dismissal action, breakdowns, wording | FR-301–FR-306 |
| Instruction, setting, request, schema, Policy D | FR-307–FR-310 |
| Eligibility, record, failures, independence, role, shadow, live only | FR-311–FR-317 |
| Opening, link, reconciliation, removal of the classification opener | FR-318–FR-323 |
| Qualification core, suites, keys, selection protocol, sets | FR-324–FR-333 |
| C9′, C10, panel reads only | FR-334–FR-337 |
| Invariants, L-B1, one revision, no runtime in checks | FR-338–FR-341 |

**Refactors and their reasons:**
- **The qualification script is split into core and suites** (D-TG-194). Without the split, the attention suite
  would be a second definition of sets, repeat, latency and verdicts.
- **`smoke_attention.py` is re-pointed** (D-TG-195) so there is one benchmark path, not two.

No other refactor.

**Architecture rules (`make check`):**
- All new Python modules sit under the permitted moderation prefixes:
  - `app/domain/moderation/attention_judgement.py` is pure;
  - `app/application/moderation/attention_judgement.py`;
  - `app/workers/tasks/moderation/judge_attention.py`.
- `app/scripts/qualification/` is a composition root, exempt by directory.
- No `httpx`, `ollama` or `openai` import outside providers.
- No text in log lines (`redacted_text` binding only).

## Project Structure

### Documentation (this feature)

```text
specs/011-tg-m5-3-attention-judgement/
├── spec.md                         # FR-301…341, SC-301…310, clarifications 2026-10-06/07
├── plan.md                         # this file
├── research.md                     # Findings 14–19, D-TG-182…199, §2 qualification runs (during work)
├── data-model.md                   # revision 0008, close_reason vocabulary, settings, fixture keys, domain values
├── quickstart.md                   # story 1, migrate, prerequisites, selection, freeze, shadow, pilot, rollback
├── contracts/
│   ├── dismissal-reasons.md        # K1–K12: the action, unchanged counts, breakdown, wording
│   ├── attention-judgement.md      # J, AE, P, S, Policy D, A1–A2/V, W, F, L, N, limitations
│   ├── attention-metrics.md        # C9′ (two eras), C10a–c, M23′–M32
│   └── qualification.md            # v2: command, sets, keys, S1–S6, A1–A9 + Q5–Q12, reported lines, W-1…W-7
├── checklists/requirements.md
└── tasks.md                        # /speckit-tasks
```

### Source Code (repository root)

```text
apps/ai-api/
├── alembic/versions/0008_moderation_attention_judgement.py          # NEW (data-model §1–§4, §6)
├── app/domain/model_profile.py                                      # Role, GenerationRole += "attention"
├── app/domain/moderation/attention_judgement.py                     # NEW, pure: INTENTS, needs_response_for, attention_exclusion, judgement_proposes, vetoed
├── app/domain/moderation/classification.py                          # − proposes_attention, − NO_RESPONSE_CATEGORIES
├── app/application/moderation/attention_judgement.py                # NEW: AttentionJudgementResult, build_attention_input, judge_one, record_attention_failure
├── app/application/moderation/attention.py                          # _model_proposal reads judgements + V; attention_judgement_id; ai_attention_from_settings needs both settings
├── app/application/moderation/classification.py                     # − request_rejudgement call (W3)
├── app/application/moderation/messages.py                           # judge_attention.send before classify_message.send (J1)
├── app/workers/tasks/moderation/judge_attention.py                  # NEW actor: queue moderation_attention, priority 0, task-level retry
├── app/workers/tasks/moderation/classify_message.py                 # priority=10
├── app/workers/main.py                                              # register judge_attention
├── app/infrastructure/config.py                                     # ATTENTION_PROMPT_VERSIONS (empty until the freeze), MODERATION_ATTENTION_PROMPT_VERSION + validator (D-TG-189)
├── app/infrastructure/models.py                                     # model_profiles role check
├── app/infrastructure/models_moderation.py                          # the two tables; attention_items.attention_judgement_id
├── app/prompts/moderation/attention_v1.md                           # NEW, Phase 4 (after selection)
├── app/scripts/qualification/{__init__,__main__,core,attention,moderation}.py   # NEW (D-TG-194)
├── app/scripts/qualify_moderation.py                                # thin wrapper over the moderation suite
├── app/scripts/smoke_attention.py                                   # re-pointed to judge_attention_line (D-TG-195)
├── app/scripts/seed_profiles.py                                     # + the two inactive attention profiles
├── app/scripts/attention_validation_fixtures.jsonl                  # NEW, before selection (peer lines rule-declined)
├── app/scripts/attention_burst_fixtures.jsonl                       # NEW, before selection
├── app/scripts/attention_heldout_fixtures.jsonl                     # NEW, after the freeze
└── tests/moderation/
    ├── attention_judgement/                                         # NEW
    │   ├── test_domain.py                                           # derivation, AE1/AE2, A1/A2, V
    │   ├── test_judge_one.py                                        # record, exclusions, failures, claim, prompt blank, rejudgement
    │   ├── test_judge_attention_retry.py                            # F1 backoff, final failure row
    │   ├── test_dispatch.py                                         # J1 order and condition
    │   ├── test_opening.py                                          # open_item via judgement, V, link check, Case A/B, eras
    │   ├── test_independence.py                                     # each side with the other absent / failed / late
    │   ├── test_migration_0008.py                                   # planted violations, downgrade
    │   ├── test_metrics_attention.py                                # C9′, C10a–c, breakdown sums
    │   └── test_attention_fixture_files.py                          # keys valid; in-repo peer lines rule-declined
    ├── classification/
    │   ├── test_prompt_pinned.py                                    # two allowlists; G4 on classify_* only
    │   ├── test_ai_attention.py, test_attention_gate.py             # re-pointed to the judgement (G1–G4 → A1/A2/V)
    │   ├── test_classify_one.py                                     # no request_rejudgement (W3)
    │   ├── test_config_classification.py                            # the new setting; blank default
    │   ├── test_metrics_model_opened.py                             # breakdown columns; era rows
    │   └── test_qualification_*.py                                  # moved to core/suites; A1–A9, S1b, R-lines, CANDIDATE
apps/ai-control/
├── app/Filament/Pages/LiveAttentionQueue.php                        # dismiss_member_discussion (K1–K4)
├── app/Filament/Pages/Concerns/ClassificationMetrics.php            # breakdown on C7, C9′ union
├── app/Filament/Pages/Concerns/AttentionJudgementMetrics.php        # NEW: C10a–c
├── app/Filament/Pages/ClassificationAccuracy.php                     # attention sections
├── resources/views/filament/pages/classification-accuracy.blade.php # wording (K11), breakdowns, attention blocks
├── app/Filament/Resources/ModelProfiles/{Schemas/ModelProfileForm,Tables/ModelProfilesTable}.php   # 'attention' option
├── config/moderation.php                                            # burst_gap_s
└── tests/Feature/
    ├── AttentionDismissTest.php                                     # + member discussion
    ├── ModelViewDisplayTest.php                                     # + action exists
    ├── ModelOpenedQuestionsTest.php                                 # breakdown shape; new wording; eras
    ├── DismissalBreakdownTest.php                                   # NEW: sums; unchanged values (SC-301)
    └── AttentionJudgementFiguresTest.php                            # NEW: C10a–c
infra/docker-compose.yml          # ai-classifier --queues moderation_attention moderation_classify; MODERATION_ATTENTION_PROMPT_VERSION on ai-worker and ai-classifier; MODERATION_BURST_GAP_S on ai-control
Makefile                          # qualify (TASK=…), qualify-moderation alias, smoke-attention re-pointed
.env.example                      # MODERATION_ATTENTION_PROMPT_VERSION (blank)
```

**Documentation amendments.** These are dated notes; the history is kept.

| File | Change |
|---|---|
| `specs/006-…/spec.md` FR-051; `data-model.md` (`close_reason`; `attention_items.attention_judgement_id`) | dismissal-reasons §5; data-model §3 |
| `specs/006-…/contracts/control-panel-attention.md` §2; `attention-metrics.md` §3 M10, §5 | dismissal-reasons K2, K6, K7 |
| `specs/008-…/contracts/classification-pipeline.md` R13, N1, F6 | the classifier no longer requests re-judgement; needs-response is measurement only again |
| `specs/008-…/contracts/classification-metrics.md` C7, §8a | K7, K8, K10; C9′ points to `attention-metrics.md` |
| `specs/008-…/contracts/control-panel-classification.md` §4 | K11; the attention sections |
| `specs/008-…/data-model.md` | the `attention` role; the item's second link |
| `specs/009-…/contracts/attention-opening.md` §1–§3, §9 | G1–G4 superseded by A1/A2/V; O3 link; I1 caller; L-B1 |
| `specs/009-…/quickstart.md` §5 | K11 |
| `specs/010-…/contracts/qualification.md` | superseded by 011's version 2; the alias is kept |
| `docs/plan/telegram/telegram-moderation-intelligence.md` | the revision reservation note (D-TG-192) |
| `docs/runbooks/tg-operator-prerequisites.md` §C | a TG-M5.3 row: Policy D, T031 with intents, the fresh sample, qualify, shadow, switch |
| `CLAUDE.md` | the active feature |

**Structure Decision:** the existing two-app layout. There is no new service, package or dependency. The
attention judgement mirrors the classification's files one for one.

## Implementation order (for `/speckit-tasks`)

1. **Story 1, deployable alone.** Panel action; breakdowns on C7 and C9; wording; PHP and Python figure tests;
   the 006/008/009 notes for K-clauses.
2. **Foundation.**
   - revision `0008` and its constraint tests;
   - ORM metadata; the role literals and option; the seed rows;
   - settings; the domain module with pure tests.
3. **The judgement.** `judge_one`, the actor, dispatch, retry and the compose wiring, with tests, test-first.
   `attention_v1.md` does not exist yet; tests use a test-only instruction fixture.
4. **Opening.** Re-point `_model_proposal`; V; the link; `ai_attention_from_settings`; remove the classifier's
   request and `proposes_attention`; re-point TG-M5.1's tests.
5. **Qualification version 2.** Core and suites; candidate mode; keys; S1b; reported lines; the alias; the smoke
   re-pointed; tests.
6. **Figures.** C9′ union, C10a–c, the panel sections, tests.
7. **Fixtures (agent, before selection).** The validation set (~40 lines, ~12 peer, rule-declined, checked) and
   the burst set; the fixture-file test.
8. **Selection** (operator prerequisites first: Policy D confirmed, T031 with intents).
   - Write W1–W3 outside the repository, record hashes, run the matrix, apply W-3.
   - Allow at most one revision, then freeze `attention_v1.md` with its pin and allowlist. **Or stop** (W-7).
9. **Held-out** (after the freeze). Write it, check it with `evaluate`, run it once, and record the counts.
10. **Documentation amendments,** then `make check` with Ollama quit.
11. **Operator, outside the agent's tasks:** the fresh sample, the production-host qualification, the shadow
    week, switch-on and the pilot.

## Complexity Tracking

No constitution violations. The two refactors are justified under Constitution Check 5: the qualification split
and the smoke re-point.

## Progress

| Phase | Status |
|---|---|
| Plan of record and amendments | ✅ 2026-10-06 / 2026-10-07 |
| Spec | ✅ 2026-10-07 |
| Plan: research, data model, contracts, quickstart | ✅ 2026-10-07 |
| Tasks | ✅ 2026-10-07 (82 tasks; Story 1 first) |
| Implementation: Phase 1 (baselines) and Story 1 (T001–T013) | ✅ 2026-10-07 |
| Implementation: Phase 3, Foundational (T014–T026) | ✅ 2026-10-07 |
| Implementation: Phase 4, US2 shadow mode (T027–T039) | ✅ 2026-10-07 |
| Implementation: Phase 5, US3 opening from the judgement (T040–T047, T049–T051) | ✅ 2026-10-07 (T048's deletion deferred to T060) |
| Implementation: Phase 6, US5 qualification version 2 (T052–T062, with T048) | ✅ 2026-10-07 |
| Implementation: Phase 7, US4 validation set (T063–T064) | ✅ 2026-10-07 |
| Implementation: Phase 8, US7 burst fixtures and C10c (T065–T069) | ✅ 2026-10-07 |
| Implementation: Phase 10 (T078–T082) | ✅ 2026-10-09: dated TG-M5.3 notes in 006/008/009/010, the revision reservation, the runbook row; `make check` at T001's baseline |
| Selection, freeze, held-out (T070–T076) | ✅ 2026-10-07: `attention_v1` frozen (W2R, e4b); held-out A4 PASS; `INCOMPLETE` until the fresh sample |
| Fresh sample and qualification (T077) | ✅ 2026-10-08: e4b + `attention_v1` `QUALIFIED`; moderation `QUALIFIED`, per-line status as T002 (SC-305) |
| Policy D′ and `attention_v2` (addendum, Phase 9b T083–T095) | 2026-10-09: addendum approved with every recommended option. T083 ✅: D′ recorded in the spec, the contracts, the plan of record, research (D-TG-200), the data model, the quickstart and tasks. `attention_v1` frozen as history; no model run yet. T084 (operator) and T085 ✅: the 37-line sample is relabelled under D′ and is now tuning (`real-attention-fresh-v1.jsonl`). T086 ✅: the v1 held-out set is renamed (byte-identical, pinned) and is a validation set; A3 is judged per validation set. T087 ✅: `attention_validation_scope_fixtures.jsonl` (18 lines), written before any v2 candidate. T088 ✅: `make check` gives T001's baseline outcome (PHP 139 OK; the 4 known secret-scan failures). T089–T091 ✅: no V2 candidate passed, nor V2-AR after the one revision. **Stopped under W-7′**: no `attention_v2`, and T092–T095 skipped. Opening stays rules-only |
| Shadow, pilot | — not reached: no attention instruction qualified under Policy D′; opening stays rules-only |
| **Milestone** | **Closed 2026-10-09.** Story 1 ships. The attention judgement is complete and switched off. `attention_v2` stopped under W-7′ |
