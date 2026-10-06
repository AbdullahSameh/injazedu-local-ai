# Implementation Plan: TG-M5.2 — classify_v3 and Model Qualification

**Branch**: none created. Git is operator-owned, so the work sits on `m5/ai-classification`.
**Date**: 2026-10-04
**Spec**: `spec.md`
**Contracts**: `contracts/classify-v3.md`, `contracts/qualification.md`
**Plan of record**: `docs/plan/telegram/tg-m5-classify-v3-plan.md` (§1–§4 analysis, §14 tuning, §16 larger
model)

## Summary

TG-M5.2 does three things:
1. **A third, opt-in instruction, `classify_v3`.** It decides needs-response by whether the writer is asking or
   informing (Policy S), keeps v2's advert and abuse wording byte-identical, and is frozen in at most two
   measured rounds.
2. **A read-only qualification command.** It judges one model profile and instruction pair over every benchmark
   set, keeps ambiguous and tracked lines out of the hard gates, and prints `QUALIFIED`, `NOT QUALIFIED` or
   `INCOMPLETE`.
3. **A held-out set,** written only after the freeze.

The production model is whichever candidate qualifies on the production host. The code is the same; only
evidence and configuration differ.

There is no migration and no schema, TG-M5.1, rule or panel change.

## Technical Context

- **Language/Version:** Python 3.12, the `apps/ai-api` service.
- **Primary Dependencies:**
  - the existing ones: SQLAlchemy async and Pydantic;
  - the M1 gateway (`app.application.gateway`), with a bare `Gateway(registry)` that records no accounting;
  - Ollama through the provider.

  Nothing new is added.
- **Storage:** PostgreSQL.
  - Only reads, for profile resolution.
  - Development gets new inactive `model_profiles` rows per candidate, through the panel or an insert.
  - No DDL.
- **Testing:** pytest with the model scripted. `make check` runs with Ollama quit. The live runs are operator and
  implementation evidence, not CI.
- **Target Platform:** the Docker Compose tools container (`migrate` image). Development is the 16 GB macOS
  machine; production is a powerful Linux host, not yet provisioned.
- **Project Type:** a web service plus worker, with an operator CLI command added.
- **Performance Goals:** p95 single classification ≤ 10 s on the qualified pair (Q10), so live predictions land
  inside the 90 s settle (SC-207).
- **Constraints:**
  - no message text in any output or log (check 4);
  - the command writes nothing (C2);
  - local-first;
  - v1 and v2 byte-identical;
  - at most v2 + 1,200 characters for v3.
- **Scale/Scope:** about 200 fixture lines per qualification, run twice. Measured: about 6 minutes on e4b on the
  development machine.

## Constitution Check

*GATE: must pass before Phase 0 research, and again after the Phase 1 design. It passes both times.*

**1. Which behaviours need tests, and which are exempt (I)?**
- **Tested:**
  - the gate Q1–Q12, pure, at every boundary, including `INCOMPLETE` and `--repeat` < 2;
  - label-class scoring;
  - the exclusion of tracked lines and the closed-list limit;
  - fixture-key validation (bad `label_class` or `tracked`; `label_class` on a moderation line);
  - repeat comparison;
  - latency percentiles;
  - that output carries no text;
  - that the extracted per-fixture functions leave the smokes' summaries unchanged (existing tests);
  - the allowlist, files and pins as one set (v1 and v2 hashes unchanged, v3 pinned);
  - the G4 sentence in every instruction;
  - config accepts `classify_v3` with the default unchanged;
  - v3's bytes are sent as `system`;
  - a v3 prediction stores `prompt_version = 'classify_v3'`.
- **Exempt:**
  - the Make target and the compose mount (configuration);
  - the live-model runs (operator evidence, recorded in `research.md`).
- **Not tested here:** the wording's quality. That is the qualification's job, by design.

**2. Do any tests touch a database (II)?**
- The pure scoring tests touch none.
- The `classify_one` case uses the existing `injaz_ai_test` fixtures.
- No PHP test changes.

**3. Anything inside `injazedu/` (III)?** No.

**4. Any Git actions (IV)?** None by the agent. Spec Kit's commit hooks are surfaced only; the operator commits.

**5. Is every task traceable to the spec (V)?**

| Work | Traces to |
|---|---|
| `classify_v3` | FR-201 to FR-205 |
| The command | FR-206 to FR-208 |
| The held-out set | FR-209 |
| The production rule (operator) | FR-210 |
| Labels and tracking | FR-211, FR-212 |
| Invariants | FR-213 to FR-215 |
| The fallback | FR-216 |

No unrelated refactor. The one refactor, extracting the per-fixture judgement, exists so that the command
reuses the smokes and avoids a second definition (D-TG-178).

**Architecture rules (`make check`):**
- `app/scripts/qualify_moderation.py` is a composition root (`app/scripts/` is exempt by directory).
- The domain modules stay pure; no domain module changes.
- No `httpx`, `ollama` or `openai` import outside providers. The smokes' existing reachability probe is reused,
  not duplicated.

## Project Structure

### Documentation (this feature)

