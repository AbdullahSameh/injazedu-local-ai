---
description: "Task list for TG-M0 — Moderation Intelligence Domain Foundation"
---

# Tasks: TG-M0 — Moderation Intelligence Domain Foundation

**Input**: Design documents from `specs/003-tg-m0-moderation-foundation/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts, data
integrity and security boundaries, and `plan.md`'s Constitution Check enumerates the eleven
behaviours that earn one, each mapped to an FR/SC. Behaviours named exempt there — the package
directories, `.env.example` contents, the empty provider and worker skeletons, documentation — get
**no** test task here.

Three of those tests assert that a *shell script fails*. That is deliberate and is argued in
`plan.md` → Complexity Tracking: in this milestone the gate rules **are** the deliverable, and a grep
that matches nothing passes silently forever.

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US5, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its tests at
`apps/ai-api/tests/`, operator scripts at `scripts/`, `.env.example` and `CLAUDE.md` at the root.
**No `apps/ai-control/` work in this milestone** — TG-M0 has no UI.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The package boundary must physically exist before any check can scan it. Nothing here
has behaviour.

- [X] T001 Create the four moderation package skeletons, each with an `__init__.py` carrying a one-line docstring naming its layer: `apps/ai-api/app/domain/moderation/`, `apps/ai-api/app/application/moderation/`, `apps/ai-api/app/providers/telegram/`, `apps/ai-api/app/workers/tasks/moderation/` (FR-001, D-TG-17)
- [X] T002 [P] Create the test package `apps/ai-api/tests/moderation/__init__.py`, mirroring how `tests/gateway/` was added for M1 (D-TG-17)
- [X] T003 [P] Add the five moderation variables with their documented defaults to `.env.example`, copying the block verbatim from `specs/003-tg-m0-moderation-foundation/contracts/environment.md` §1 — `TELEGRAM_BOT_TOKEN` empty, never a placeholder that looks like a token (FR-011)

**Checkpoint**: The four directories exist, so the Phase 3 greps cannot fail with "no such directory".

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: One operator decision that gates the milestone's acceptance, and the fixture set two
user stories both need.

**⚠️ CRITICAL**: T004 blocks *acceptance* of US1 and US4. Implementation of every story can proceed
without it, but `make check` cannot go green until it is resolved.

- [X] T004 ⚠ **OPERATOR DECISION — resolve the six pre-existing `scripts/scan_secrets.sh` false positives** so `make check` is green *before* TG-M0's own rule lands in that script. All six are false positives (`held_token`/`recovered_token` locals in `apps/ai-api/tests/gateway/test_lanes.py`, `MIGRATOR_PASSWORD="$(grep …)"` in `scripts/test_db_reset.sh`, and `scripts/scan_secrets.sh` detecting its own three pattern definitions). Four options with their trade-offs are in `plan.md` → **Blocking Prerequisite Discovered During Planning**. Narrowing a secret scanner changes what the repository considers a secret, so Constitution Principle V makes this the operator's call, not the agent's. **Resolved**: operator chose "exempt `scan_secrets.sh` from itself + rename the `_token`/`PASSWORD` locals" — keeps full existing coverage. `scan_secrets.sh` now skips its own path in the `KEY=value` heuristic only (fixed-signature checks still run on it); `held_token`→`held_lease`, `recovered_token`→`recovered_lease` in `test_lanes.py`; `MIGRATOR_PASSWORD`→`MIGRATOR_PW` in `test_db_reset.sh`. `bash scripts/scan_secrets.sh` now exits 0.
- [X] T005 [P] Create the Arabic fixture set in `apps/ai-api/tests/moderation/fixtures/arabic_messages.py`: the three measured equivalence classes from `research.md` §0, the edge cases from `spec.md` (empty, whitespace-only, emoji-only, link-only, code-switched Arabic/Latin), and one message carrying each of the four redaction patterns. Used by US2 and US3.

**Checkpoint**: Fixtures exist; the acceptance blocker is on the operator's desk rather than
discovered at the end.

---

## Phase 3: User Story 1 — The domain boundary refuses to be crossed (Priority: P1) 🎯 MVP

**Goal**: A developer who imports across the domain boundary, in either direction, or reaches for a
Telegram SDK outside the provider, is stopped by `make check` with a message naming the file.

**Independent Test**: Plant each of the three violations in turn, run `make check`, confirm it fails
and names the file; remove them and confirm it passes. No credential, database or model involved.

### Tests for User Story 1

- [X] T006 [US1] Write the planted-violation harness and its three failing tests in `apps/ai-api/tests/moderation/test_boundary_checks.py`: each writes a temporary violating module, invokes the relevant check, and asserts a non-zero exit whose output names the file. Keep the plants inside `tmp_path` or restore the file in a `finally` — a test that leaves a violation behind poisons every later run (FR-005, SC-002)

### Implementation for User Story 1

- [X] T007 [US1] Add the **forward allowlist** check to `scripts/check.sh`: any `import app.X` under the four moderation directories fails unless `app.X` starts with one of the seven permitted prefixes in `contracts/domain-boundary.md` §2. Use the existing `if grep …; then echo … >&2; exit 1; fi` form — a bare `grep` exits 1 on no match and would abort the gate on a clean tree under `set -euo pipefail` (FR-002, FR-003, D-TG-18)
- [X] T008 [US1] Add the **reverse** check to `scripts/check.sh`: no module under `app/domain/`, `app/application/`, `app/providers/` or `app/api/`, outside the moderation and telegram subdirectories, may import `app.*moderation*` or `app.providers.telegram`. Composition roots — `app/main.py`, `app/workers/`, `app/scripts/` — are exempt by directory, per `contracts/domain-boundary.md` §3 (FR-002)
- [X] T009 [US1] Add the **Telegram SDK** check to `scripts/check.sh`: no `telegram`, `aiogram`, `telebot`, `pyrogram` or `telethon` import outside `app/providers/telegram/`. Give each of the three checks its own failure message — three rules collapsed into one grep produce one unhelpful error for three unrelated mistakes (FR-004, D-TG-19)

**Checkpoint**: The boundary is mechanical. This is the milestone's structural value and the only
part that cannot be retrofitted later without unpicking work. **MVP.**

---

## Phase 4: User Story 2 — Arabic questions match regardless of how they were typed (Priority: P2)

**Goal**: A normalised form exists for every message, the original is untouched, and the same
question typed five ways collapses to one string.

**Independent Test**: Run the fixture set through `normalize` and assert the expected form for each,
that the input is unchanged, and that a second pass changes nothing.

### Tests for User Story 2

- [X] T010 [P] [US2] Write failing tests in `apps/ai-api/tests/moderation/test_normalize.py` against `contracts/moderation-text.md` §2's worked-examples table: the three equivalence classes each collapse to one form; idempotence over the whole fixture set; the input string unmodified; emoji and Latin runs survive; ⚠ **digit runs survive unaltered** — the D-TG-21 regression, which no test of the redactor alone would catch (FR-015–FR-020, SC-007, SC-008, SC-009)

### Implementation for User Story 2

- [X] T011 [US2] Implement `normalize(text: str) -> str` in `apps/ai-api/app/application/moderation/text.py` as the seven ordered steps in `contracts/moderation-text.md` §2. Two details that are easy to get wrong and are measured: NFKC does **not** fold Arabic-Indic/Eastern digits or strip tatweel, so both need explicit handling; and step 2 must strip bidi and format marks while **preserving ZWJ U+200D**, which emoji sequences are built from. Collapse repeated **letters** only, threshold 3 (FR-015–FR-021, D-TG-20, D-TG-21)

**Checkpoint**: TG-M3's rule set has a stable string to match against.

---

## Phase 5: User Story 3 — Nothing identifying reaches a model (Priority: P3)

**Goal**: Contact details, links and handles are replaced by fixed placeholders before text can leave
the domain, and the rule that identity never becomes a model input is written down for TG-M5.

**Independent Test**: Run the fixture set through `redact` and assert each pattern is replaced, the
surrounding text is unchanged, overlapping cases are deterministic, and a second pass changes
nothing.

### Tests for User Story 3

- [X] T012 [P] [US3] Write failing tests in `apps/ai-api/tests/moderation/test_redact.py` against `contracts/moderation-text.md` §3's worked-examples table: each of the four patterns replaced by its placeholder; `https://x.com/@someone` yields one `«رابط»` and not a nested substitution; idempotence; clean text returned unchanged; short numbers (a year, a lecture number) survive (FR-022, FR-026, SC-010)

