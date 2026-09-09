# Implementation Plan: TG-M0 — Moderation Intelligence Domain Foundation

**Branch**: `tg-m0/foundation` *(operator-created — Constitution IV)* | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-tg-m0-moderation-foundation/spec.md`
**Source plan**: `docs/plan/telegram/telegram-moderation-intelligence.md` (§6, §15.4–§15.5, §19, §21, §25 TG-M0, §27, §30)
**Operator runbook**: `docs/runbooks/tg-operator-prerequisites.md` (§A, §C TG-M0 row, §F)

## Summary

TG-M0 opens the Moderation Intelligence domain beside the existing Assessment domain and builds the
wall between them before there is anything to separate. It ships **four package skeletons, one
module of real logic, five settings, two contained fixes to shared infrastructure, and three new
checks in the quality gate** — no table, no migration, no Telegram call, no screen, no model call.

The approach is almost entirely additive. The one module with behaviour is
`app/application/moderation/text.py`: a seven-step Arabic normaliser and a four-pattern redactor,
both pure functions, both deterministic, both idempotent. Everything else is a directory, a
configuration field, or a grep.

**Two probes changed the design rather than confirming it**, and both are the kind of thing that
looks fine until it corrupts data at scale:

1. ⚠ **A naive repeated-character collapse destroys phone numbers.** `(.)\1{2,}` turns
   `0555555555` into `05`. Because normalisation runs *before* redaction, the redactor then finds
   nothing to replace, `«رقم»` never appears, and a mangled fragment goes to the model instead — while
   a phone number *without* a triple digit is redacted correctly, so the same rule handles two phone
   numbers two different ways. The collapse is restricted to **letters** (D-TG-21). This corrects the
   source plan's §15.4 wording.
2. ⚠ **The existing secret scan already covers the `.env` case** — its `KEY=value` rule matches any
   name ending `_TOKEN` — but it is deliberately restricted to config-shaped files, so a token pasted
   into a **`.md` spec or runbook is invisible today**. That is precisely the risk §27 names, and
   precisely the file type this track produces most of. The new rule is therefore a fixed-signature
   check over *every* tracked file, not another `KEY=value` heuristic (D-TG-25).

Two further findings narrowed the work. `app/providers/telegram/` sits inside the directory the
existing `httpx` rule already exempts, so the Telegram provider needs **no new allowlist entry** and
**no new dependency** — it will speak the Bot API over the `httpx` M0 already installs (D-TG-19). And
stdlib `logging` **rejects** `extra={"message": …}` outright, which is why the correlation key is
`message_id` — a redesign avoided by measuring rather than discovering it mid-implementation (D-TG-24).

## Technical Context

**Language/Version**: Python 3.12 (unchanged) · no change to the PHP control panel — TG-M0 has no UI
**Primary Dependencies**: **none added**. `pydantic-settings` (present), stdlib `re` /
`unicodedata` / `logging` / `json`. ⚠ No Telegram SDK is added — see Complexity Tracking and D-TG-19
**Storage**: **none**. No table, no migration, no Redis key. Alembic revisions `0003`–`0009` stay
reserved and unconsumed
**Testing**: pytest, offline by default; one new test package `tests/moderation/` with checked-in
Arabic fixtures; three planted-violation checks that assert the gate fails
**Target Platform**: macOS 26.6 on Apple Silicon (M1 Pro, 16 GB), local-only, no inbound network
**Project Type**: Multi-service local application — Python service (API + worker) + PHP control panel
**Performance Goals**: none of consequence. The gate's added runtime is three greps and ~40 pure
unit tests; budget < 10 s against SC-003
**Constraints**: no Telegram network call · no database change · no model call · no UI · every test
offline and credential-free · no import across the moderation/assessment boundary · no message text
in any log line · zero writes inside `injazedu/`
**Scale/Scope**: 4 new package directories, 1 module with logic, 5 settings, 2 shared-infrastructure
edits, 3 gate checks, 1 secret-scan signature, ~40 focused tests, 0 tables

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution's Development Workflow requires every plan to answer five questions.

### 1. Which behaviors are high-risk enough to need tests, and which are exempt? (Principle I)

**Tested — these are contracts, data-safety mechanisms, or measured failure modes:**

| Behavior | Why it earns a test | Covers |
|---|---|---|
| Normalisation: the three measured equivalence classes each collapse to one form | This is the whole point of the module, and TG-M3's rule recall on dialect Arabic is a named high-likelihood risk | FR-016, FR-017, SC-007 |
| Normalisation idempotence, and `original_text` unmodified | Derived state must be rebuildable from raw updates (D-TG-02); a non-idempotent transform breaks replay convergence at TG-M10 | FR-015, FR-020, SC-008 |
| ⚠ Repeated-collapse leaves digit runs intact | Measured silent-failure mode (D-TG-21). Untested, a phone number becomes `05` and the redactor reports success on text it never redacted | FR-018, FR-022, SC-007 |
| Emoji and Latin script survive normalisation | FR-018 and FR-019 pull against each other; only a test proves the letters-only rule satisfies both | FR-019, SC-009 |
| Redaction: each of the four patterns replaced, overlapping cases deterministic, idempotent, no-op text unchanged | The privacy contract. Overlap order is forced by containment, not preference, and a reordering would silently nest substitutions | FR-022, FR-026, SC-010 |
| Settings: each duration rejects zero and negative, message names the variable | `MODERATION_TEXT_RETENTION_DAYS=0` reaching TG-M10's purge deletes every message text on first run. This is a data-safety test, not a config test | FR-010, SC-005 |
| Credential absent → startup succeeds, gate passes | The supported operating state the runbook requires; regressing it makes every later milestone un-runnable offline | FR-008, SC-003 |
| Log formatter: whitelisted keys emitted, unlisted keys (incl. text) dropped, existing output unchanged | Security/privacy. The formatter *is* the guarantee; the grep is only its backstop | FR-027–FR-030, SC-012 |
| **The three planted boundary violations each fail the gate** | A grep that matches nothing passes silently forever. Ten milestones lean on these rules | FR-005, SC-002 |
| **A planted logged-text line fails the gate** | Same argument | FR-030, SC-013 |
| A token-shaped value in a tracked `.md` fails the secret scan; a placeholder does not | Measured gap (D-TG-25) — the case the existing scan does not cover is the one this track will actually hit | FR-013, FR-014, SC-006 |

**Explicitly exempt under Principle I — no tests written:**
The package directories and their `__init__.py` files (structure; the gate proves it) ·
`.env.example` contents · the empty provider and worker-task skeletons · documentation files ·
Makefile plumbing. These are wiring or inert scaffolding.

### 2. Do any tests touch a database — and is the `_test` database wired through the testing environment? (Principle II)

**No.** TG-M0 adds **zero** database-backed tests, because it adds zero tables. Every test in this
milestone is a pure unit test over `text.py`, `config.py` or `logging.py`, or a subprocess assertion
that a gate check fails on a planted file.

M0's guard remains in force and unmodified: `tests/conftest.py` still aborts the session unless
`TEST_DATABASE_URL` names a `_test`, local, non-`DATABASE_URL` database. TG-M0 changes no part of
that mechanism, adds no database, and drops none. The existing database-backed tests from M0 and M1
continue to run under it unchanged.

### 3. Does anything require writing inside `injazedu/`? (Principle III)

**No.** The source plan states it explicitly for the whole track: "For v1: none. Nothing in
TG-M0…TG-M10 requires a change inside `injazedu/`" (§24). This milestone neither reads nor writes it.
**Operator/InjazEdu-team work in TG-M0: none.**

### 4. Are there Git actions in the task list? (Principle IV)

**Yes, and every one is an operator step:**

- The `tg-m0/foundation` branch — **already created by the operator**; the agent did not create it,
  and the mandatory `before_specify` hook was surfaced, not executed.
- The `before_plan` / `after_plan` auto-commit hooks in `.specify/extensions.yml` — surfaced by the
  agent, executed only by the operator.
- Committing TG-M0's implementation — operator.

The agent inspects Git state (`status`, `diff`, `log`) and nothing more. Note that
`scripts/scan_secrets.sh` runs `git ls-files`, which is inspection.

### 5. Is every task traceable to the approved spec and current milestone? (Principle V)

**Yes.** Every design element maps to a numbered requirement in `spec.md`, which maps to the source
plan's §25 TG-M0 row and the sections listed under **Source plan**. Five boundary calls worth naming,
because each is somewhere this milestone *declined* to build:

- **No health-report component.** The `telegram_ingestion` block is TG-M1's, where there is something
  to report. An always-"not configured" component now would be noise (research §5.2).
- **No credential validation.** The token is carried, never checked. `make tg-doctor` is TG-M1's
  (D-TG-27).
- **No migration, and no reservation consumed.** Revisions `0003`–`0009` stay untouched (research §5.4).
- **No `role='moderation'` widening** of `model_profiles`. That is TG-M5's one-line CHECK change.
- **No Dramatiq retry policy.** The moderation task package ships empty; retries are set per-actor by
  the milestones that add actors.

Two shared-infrastructure files are edited — `config.py` and `logging.py`. Both edits are named in
the source plan's TG-M0 "Repo areas" row, both are additive, and neither changes existing behaviour
(FR-012, FR-029). No opportunistic refactor rides along; research §5.1 records one such temptation
(`ensure_ascii`) and declines it.

## Project Structure

### Documentation (this feature)

```text
specs/003-tg-m0-moderation-foundation/
├── plan.md                        # This file
├── spec.md                        # FR-001…FR-034, SC-001…SC-016
├── research.md                    # Phase 0 — 12 decisions D-TG-17…D-TG-28, 8 probes
├── data-model.md                  # Phase 1 — value shapes only; no schema change
├── quickstart.md                  # Phase 1 — operator walkthrough, reproducible probes, limitations
├── contracts/
│   ├── domain-boundary.md         # the boundary as a checkable rule: allowlist, exemptions, messages
│   ├── moderation-text.md         # THE durable contract: normaliser + redactor + the redact-before-gateway rule
│   └── environment.md             # the five settings, defaults, validation, absent-credential semantics
├── checklists/requirements.md     # spec quality checklist (16/16)
└── tasks.md                       # Phase 2 (/speckit-tasks — NOT created by this command)
```

### Source Code (repository root)

```text
apps/ai-api/
├── app/
│   ├── domain/
│   │   ├── model_profile.py                 # unchanged — one of the 3 permitted shared imports
│   │   └── moderation/                      # NEW — package skeleton, frozen dataclasses to come
│   │       └── __init__.py
│   ├── application/
│   │   ├── gateway/                         # unchanged — permitted shared import
│   │   ├── probes/  health_service.py       # unchanged — NOT importable from moderation
│   │   └── moderation/                      # NEW
│   │       ├── __init__.py
│   │       └── text.py                      # THE module with logic: normalize() + redact()
│   ├── providers/
│   │   ├── llm/  embeddings/                # unchanged
│   │   └── telegram/                        # NEW — skeleton; inside the existing httpx exemption
│   │       └── __init__.py
│   ├── workers/tasks/
│   │   ├── diagnostics.py                   # unchanged
│   │   └── moderation/                      # NEW — skeleton, no actors in TG-M0
│   │       └── __init__.py
│   └── infrastructure/
│       ├── config.py                        # EDIT — 5 settings + 3 validators (additive)
│       └── logging.py                       # EDIT — 6-key extra whitelist (additive)
└── tests/
    ├── conftest.py                          # unchanged — M0's _test guard still governs
    ├── gateway/  integration/  unit/        # unchanged
    └── moderation/                          # NEW test package, mirroring tests/gateway/
        ├── __init__.py
        ├── fixtures/arabic_messages.py      # checked-in fixtures incl. the measured equivalence classes
        ├── test_normalize.py
        ├── test_redact.py
        ├── test_config_moderation.py
        ├── test_logging_extras.py
        └── test_boundary_checks.py          # plants violations, asserts the gate fails

