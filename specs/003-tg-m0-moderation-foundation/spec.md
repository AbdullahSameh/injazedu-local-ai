# Feature Specification: TG-M0 — Moderation Intelligence Domain Foundation

**Feature Branch**: `tg-m0/foundation` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/003-tg-m0-moderation-foundation`
**Created**: 2026-09-09
**Status**: Draft
**Milestone**: TG-M0 (first milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25)
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prerequisites.md, the start specify Milestone number 0 Domain foundation"

## Overview

TG-M0 opens a **second bounded domain** — Moderation Intelligence — beside the existing Assessment
Intelligence domain. The two share infrastructure (one database, one queue, one background worker,
one model gateway, one control panel shell) and share nothing else. This milestone builds the wall
between them, and the three small pieces of text and configuration handling that every later
moderation milestone will depend on.

It deliberately contains **no Telegram call, no table, no screen and no model call**. Its entire
value is that the constraints are in place and mechanically checked *before* ten milestones of
moderation code exist. Retrofitting a domain split after five milestones is how bounded contexts
bleed into each other; that is the failure this milestone prevents.

Four things ship:

1. **A boundary that fails the build when crossed.** Moderation code may not reach into assessment
   code, assessment code may not reach into moderation code, and Telegram-specific client code may
   live in exactly one place. All three are checked automatically, not by convention or review.
2. **Configuration for a domain that is not switched on yet.** Every moderation setting gains a
   value and a safe default, and the Telegram credential is *optional*: with no credential present
   the system starts, stays healthy and passes its full quality gate. Ingestion simply does not run.
3. **Arabic text handling this domain owns.** A student writing `مـتـى تبدأ المحاااضرة ؟٣`
   and a student writing `متى تبدا المحاضره 3` are asking the same question. A small, deterministic
   normaliser makes them match, while never touching the original text and never damaging the Latin
   words ("zoom link", "STEP") that Saudi and Egyptian group chat is full of.
4. **Redaction, applied before anything leaves the domain.** Phone numbers, emails, links and
   handles are replaced with neutral placeholders *before* text is ever handed toward a model, not
   after — so that turning on the gateway's payload-capture debug flag can never become a privacy
   regression. Identity — who wrote it, in which group, on which course — is never part of what a
   model is asked to judge.

Alongside those, two contained fixes to shared infrastructure that ingestion cannot be debugged
without: log records gain a **closed whitelist of correlation identifiers** (today extra fields are
silently discarded, so nothing is traceable), and the repository secret scan learns the **shape of a
Telegram bot credential** so one can never be committed.

TG-M0 is done when a deliberately planted violation of any of these rules fails the quality gate,
and the gate itself passes offline, with no model runtime running and no Telegram credential set.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The domain boundary refuses to be crossed (Priority: P1)

A developer working on a later moderation milestone adds a convenient import from the assessment
side — a chunking helper, a document-scoped identifier, a retrieval utility. Or they reach for a
Telegram client from inside business logic because it is quicker than going through the provider
layer. In every case the quality gate stops them, names the file and the rule, and refuses to pass.
The same happens in reverse when assessment code reaches into moderation.

**Why this priority**: Every one of the ten milestones after this one depends on the boundary
holding. It is the only deliverable here that cannot be added later without unpicking work already
done, and the plan's stated reason for the milestone existing at all. On its own it delivers the
whole of TG-M0's structural value.

**Independent Test**: Plant one file that imports assessment code from a moderation module, one that
imports moderation code from an assessment module, and one that imports a Telegram client from
outside the moderation provider area. Run the quality gate and confirm each is reported and the gate
fails. Remove them and confirm it passes. No Telegram credential, database row or model is involved.

**Acceptance Scenarios**:

1. **Given** the moderation package areas exist and are empty of business logic, **When** the quality
   gate runs on the unmodified repository, **Then** it passes and reports the boundary checks as
   satisfied.
2. **Given** a moderation module that imports from an assessment module, **When** the quality gate
   runs, **Then** it fails, names the offending file, and states which boundary rule was broken.
3. **Given** an assessment module that imports from a moderation module, **When** the quality gate
   runs, **Then** it fails in the same way.
4. **Given** a module outside the moderation provider area that imports a Telegram client library,
   **When** the quality gate runs, **Then** it fails and names the file.
5. **Given** a moderation module that imports the shared model gateway, the shared infrastructure, or
   the shared model-profile type, **When** the quality gate runs, **Then** it passes — these are the
   only permitted shared dependencies.

---

### User Story 2 - Arabic questions match regardless of how they were typed (Priority: P2)

The same question arrives written five ways across five groups: with diacritics, with elongation
(`تمااااام`), with Arabic-Indic digits, with a different alef, with `ة` where another student wrote
`ه`. Later milestones must recognise all five as the same shape without a model. A normalised form
of every message is produced for matching, while the exact original the student typed is preserved
untouched for display and for evidence.

**Why this priority**: The deterministic rule set in TG-M3 is the first shippable metric, and its
recall on dialect Arabic is one of the plan's named high-likelihood risks. Normalisation is the
single cheapest lever on that risk, and it must exist before any rule is written against it. It is
independently valuable and independently testable with a fixture file of real Arabic messages.

**Independent Test**: Feed a fixture set of real Arabic, Arabizi and mixed-script messages through
normalisation and assert the expected normalised form for each, that the original is byte-identical
afterwards, and that normalising an already-normalised string changes nothing.

**Acceptance Scenarios**:

1. **Given** a message containing diacritics and elongation characters, **When** it is normalised,
   **Then** both are removed and the remaining letters are unchanged.
2. **Given** messages differing only by alef variant, teh marbuta versus heh, or alef maqsura versus
   yeh, **When** each is normalised, **Then** all produce the same normalised text.
3. **Given** a message containing Arabic-Indic or Eastern Arabic-Indic digits, **When** it is
   normalised, **Then** the digits appear as their ASCII equivalents.
4. **Given** a message with a character repeated for emphasis and with irregular spacing, **When** it
   is normalised, **Then** the repetition collapses to the base word and whitespace collapses to
   single spaces.
5. **Given** a message mixing Arabic with Latin words and emoji, **When** it is normalised, **Then**
   the Latin words and the emoji survive intact and readable.
6. **Given** any message, **When** it is normalised twice, **Then** the second pass produces exactly
   the result of the first.
7. **Given** any message, **When** normalisation completes, **Then** the original text is unmodified
   and remains available separately.

---

### User Story 3 - Nothing identifying reaches a model (Priority: P3)

Before any message text is handed toward a model for judgement, contact details, links and handles
are replaced by neutral placeholders, and no identifying attribute — who sent it, which group it was
in, which course that group belongs to, any numeric identifier — is included at all. The model is
asked *what kind of thing was said*, never *who said it*.

**Why this priority**: This is the milestone's privacy contract and the plan calls it out as the
important one. Redaction happening *before* the gateway rather than after is what makes the
gateway's debug payload-capture flag safe to switch on. It ships now, in the milestone that owns the
text pipeline, rather than in the milestone that first calls a model — because by then it would be a
retrofit under deadline.

**Independent Test**: Feed messages containing phone numbers, emails, links and handles through
redaction and assert each is replaced by its placeholder while the surrounding Arabic and Latin text
is unchanged; assert redaction is idempotent; and assert that the assembled classification input
contains message text only and no identity, group or course attribute.

**Acceptance Scenarios**:

1. **Given** a message containing a phone number or a long run of digits, **When** it is redacted,
   **Then** the digits are replaced by a fixed neutral placeholder.
2. **Given** a message containing an email address, a web link, or an `@` handle, **When** it is
   redacted, **Then** each is replaced by its own fixed neutral placeholder.
3. **Given** a redacted message, **When** it is redacted again, **Then** the result is unchanged.
4. **Given** a message with no contact details, links or handles, **When** it is redacted, **Then**
   the text is returned unchanged.
5. **Given** any request assembled for model judgement, **When** its contents are inspected, **Then**
   they contain redacted message text and taxonomy instructions only — no sender name, no handle, no
   numeric identifier, no group title and no course name.
6. **Given** the ordering of the two operations, **When** text is prepared for a model, **Then**
   redaction is applied to the normalised text and the result of redaction is what leaves the domain.

---

### User Story 4 - The system runs, and its gate passes, with no Telegram credential (Priority: P4)

An operator who has not yet created a bot — or a continuous check running on a machine that must
never hold a live credential — starts the stack, runs the full quality gate and gets a clean result.
Nothing degrades, nothing warns spuriously, and readiness is unaffected. The credential's absence
means exactly one thing: ingestion is not running.

**Why this priority**: The plan's smoke test for this milestone is literally "the gate passes with
no credential set", and the runbook forbids the live and development credentials from coexisting on
one machine. Making absence a first-class, tested state now is what keeps every later milestone
runnable offline. Lower priority than the three above only because it is a property of them rather
than new capability.

**Independent Test**: Run the full quality gate twice — once with no credential variable defined and
once with it defined but empty — and confirm both pass with no moderation component reporting
unhealthy.

**Acceptance Scenarios**:

1. **Given** no Telegram credential is configured, **When** the stack starts, **Then** it starts
   successfully and readiness is unaffected.
2. **Given** no Telegram credential is configured, **When** the full quality gate runs offline with
   no model runtime available, **Then** it passes.
3. **Given** a Telegram credential is configured, **When** the stack starts, **Then** behaviour in
   this milestone is otherwise identical — no network call to Telegram is made.
4. **Given** a moderation setting is given a value outside its permitted range, **When** the stack
   starts, **Then** startup fails with a message naming that specific setting and the permitted
   range.
5. **Given** the environment example file, **When** it is inspected, **Then** every moderation
   setting appears with its documented default and the credential appears as a placeholder only.

---

### User Story 5 - A moderation event can be traced through the logs, and never leaks text (Priority: P5)

An operator investigating why a particular update was not turned into an item searches the logs by
that update's identifier and finds every line the system wrote about it. What they never find, in
any line, is what a student actually wrote.

**Why this priority**: Ingestion debugging is impossible without correlation identifiers — today
extra fields attached to a log record are silently discarded — and the plan names this as the
smallest change that makes ingestion debuggable. It is last only because nothing in TG-M0 itself
emits these identifiers; the fix must simply be in place before TG-M1 does.

**Independent Test**: Emit log records carrying each whitelisted identifier and confirm each appears
in the output; emit a record carrying an unlisted field and confirm it is absent; run the automated
check that forbids message text from being logged against a planted violation.

**Acceptance Scenarios**:

1. **Given** a log record carrying one or more of the permitted correlation identifiers, **When** it
   is written, **Then** each identifier appears as its own field in the output.
2. **Given** a log record carrying a field outside the permitted set, **When** it is written,
   **Then** that field does not appear in the output and the record is still written.
3. **Given** existing log output produced elsewhere in the system, **When** the change is in place,
   **Then** the previously emitted fields are unchanged.
4. **Given** a planted line that writes message text to a log, **When** the quality gate runs,
   **Then** it fails and names the file.
5. **Given** a Telegram-credential-shaped value placed in any version-controlled file, **When** the
   secret scan runs, **Then** it fails and names the file and line.
6. **Given** the credential placeholder in the environment example file, **When** the secret scan
   runs, **Then** it is not reported.

---

### Edge Cases

- **Empty, whitespace-only, or emoji-only text.** Normalisation and redaction must return a defined
  result rather than failing, and an emoji-only message must survive as emoji — the plan treats
  emoji as signal.
- **A message that is nothing but a link, or nothing but a handle.** After redaction it becomes a
  placeholder with no surrounding words; that is correct, and downstream rules must be able to
  receive it.
- **A link that contains a handle, or an email whose domain looks like a link.** The overlapping
  patterns must produce one deterministic result, not a doubly-substituted fragment, and the same
  result on every run.
- **Arabic text where a digit run is a year or a lecture number, not a phone number.** The rule is
  length-based and will over-redact some legitimate numbers; over-redaction is the accepted direction
  of error and must be documented rather than silently tuned.
- **Latin-script content that must survive.** "STEP", "zoom link" and code-switched phrases such as
  `الـ link` must remain recognisable after normalisation; damaging them would break rule matching in
  exactly the groups that use them most.
- **Repeated-character collapse against legitimate doubling.** Arabic words with genuine doubled
  letters must not be corrupted; the collapse threshold must be chosen and tested against real
  fixtures rather than assumed.
- **Credential present but malformed.** In this milestone nothing calls Telegram, so a malformed
  credential must not cause a startup failure that a valid one would not — the shape is validated
  where it is used, not at import time.
- **Retention or window settings at their boundaries.** Zero and negative values for the burst
  window, the maximum item age and the retention period must be rejected at startup, not accepted and
  discovered later by a purge that deletes everything.
- **An allowlisted file in the boundary check.** The existing gate carries a small allowlist for
  pre-existing files; adding moderation rules must not silently widen it, and any new entry must be
  justified in place.
- **The gate running on a machine with no model runtime and no network.** Every check added here is
  static or local; none may introduce an external dependency into the default gate.

## Requirements *(mandatory)*

### Functional Requirements

**The domain boundary**

- **FR-001**: The system MUST establish Moderation Intelligence as a package boundary distinct from
  the existing Assessment Intelligence domain, with its own domain, application, provider and
  background-task areas, following the existing layering conventions without introducing new ones.
- **FR-002**: No moderation module may import from an assessment module, and no assessment module may
  import from a moderation module. This MUST be enforced automatically by the quality gate, not by
  review.
- **FR-003**: The only shared dependencies a moderation module may take are the model gateway, the
  shared infrastructure services, and the shared model-profile type. Any other shared import MUST
  fail the gate.
- **FR-004**: Telegram-specific client libraries, request shapes and response shapes MUST be confined
  to the moderation provider area, enforced automatically by the same gate — mirroring the existing
  rule that confines model-runtime libraries to the gateway's provider layer.
- **FR-005**: Each boundary rule MUST fail the gate on a deliberately planted violation, reporting
  the offending file and the rule broken, and MUST pass on the unmodified repository.
- **FR-006**: This milestone MUST create no database table and no migration, make no Telegram network
  call, add no user-facing screen and make no model call. Its provider area is a skeleton only.

**Configuration**

- **FR-007**: The Telegram bot credential MUST be supplied through the environment only. It MUST NOT
  be written to a database column, a log record, a specification document, or any version-controlled
  file.
- **FR-008**: The credential MUST be optional. With it absent or empty, the system MUST start
  normally, MUST report unchanged readiness, and the full quality gate MUST pass. Its absence means
  only that ingestion does not run.
- **FR-009**: The system MUST provide configurable settings, each with a documented default, for: the
  set of Telegram update kinds to subscribe to; the grouping window that treats consecutive messages
  from one sender as a single burst (default 90 seconds); the maximum age at which an unresolved
  attention item stops ageing (default 24 hours); and the retention period for message text (default
  90 days).
- **FR-010**: A setting given a value outside its permitted range MUST cause startup to fail with a
  message naming that setting and its permitted range. Zero and negative durations MUST be rejected.
- **FR-011**: Every new setting MUST appear in the environment example file with its default, and the
  credential MUST appear there as a placeholder only.
- **FR-012**: No setting introduced here may change the behaviour of the existing assessment domain
  or of the model gateway.

**Secret handling**

- **FR-013**: The repository secret scan MUST fail when a value matching the shape of a Telegram bot
  credential appears in any version-controlled file, naming the file and line.
- **FR-014**: The scan MUST NOT report documented placeholder values, and MUST NOT report the
  existing safe patterns it already tolerates.

**Arabic text normalisation**

- **FR-015**: The system MUST produce a normalised form of any message text for matching purposes,
  and MUST leave the original text unmodified and separately available.
- **FR-016**: Normalisation MUST unify the Arabic letter variants that students use
  interchangeably — the alef family, teh marbuta against heh, and alef maqsura against yeh — so that
  texts differing only in those variants normalise identically.
- **FR-017**: Normalisation MUST remove diacritics and elongation characters, and MUST convert
  Arabic-Indic and Eastern Arabic-Indic digits to their ASCII equivalents.
- **FR-018**: Normalisation MUST collapse repeated characters used for emphasis to the base form, and
  MUST collapse runs of whitespace to a single space.
- **FR-019**: Normalisation MUST preserve emoji, MUST preserve Latin-script words, and MUST leave
  code-switched Arabic-and-Latin phrases readable.
- **FR-020**: Normalisation MUST be deterministic and idempotent: the same input always yields the
  same output, and normalising an already-normalised text changes nothing.
- **FR-021**: Normalisation MUST be owned by the moderation domain and MUST NOT depend on any
  assessment-side text handling, present or future.

**Redaction**

- **FR-022**: The system MUST replace, with fixed neutral placeholders, each of: long digit runs and
  phone numbers, email addresses, web links, and `@` handles.
- **FR-023**: Redaction MUST be applied to the normalised text, and the redacted result MUST be the
  only form of message text permitted to leave the moderation domain toward a model.
- **FR-024**: Redaction MUST be applied before the text reaches the model gateway, so that no
  unredacted text can ever be recorded by the gateway's optional payload capture.
- **FR-025**: Text prepared for model judgement MUST consist of redacted message text and instruction
  content only. Sender names, handles, numeric identifiers, group titles and course names MUST NOT be
  included in any model request.
- **FR-026**: Redaction MUST be idempotent, MUST be deterministic when patterns overlap, and MUST
  leave text containing none of the targeted patterns unchanged.

**Traceable, text-free logging**

- **FR-027**: Log records MUST be able to carry a closed set of correlation identifiers — update,
  chat, message, incident, alert and actor — and each supplied identifier MUST appear as its own
  field in the log output.
- **FR-028**: Any field outside that permitted set MUST be dropped from the output, and the record
  MUST still be written.
- **FR-029**: The existing log output produced elsewhere in the system MUST be unchanged by this
  addition.
- **FR-030**: Message text MUST NOT appear in any log record. This MUST be enforced automatically by
  the quality gate and covered by a test, not left to convention.

**Documentation**

- **FR-031**: The milestone MUST record, in the repository, the limitations later milestones inherit
  and cannot design around: Telegram reports no group message deletion and no deleting actor, offers
  no message history, and retains undelivered updates for at most 24 hours.
- **FR-032**: The milestone MUST record that this domain's Arabic normaliser is deliberately its own,
  and that a future assessment-side normaliser may adopt or supersede it but is not a dependency.
- **FR-033**: The milestone MUST record the direction of error accepted in redaction — that
  length-based digit redaction will replace some legitimate numbers — so it is not later mistaken for
  a defect.
- **FR-034**: The active-feature pointer in the repository's agent instructions MUST be updated to
  this milestone, with the previous milestone recorded as prior context, without altering the meaning
  of any existing plan.

### Out of Scope (deferred to named later milestones)

- Any Telegram network call, credential validation against Telegram, poller process, entrypoint or
  container — **TG-M1**. This milestone's provider area is an empty skeleton.
- Every database table in this domain, and the migration revisions that create them — **TG-M1**
  onward. This milestone has no schema change of any kind.
- The health report's ingestion component and the Telegram diagnostic command — **TG-M1**.
- Group, user, message and moderator records; monitored-group flags; time-versioned ownership —
  **TG-M2**.
- The needs-response rule set, attention items and first-response measurement — **TG-M3**. The burst
  window and maximum item age are *configured* here and *consumed* there.
- Policy incidents, their lifecycle and moderator actions — **TG-M4**.
- Any model call, the moderation taxonomy, the prompt template and its versioning, the confidence
  floor, and the widening of the model-profile role — **TG-M5**. Redaction ships here; the thing it
  protects arrives there.
- Alert rules, thresholds, quiet hours, the private moderators' group and message delivery —
  **TG-M6**.
- Authentication on the request-serving surface and the automation-facing endpoints — **TG-M7/TG-M9**.
- Dashboards, metric queries and every screen in the control panel — **TG-M7**.
- Classification review and reprocessing — **TG-M8**.
- Scheduled digests and any automation-tool workflow or configuration — **TG-M9**.
- The text purge job that consumes the retention setting, and replay convergence — **TG-M10**.
- Any change inside the read-only reference application, and any linkage between Telegram groups and
  course records — post-v1, and operator-manual when it comes.
- Retry policies for background tasks and any scheduler — introduced by the milestones that need
  them, not globally here.

### Key Entities

- **Moderation domain boundary**: The rule that this domain and the assessment domain may not import
  each other, plus the short list of shared services both may use. It is a checkable property of the
  repository rather than a stored record, and it is this milestone's primary deliverable.
- **Moderation settings**: The named, defaulted, environment-supplied values that govern the domain —
  which update kinds to subscribe to, the burst window, the maximum item age, the text retention
  period — and the optional Telegram credential whose absence is a supported state.
- **Original text**: Exactly what the student typed. Never modified, and the only form suitable for
  display and evidence.
- **Normalised text**: The matching form of a message — variant letters unified, diacritics and
  elongation gone, digits in ASCII, repetition and whitespace collapsed, emoji and Latin script
  intact. Derived, deterministic, and always reproducible from the original.
- **Redacted text**: The normalised form with contact details, links and handles replaced by neutral
  placeholders. The only form of message text permitted to leave the domain toward a model.
- **Correlation identifier**: One of a closed set of ids that a log record may carry so a single
  Telegram update can be followed across processes. The set is closed precisely so that message text
  can never join it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 0 imports cross between the moderation and assessment domains in either direction, and
  0 Telegram client imports exist outside the moderation provider area — verified by an automated
  check that fails the quality gate when violated.
- **SC-002**: Each of the 3 planted boundary violations (moderation→assessment, assessment→moderation,
  Telegram client outside its provider area) fails the quality gate on 100% of runs, and each failure
  names the offending file.
- **SC-003**: The full quality gate passes with 0 Telegram credentials configured, 0 model runtimes
  running and 0 external network calls, and the moderation additions extend its runtime by under 10
  seconds.
- **SC-004**: This milestone adds 0 database tables, 0 migration revisions, 0 screens and 0 model
  calls — verified by inspection of the change set.
- **SC-005**: 100% of moderation settings have a documented default and appear in the environment
  example file, and 100% of out-of-range values are rejected at startup with a message naming the
  setting.
- **SC-006**: A credential-shaped value placed in a version-controlled file is reported by the secret
  scan on 100% of attempts, and documented placeholders are reported on 0% of runs.
- **SC-007**: Across a fixture set of at least 30 real Arabic, dialect, Arabizi and mixed-script
  messages, normalisation produces the expected form on 100% of cases, and messages that differ only
  by letter variant, diacritics, elongation or digit script collapse to an identical normalised form
  on 100% of cases.
- **SC-008**: Normalisation is idempotent on 100% of the fixture set, and the original text is
  byte-identical after normalisation on 100% of cases.
- **SC-009**: Latin words and emoji present in the fixture set survive normalisation intact on 100%
  of cases.
- **SC-010**: Across a fixture set of messages containing phone numbers, emails, links and handles,
  each targeted pattern is replaced by its placeholder on 100% of occurrences, redaction is
  idempotent on 100% of cases, and text containing none of the patterns is returned unchanged on 100%
  of cases.
- **SC-011**: 0 sender names, handles, numeric identifiers, group titles or course names appear in
  any request assembled for a model, and redaction is applied before the gateway on 100% of paths —
  demonstrated by the assembly path having no other route to model text.
- **SC-012**: 100% of the 6 permitted correlation identifiers appear in log output when supplied, 0
  unlisted fields appear, and the fields emitted by existing log sites are unchanged.
- **SC-013**: A planted log line containing message text fails the quality gate on 100% of runs.
- **SC-014**: The inherited Telegram limitations, the normaliser's independence and the accepted
  redaction over-reach are each recorded in the repository, and a reader can find all 3 from the
  milestone's own documentation in under 2 minutes.
- **SC-015**: 0 secrets appear in version-controlled files and 0 files inside the read-only reference
  application are created, modified or deleted during TG-M0 — both verified by a repository scan.
- **SC-016**: Running the quality gate twice on an unmodified repository produces identical results 2
  out of 2 times, with no dependence on a Telegram credential, a model runtime or network access.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the source plan, the operator runbook, the constitution, or an operator decision recorded
during specification.

- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was
  added, and known limitations are written down. Taken from the source plan's §25 preamble.
- **The smoke test is the gate itself.** The plan gives this milestone one smoke step: the quality
  gate passes with no credential set. There is nothing to demonstrate interactively, because nothing
  in TG-M0 touches Telegram, the database or a screen.
- **Defaults come from the plan, not from judgement.** The 90-second burst window, the 24-hour
  maximum item age and the 90-day text retention are the plan's values (§25 TG-M0, §19.2, D-TG-11).
  They are configured here and consumed by later milestones; changing them is a settings edit, not a
  code change.
- **Boundary enforcement is textual, in the same style as the existing rule.** The repository already
  enforces its model-runtime import rule by scanning source for import statements, and the plan says
  explicitly that the moderation rules are "a grep … next to the existing rule". The new checks
  follow that established mechanism rather than introducing an import-graph analysis tool.
- **The permitted shared imports are exactly three.** The model gateway, the shared infrastructure
  services, and the shared model-profile type — the plan's §6 list. Everything else is a violation,
  including anything that looks harmless today.
- **Redaction placeholders are fixed neutral tokens.** Their exact wording is the plan's (§15.5) and
  is Arabic, which keeps the redacted text linguistically coherent for a model reading Arabic. The
  wording is a constant, not a setting.
- **Digit redaction is length-based and will over-redact.** No reliable way exists to distinguish a
  phone number from a long lecture code in free text, and over-redaction is the safe direction. This
  is recorded as a known limitation rather than tuned.
- **The correlation identifier set is closed at six.** Update, chat, message, incident, alert, actor —
  the plan's §21 list. Closing the set is what guarantees message text can never be attached to a log
  record by accident; widening it later is a deliberate, reviewable change.
- **A malformed credential is not this milestone's problem.** Nothing here contacts Telegram, so the
  credential is carried, never validated. Shape validation belongs where it is used, in TG-M1.
- **No amendment to the constitution is needed.** Every principle already holds for this domain:
  risk-proportional tests, test-database isolation, the read-only reference application, operator-owned
  Git, and scope discipline. Recorded because the source plan explicitly checked this (§30).
- **Migration revision numbers are reserved, not used.** The plan reserves the next block of revision
  identifiers for this domain so the two tracks cannot collide. TG-M0 consumes none of them.
- **Tests are written where the risk is.** Following Principle I, tests here cover the text pipeline's
  correctness and idempotency, settings validation, and the fact that each new gate rule actually
  fires. No test is written for package structure itself, which the gate already proves.
- **Operator prerequisites for this milestone are already met.** The runbook's §C row for TG-M0 asks
  only that the stack is healthy and the seven operator decisions have been made. None of those
  decisions changes anything this specification requires: the first four block TG-M3 and TG-M6, and
  the remaining three are pilot and policy matters outside the code.

## Dependencies

- **M0 and M1 must be complete and merged**, as they are: the running environment, the database with
  migrations as its sole schema owner, the queue and background worker, the model gateway with its
  lane, breaker and call accounting, the control panel shell, and the quality gate with its enforced
  test-database isolation. This milestone extends the gate and the settings; it changes nothing else
  in them.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — specifically §6 for
  the boundary rule and its permitted shared imports, §15.4 for normalisation, §15.5 for redaction,
  §19 for retention and security, §21 for correlation identifiers, and §25 for this milestone's own
  definition.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §A for what must be true
  before this milestone starts, and §C for its smoke step. No step in §B (bot creation) is required
  for TG-M0; bots are created at TG-M1.
- **A fixture set of real Arabic group messages** whose correct normalised and redacted forms are
  known, supplied by the operator or drawn from the plan's examples. Without real dialect text, the
  normaliser cannot be validated against the risk it exists to reduce.
- **No Telegram credential, no model runtime and no network access** are required by anything in this
  milestone, including its tests.
- **The reference application remains read-only.** This domain needs nothing from it in v1
  (Constitution Principle III).
- **Git operations** — branch creation, commits and any history change — are the operator's, not the
  agent's (Constitution Principle IV). The feature branch for this spec was created by the operator.