### Implementation for User Story 3

- [X] T013 [US3] Implement `redact(text: str) -> str` in `apps/ai-api/app/application/moderation/text.py` — the four patterns in the fixed order URL → email → handle → digit run, with the Arabic placeholders from `contracts/moderation-text.md` §3. The order is forced by containment, not preference: an email contains `@`, a URL contains both. Idempotence needs no guard code — no placeholder matches any pattern. Depends on T011: same file (FR-022, FR-023, FR-026, D-TG-22)

**Checkpoint**: The text pipeline is complete. `contracts/moderation-text.md` §4 is the written rule
TG-M5's request builder must follow; TG-M0 ships no call site to enforce it against (D-TG-23).

---

## Phase 6: User Story 4 — The system runs, and its gate passes, with no Telegram credential (Priority: P4)

**Goal**: Absence of the credential is a fully supported state, and a bad duration is refused at
startup rather than discovered by a purge job.

**Independent Test**: `make check` with the variable unset, and again with it set empty — both pass.
`MODERATION_TEXT_RETENTION_DAYS=0 make check` exits 1 naming that variable.

### Tests for User Story 4

- [X] T014 [P] [US4] Write failing tests in `apps/ai-api/tests/moderation/test_config_moderation.py`: each of the three durations rejects zero and negative with a message naming the variable; an empty `TELEGRAM_ALLOWED_UPDATES` is rejected; `Settings` loads with `TELEGRAM_BOT_TOKEN` absent **and** with it empty, yielding `None` in both cases (FR-008, FR-010, SC-005)