```text
specs/010-tg-m5-2-classify-v3/
├── spec.md                  # FR-201…216, SC-201…208, clarifications 2026-10-04
├── plan.md                  # this file
├── research.md              # Findings 10–13, D-TG-172…181, §2 qualification runs (filled during work)
├── data-model.md            # no DDL; fixture keys; sets; held-out grid; the printed result
├── quickstart.md            # annotate, qualify (dev reference, production host), switch on, pilot, rollback
├── contracts/
│   ├── classify-v3.md       # V1–V7, starting draft F1, freeze protocol, X1–X5
│   └── qualification.md     # the command C1–C5, sets, scoring S1–S6, gate Q1–Q12, R1–R3, N1–N4
├── checklists/requirements.md
└── tasks.md                 # /speckit-tasks
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/prompts/moderation/classify_v3.md                    # NEW: frozen per contracts/classify-v3.md §3
├── app/infrastructure/config.py                             # ModerationPromptVersion += "classify_v3" (default unchanged)
├── app/scripts/
│   ├── qualify_moderation.py                                # NEW: the command, a composition root
│   ├── smoke_attention.py                                   # extract judge_attention_fixture(); output unchanged
│   ├── smoke_moderation.py                                  # extract judge_moderation_fixture(); output unchanged
│   ├── attention_smoke_fixtures.jsonl                       # + label_class on #4, #5, #6 (annotation only)
│   ├── moderation_smoke_fixtures.jsonl                      # + tracked "label-review" on #11 (annotation only)
│   └── attention_smoke_heldout_fixtures.jsonl               # NEW: written after the freeze
└── tests/moderation/classification/
    ├── test_qualification_scoring.py                        # NEW: S1–S6, Q1–Q12, verdicts, no text
    ├── test_qualification_fixtures.py                       # NEW: key validation, closed list
    ├── test_prompt_pinned.py                                # + v3 pin; v1/v2 unchanged; G4 sentence in every instruction
    ├── test_prompt_version.py / test_config_classification.py   # + classify_v3 accepted; default classify_v1
    ├── test_model_input.py                                  # + v3 bytes as system
    └── test_classify_one.py                                 # + v3 prompt_version stored
Makefile                                                     # + qualify-moderation (read-only fixtures mount)
.env.example                                                 # MODERATION_PROMPT_VERSION comment lists classify_v3
```

**Documentation amendments** (dated notes, history kept; D-TG-181):

| File | Change |
|---|---|
| `specs/008-…/contracts/classification-pipeline.md` | §2b `classify_v3` byte for byte; "Which one is sent"; the measured table |
| `specs/008-…/data-model.md` | the `prompt_version` note |
| `specs/009-…/contracts/attention-opening.md` | G4's "both" becomes "every instruction" |
| `specs/009-…/spec.md`, `specs/009-…/quickstart.md` | pointer notes to 010 |
| `docs/runbooks/tg-operator-prerequisites.md` §C | a TG-M5.2 row: annotations, fresh sample, production qualification |
| `CLAUDE.md` | the active feature |

**Structure Decision:** this is the existing `apps/ai-api` layout. There is no new package or service, and the
PHP control panel is untouched (FR-215).

## Implementation order (for `/speckit-tasks`)

1. **Tests first:** the qualification scoring and gate (pure), and fixture-key validation. Watch them fail.
2. **The per-fixture judgement**, extracted in both smokes. Their existing scoring tests stay green.
3. **`qualify_moderation.py`** and the Make target.
4. **The shipped-set annotations:** `label_class` on attention #4–#6, `tracked` on moderation #11.
5. **The freeze, F1 and then possibly F2:**
   - write `classify_v3.md` (the starting draft);
   - add the allowlist entry, the provisional pin and the tests;
   - qualify on e4b and e2b;
   - freeze or stop (FR-216).
6. **The held-out set**, written after the freeze, its "rule-declined" lines checked with `evaluate` first. Run
   it once on e4b and record the result.
7. **The documentation amendments** and `research.md` §2 counts.
8. `make check` with Ollama quit.
9. **Operator, outside the agent's tasks:**
   - annotate the external fixtures;
   - build the fresh sample;
   - review the labels;
   - run the production-host qualification;
   - switch on and run the pilot.

## Complexity Tracking

No constitution violations. The single refactor, extracting the per-fixture judgement from two scripts,
replaces a second definition the command would otherwise need (D-TG-178).

## Progress

| Phase | Status |
|---|---|
| Analysis, tuning and the larger-model measurement | ✅ 2026-10-04 (plan of record §1–§16) |
| Spec and clarifications | ✅ 2026-10-04 |
| Plan: research, data model, contracts, quickstart | ✅ 2026-10-04 |
| Tasks | ✅ 2026-10-04 |
| Implementation and the development reference qualification | ✅ Phases 1–3 (qualification) · ⛔ Phase 4 stopped under FR-216 (F1, F2) |
| Fresh sample, label review, production-host qualification, pilot | ⛔ not for v3. The label review and fresh sample carry over to TG-M5.3 |
| Closure | **Stopped under FR-216 (2026-10-06).** The provisional `classify_v3` was removed; development is back on e2b + `classify_v2`. Next: `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md` |