scripts/
├── check.sh                                 # EDIT — 3 new checks beside the existing httpx rule
└── scan_secrets.sh                          # EDIT — 1 fixed-signature token rule, all tracked files

.env.example                                 # EDIT — the 5 settings, credential as placeholder only
CLAUDE.md / AGENTS.md                        # EDIT — active-feature pointer (identical files)
docs/plan/telegram/telegram-api-capabilities.md   # NEW — §5's verified capabilities and limitations
```

**Structure Decision.** Four peer directories inside the existing four layers, not a new top-level
`app/moderation/` tree (D-TG-17). This is what the source plan's §25 "Repo areas" row names, and it
means the `pyproject.toml` mypy strict overrides for `app.domain.*` and `app.application.*` apply to
moderation code with **no configuration change** — `text.py` is strict-typed from its first line.
Tests get one new top-level package because that is how `tests/gateway/` was added for M1.

## ⚠ Blocking Prerequisite Discovered During Planning

**`make check` does not currently pass on the committed tree.** Verified 2026-09-09 on
`tg-m0/foundation` at `182bfb1`, with no file of mine modified: `scripts/scan_secrets.sh` — which
`scripts/check.sh` runs as its last step — exits 1 with six findings.

This matters here more than anywhere else, because TG-M0's *only* smoke test is "`make check` passes
with no credential set" (SC-003), and FR-013/FR-014 add a new rule to that same script.

**All six are false positives. None is a real credential.**

| File:line | Flagged text | Why it fires |
|---|---|---|
| `apps/ai-api/tests/gateway/test_lanes.py:85` | `held_token = await holder.lane.acquire(...)` | local variable ending `_token` |
| `apps/ai-api/tests/gateway/test_lanes.py:160` | `recovered_token = await acquirer.lane.acquire(...)` | same |
| `scripts/scan_secrets.sh:30` | `AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")` | the scanner detecting **its own** pattern definitions |
| `scripts/scan_secrets.sh:31` | `GITHUB_TOKEN = re.compile(...)` | same |
| `scripts/scan_secrets.sh:32` | `SLACK_TOKEN = re.compile(...)` | same |
| `scripts/test_db_reset.sh:26` | `MIGRATOR_PASSWORD="$(grep '^AI_MIGRATOR_PASSWORD=' .env ...)"` | a shell variable holding a *command substitution*, not a value |