### Implementation for User Story 4

- [X] T015 [US4] Extend `Settings` in `apps/ai-api/app/infrastructure/config.py` with the five fields from `data-model.md` §1, typed per that table — `telegram_bot_token: str | None = None`, not `str = ""`, so "not configured" and "configured empty" are one state. Add three `@model_validator(mode="after")` positivity checks in the shape M1 already uses, so `load_settings()` prints `Configuration error: <FIELD>: <msg>` and exits 1 with no stack trace. These are data-safety checks: `MODERATION_TEXT_RETENTION_DAYS=0` reaching TG-M10's purge would null every message text on its first run (FR-007–FR-012, D-TG-26). Also required a `field_validator(mode="before")` coercing `TELEGRAM_BOT_TOKEN=""` to `None` — pydantic does not do this on its own for `str | None`, and the contract requires "" and unset to be one state.

**Checkpoint**: The gate runs on a machine that holds no credential, which the runbook requires and
every later milestone depends on.

---

## Phase 7: User Story 5 — Traceable, text-free logs (Priority: P5)

**Goal**: A moderation event can be followed through the logs by identifier, message text
structurally cannot reach them, and a credential pasted into a document is caught.

**Independent Test**: Emit records carrying each whitelisted key and confirm each appears; emit an
unlisted key and confirm it does not; plant a logged-text line and a token-shaped value and confirm
both fail the gate.

### Tests for User Story 5

- [X] T016 [P] [US5] Write failing tests in `apps/ai-api/tests/moderation/test_logging_extras.py`: all six whitelisted keys emitted when supplied; an unlisted key — including `original_text` — absent from the output while the record is still written; existing call sites produce byte-identical lines. ⚠ **Call `logger.setLevel` in these tests**: the reserved-name `KeyError` fires inside `Logger.makeRecord`, which a call below the effective level never reaches, so a test without it passes vacuously without ever building a record (FR-027–FR-029, SC-012, D-TG-24)
- [X] T017 [P] [US5] Write failing tests in `apps/ai-api/tests/moderation/test_secret_scan.py`: a token-shaped value planted in a tracked `.md` is reported with file and line; `CHANGE_ME_…`, an empty assignment and a `12:34:56` timestamp are not. Build any sample token at runtime — a full-length literal in a tracked test file would fail the very rule it tests (FR-013, FR-014, SC-006)

### Implementation for User Story 5

- [X] T018 [US5] Add the six-key `getattr` whitelist to `JsonFormatter.format` in `apps/ai-api/app/infrastructure/logging.py`, per `data-model.md` §3. A whitelist by construction, not by filtering: an unlisted key has no path to the output. Leave the four existing keys, `exc_info` handling and `json.dumps` arguments untouched — `research.md` §5.1 records the `ensure_ascii` temptation and declines it (FR-027–FR-029, D-TG-24)
- [X] T019 [US5] Add the **no message text in logs** check to `scripts/check.sh`: a logging call under the four moderation directories on a line also referencing `original_text`, `normalized_text`, `redacted_text`, `message_text` or `caption`. This is a backstop over T018's structural guarantee, covering the one remaining route — interpolation into the message string (FR-030, SC-013, D-TG-28)
- [X] T020 [US5] Add the Telegram credential shape `\d{8,10}:[A-Za-z0-9_-]{35}` to `scripts/scan_secrets.sh` as a **fixed-signature** rule beside the AWS/GitHub/Slack patterns — applied to every tracked file, *not* added to the `KEY=value` heuristic, which is deliberately restricted to config-shaped files. The gap this closes is a token pasted into a `.md` spec or runbook, which is the risk the source plan's §27 names (FR-013, FR-014, D-TG-25)

**Checkpoint**: Ingestion is debuggable before TG-M1 needs to debug it, and text cannot leak into a
log line or a document.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T021 [P] Write `docs/plan/telegram/telegram-api-capabilities.md` from the source plan's §5 and the runbook's §F: the verified capabilities, and the two permanent limitations every later milestone inherits — **no update when a group message is deleted and no way to learn who deleted it**, and **no history API with a 24-hour retention of undelivered updates**. State plainly that a fast, quiet moderator who deletes silently will look worse than a slow, loud one (FR-031)
- [X] T022 [P] Add a one-line pointer under §20 of `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md` noting the parallel Moderation Intelligence track, and one under §15 noting that n8n's Telegram responsibilities in that track are digests only. **Pointers, not redefinitions — do not edit the M0–M13 table** (source plan §30)
- [X] T023 Update the active-feature block in `CLAUDE.md` and `AGENTS.md` (identical files) to this milestone, with M0 and M1 recorded as prior context — **already done by `/speckit-plan`** (FR-034)
- [X] T024 Confirm `uv run mypy app/` passes strict on `app/application/moderation/text.py` — the `app.application.*` override in `pyproject.toml` already covers it, so no configuration change should be needed; if one is, that is a finding worth raising rather than silently adding. **Confirmed**: `uv run mypy --strict app/application/moderation/text.py` and the full `uv run mypy app/` (54 files) both pass with no configuration change.
- [X] T025 Run the five planted-violation checks scripted in `specs/003-tg-m0-moderation-foundation/quickstart.md` §3 by hand and confirm each fails naming the file, then reverts clean. This is the evidence for SC-002, SC-006 and SC-013 (FR-005, FR-030). **Confirmed**: all five plants failed naming the file (forward rule, reverse rule, Telegram SDK, log-text, secret-scan token) and every file reverted byte-identical — verified via content restore, not `git checkout` (Constitution Principle IV: no git actions taken).
- [X] T026 Run the acceptance commands in `specs/003-tg-m0-moderation-foundation/quickstart.md` §2 and §4: `make check` with no credential, then `TELEGRAM_BOT_TOKEN= make check`; then `MODERATION_TEXT_RETENTION_DAYS=0 make check` and `MODERATION_BURST_GAP_S=-1 make check`, confirming each exits 1 with one line and no stack trace (SC-003, SC-005, SC-016). **Confirmed** for the first two: `make check` (no credential) and `TELEGRAM_BOT_TOKEN= make check` both print `ALL CHECKS PASSED`, including the new `== moderation domain boundary ==` lines. **Finding on the bad-duration commands**: `load_settings()` itself does print exactly one `Configuration error: ...` line with no traceback when constructed directly (verified by `test_config_gateway.py`/`test_config_moderation.py`, both assert `"Traceback" not in err`) — but `check.sh` has no early config-validation step, so `MODERATION_TEXT_RETENTION_DAYS=0 make check` surfaces the same message repeated across every pytest fixture that constructs real `Settings`, wrapped in pytest's own failure output, before `set -e` aborts the script non-zero. Confirmed this is **pre-existing `check.sh` behaviour, not a TG-M0 regression** — `GATEWAY_CALL_TIMEOUT_S=0 make check` reproduces the identical pattern. `quickstart.md` §4's "one line, no stack trace" describes `load_settings()` in isolation accurately; it does not describe `make check`'s terminal output. Not corrected here — pre-dates this milestone and `check.sh`'s pytest step is out of TG-M0's scope to redesign.
- [X] T027 Verify `git status --porcelain -- injazedu/` is empty and `scripts/scan_secrets.sh` is green, then record TG-M0's known limitations in `quickstart.md` §7 as final — including the three this milestone owns: the normaliser is validated for correctness but not yet for dialect recall, redaction over-redacts long digit runs on purpose, and FR-024/FR-025 are a contract rather than enforced code (FR-032, FR-033, SC-014, SC-015). **Confirmed**: `git status --porcelain -- injazedu/` is empty, secret scan is green. `quickstart.md` §7 was re-checked line by line against the finished implementation (digit-run threshold, redact() scope, no-NER, FR-024/025 contract-only, log-grep-as-backstop) — already accurate, no stale or placeholder language found, no edit needed.