**Cause.** The `KEY=value` heuristic matches any identifier ending `PASSWORD`, `SECRET`, `_TOKEN`,
`APIKEY`, `API_KEY` or `_KEY` — case-insensitively — inside a "config-shaped" file, and that set
includes `.py`, `.sh` and `.php`. In those languages the pattern is ordinary assignment syntax, so
every local variable named `held_token` is a finding. The three `scan_secrets.sh` hits are the script
detecting itself.

**Why this plan does not fix it.** Narrowing a secret scanner is a change to a security mechanism,
and Constitution Principle V requires the agent to stop and present rather than guess when a decision
would materially change security. The plausible fixes are not equivalent:

| Option | Effect | Cost |
|---|---|---|
| Drop `.py`/`.sh`/`.php` from `CONFIG_SHAPED` | Removes all six | **Loses real coverage** — a credential pasted into a Python or shell file stops being detected |
| Require the value to look like a literal, not an expression (exclude `re.compile(`, `await `, `$(`, `` ` ``) | Removes all six | Heuristic-on-heuristic; new expression forms will recur |
| Add an inline `# noqa`-style suppression the scanner honours | Removes all six, keeps coverage | Suppressions can be pasted onto a real leak |
| Exempt `scripts/scan_secrets.sh` from itself, and require `_token` locals to be renamed | Removes all six, keeps coverage | Touches M1 test code for a naming reason |

**This is the operator's call, and it must be made before TG-M0 is implemented** — otherwise the
milestone's acceptance criterion cannot be met and the new token rule lands in a script that is
already red. It is recorded here rather than resolved because it predates this milestone and changing
it changes what the whole repository considers a secret.

**Related, and already handled:** the first draft of `quickstart.md` §3 planted a full-length sample
token in a tracked file, which the *new* rule would have flagged — the specification failing its own
rule. That example now builds the value at runtime, and both `research.md` §D-TG-25 and
`contracts/domain-boundary.md` §7 record the constraint for future docs in this track.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

**No violations.** All five gate questions pass without exception, and question 2 passes trivially —
this milestone has no database-backed test at all.

Four choices that *look* like added complexity, recorded because a reviewer will ask:

| Choice | Why it is not gratuitous |
|---|---|
| Three gate checks rather than one | They are three different rules with three different failure messages: moderation reaching into assessment, assessment reaching into moderation, and a Telegram SDK appearing anywhere. Collapsing them into one grep would produce a single unhelpful message for three unrelated mistakes. Measured: all three are silent on today's tree, so they are additive. |
| An import **allowlist** rather than a denylist | There is no `app/assessment/` directory — assessment code is the un-namespaced modules. A denylist would have to enumerate modules that mostly do not exist yet and would pass silently the day M2 adds one. The allowlist fails closed (D-TG-18). |
| Hand-rolled normalisation over `camel-tools` / `pyarabic` | Seven lines of stdlib against an NLP dependency and, for `camel-tools`, a scientific stack this project does not carry. The plan also wants this normaliser to be *small* and domain-owned so M4 can supersede it (§15.4). |
| Tests that assert a shell script fails | Ordinarily "testing the build" is exempt under Principle I. Here the gate rules *are* the deliverable — the milestone exists to make the boundary mechanical — and a grep that matches nothing passes silently forever. Without these, SC-002 and SC-013 are unverifiable claims. |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 (research.md, data-model.md, contracts/, quickstart.md). Required by the
constitution's Compliance clause.*

**RESULT: PASS — strengthened.** The design introduced no violation, and three findings made a gate
stronger than the pre-design plan promised:

| Gate | Pre-design | After design | Change |
|---|---|---|---|
| I — Risk-proportional testing | 8 tested behaviors | 11, after probe 5 exposed a silent-failure mode (digit destruction) that no test of the redactor alone would have caught | **Strengthened** |
| II — Test DB isolation | Inherits M0's `_test` guard | Confirmed *not exercised*: TG-M0 adds zero database-backed tests, so the surface is smaller than assumed | **Strengthened** |
| III — `injazedu/` read-only | No writes | Confirmed: neither read nor written; the source plan states it for the whole track (§24) | Unchanged |
| IV — Git operator-owned | Branch + commits are operator steps | Unchanged; the branch already existed, operator-created, and no artifact performs a Git action | Unchanged |
| V — Approved scope | Traceable to the §25 TG-M0 row | D-TG-19 and D-TG-25 each *removed* work the pre-design reading implied; research §5 declines six further items | **Strengthened** |

**Three things a reviewer should look at deliberately:**

1. **D-TG-21 corrects the source plan.** §15.4 says "collapse whitespace and repeated characters".
   Applied literally that destroys phone numbers, and — worse than destroying them — it destroys
   *some* of them, so redaction succeeds on one number and mangles the next. The plan's intent
   (`تماااام → تمام`) is right; its wording is too broad. The correction applies to §15.4's text, not
   only to this milestone.
2. **D-TG-25 narrows what §19.3 implies.** The existing scan already catches the `.env` case. The
   real gap is a token in a **prose file**, which is both the risk §27 names and the file type this
   documentation-heavy track generates most. The rule was retargeted accordingly, and it was checked
   that the regex does not match its own printed form — so the shape can be documented safely.
3. **FR-024 and FR-025 are contracts, not code, in this milestone — deliberately.** TG-M0 makes no
   model call, so there is no call site to guard. Manufacturing a runtime payload inspector would
   approximate a property that is trivially true if TG-M5's request builder simply has no other
   input. `contracts/moderation-text.md` states the rule TG-M5 must follow; the reviewer should
   confirm that is acceptable rather than assume the guarantee is already enforced in code (D-TG-23).

## Requirement → Design Traceability

| Spec requirements | Where the design answers them |
|---|---|
| FR-001…FR-006 (domain boundary, no-build list) | `contracts/domain-boundary.md` §1–§3; D-TG-17, D-TG-18, D-TG-19; Project Structure above |
| FR-007…FR-012 (configuration, optional credential) | `contracts/environment.md`; `data-model.md` §1; D-TG-26, D-TG-27 |
| FR-013…FR-014 (secret scanning) | `contracts/domain-boundary.md` §4; D-TG-25 |
| FR-015…FR-021 (Arabic normalisation) | `contracts/moderation-text.md` §1–§2; `data-model.md` §2; D-TG-20, D-TG-21 |
| FR-022…FR-026 (redaction) | `contracts/moderation-text.md` §3–§4; D-TG-22, D-TG-23 |
| FR-027…FR-030 (correlation ids, no text in logs) | `contracts/domain-boundary.md` §5; `data-model.md` §3; D-TG-24, D-TG-28 |
| FR-031…FR-034 (documentation, active-feature pointer) | `quickstart.md` §5; `docs/plan/telegram/telegram-api-capabilities.md`; Project Structure above |

Every FR is claimed by at least one design artifact; no design artifact exists without an FR.

## Phase Status

- [x] Phase 0 — research complete (12 decisions D-TG-17…D-TG-28, 8 probes, 0 unresolved NEEDS CLARIFICATION)
- [x] Phase 1 — data model, 3 contracts, quickstart, agent context updated
- [x] Constitution Check — pre-design PASS, post-design PASS (strengthened)
- [ ] Phase 2 — task breakdown (`/speckit-tasks`, not produced by this command)
- [ ] ⚠ **Operator decision outstanding** — the pre-existing `scan_secrets.sh` false positives above.
      `make check` is red on the committed tree; TG-M0 cannot be accepted until it is green.