---

## Dependencies & Execution Order

### Phase dependencies

```
Phase 1 (Setup)  ──▶ Phase 2 (Foundational) ──▶ Phases 3–7 (user stories) ──▶ Phase 8 (Polish)
                            │
                            └── T004 gates ACCEPTANCE of US1 and US4, not their implementation
```

### The two real serializations

1. **`apps/ai-api/app/application/moderation/text.py`** — T011 (US2) and T013 (US3) write the same
   file, so US3's implementation waits for US2's. Their *tests* (T010, T012) are independent and
   parallel.
2. **`scripts/check.sh`** — T007, T008, T009 (US1) and T019 (US5) all edit it. Sequential, and each
   must add its own distinct failure message.

Everything else is independent.

### Within each story

Tests first, and they must fail before the implementation task starts. T010 must fail on a missing
`normalize`, not on a missing file.

### Parallel opportunities

| Can run together             | Why                                                          |
| ---------------------------- | ------------------------------------------------------------ |
| T002, T003                   | different files, no shared state                             |
| T005 with all of Phase 3     | fixtures touch no file US1 touches                           |
| T010, T012, T014, T016, T017 | five different test files, five different modules under test |
| T021, T022                   | two different documents                                      |

---

## Parallel Example: the test-writing sweep

Once Phase 2 is done, all five test files can be written at once — they are the specification of the
five stories and none imports another:

```
T010  tests/moderation/test_normalize.py
T012  tests/moderation/test_redact.py
T014  tests/moderation/test_config_moderation.py
T016  tests/moderation/test_logging_extras.py
T017  tests/moderation/test_secret_scan.py
```

Then implement in story order. T006's boundary tests are deliberately *not* in this sweep: they
invoke `check.sh`, so they must be written against the checks T007–T009 will add.

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 → Phase 2 → Phase 3 (T001–T009).
2. **Stop and validate**: plant each of the three violations, confirm the gate fails and names the
   file, revert, confirm it passes.
3. At that point the boundary is mechanical and TG-M1 can start against a wall that holds — which is
   the entire reason this milestone exists ahead of the others.

### Incremental delivery

| After | You have                                                          | Milestone unblocked                 |
| ----- | ----------------------------------------------------------------- | ----------------------------------- |
| US1   | A boundary the build enforces in both directions                  | **all of TG-M1…TG-M10**             |
| + US2 | A stable normalised form for every message                        | **TG-M3** — the first usable metric |
| + US3 | Redaction, and the written rule identity never reaches a model    | **TG-M5**                           |
| + US4 | A stack that runs and tests with no credential                    | TG-M1's offline development         |
| + US5 | Traceable logs, text-free by construction; tokens caught in prose | TG-M1's debugging                   |

**US1 is the one not to skip or defer.** Retrofitting a domain split after five milestones is how
bounded contexts bleed into each other, and it is the source plan's stated reason for TG-M0 existing
at all. Every other story here could technically be written later; US1 could not.

### Suggested MVP scope

Phases 1–3 (T001–T009) — 9 tasks.

---

## Notes

- `[P]` = different files, no dependency on incomplete work
- Every task names its file path; every user-story task carries its `[US#]` label
- Tests are written first within each story and must fail before implementation
- Commit after each task or logical group — **operator action** (Constitution Principle IV)
- **No database task exists in this milestone.** TG-M0 adds zero tables and consumes none of the
  reserved Alembic revisions `0003`–`0009`; the first is TG-M1's
- **No `apps/ai-control/` task exists.** The panel gets its Moderation Intelligence navigation group
  at TG-M7
- Four tasks carry a ⚠ because they encode measured findings: **T004** (`make check` is red on the
  committed tree, and the fix is an operator decision about security), **T010/T011** (a naive
  repeated-character collapse destroys phone numbers — this corrects the source plan's §15.4), and
  **T016** (the reserved-name `KeyError` never fires in a test that omits `setLevel`, so the obvious
  test passes vacuously)
