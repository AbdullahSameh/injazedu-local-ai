# Feature Specification: M1 — Model Gateway

**Feature Branch**: `m1/model-gateway` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/002-m1-model-gateway`
**Created**: 2026-09-03
**Status**: Draft
**Milestone**: M1 (second milestone of `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`)
**Input**: User description: "read the constitution, and read carefully the core plans in docs/plan/core/, then start specify the first Milestone (m1)"

## Overview

M1 delivers the **single doorway between this project and any AI model**. From the end of M1
onward, no part of the system talks to a model directly: everything asks the gateway, and the
gateway decides which model, on which endpoint, with which parameters, one call at a time.

Two capabilities go through that doorway. **Structured generation** — the caller states the exact
shape it needs back and receives either a validated object of that shape or a clear failure, never
free text to parse. **Embedding** — the caller supplies text and says whether it is a document or a
query, and receives fixed-width vectors, with the retrieval-critical prefix handling done inside
the gateway where business code cannot forget it.

Three properties make the doorway worth building rather than calling the model inline:

1. **Portability.** Which model answers, and where it runs, is a stored configuration row. Moving
   from the laptop's model runtime to a GPU server is an edit to that row — zero business code
   changes. This is the milestone's headline acceptance criterion.
2. **Survivability.** A 16 GB laptop serialises model work on one hardware context. The gateway
   owns the single-occupancy lanes, the timeouts, the retries and the circuit breaker, so no later
   milestone can accidentally queue-storm the machine.
3. **Testability.** Deterministic stand-in providers let the entire pipeline — every milestone after
   this one — run offline, with no model and no accelerator, in the quality gate.

M1 produces **no textbook processing, no retrieval, no prompts and no InjazEdu integration**. It is
the seam those milestones plug into, plus the evidence that the seam holds.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask for a structured result and get exactly that shape (Priority: P1)

A developer writing later-milestone logic needs a machine-readable answer from a model — a chosen
option key with a supporting quotation, say. They describe the shape they need, hand it to the
gateway with their input text, and receive a validated object of that shape. If the model cannot
produce it, they receive an explicit, typed failure that says why. They never receive a string to
parse, and they never write model-runtime-specific code.

**Why this priority**: Every AI behaviour in the remaining twelve milestones is a structured call.
Until callers can rely on the shape of what comes back, nothing downstream can be written safely.
On its own this slice already replaces the riskiest pattern in AI work — parsing free text — with a
contract.

**Independent Test**: Request a small structured result using the deterministic stand-in provider
and confirm the returned object matches the requested shape; then request one whose shape the
stand-in is configured to violate and confirm a typed failure, not a partial object. Fully testable
with no model running.

**Acceptance Scenarios**:

1. **Given** a configured active generation profile, **When** a caller requests a structured result
   describing a required shape, **Then** the caller receives an object that satisfies that shape in
   full.
2. **Given** the model produces output that does not satisfy the requested shape, **When** the
   gateway has exhausted its retry budget, **Then** the caller receives an explicit failure naming
   the shape violation, and receives no object.
3. **Given** a caller requests plain text rather than a shape, **When** the call succeeds, **Then**
   the caller receives the text plus the call's token counts and duration.
4. **Given** the local model runtime is not running, **When** a generation is requested, **Then** the
   caller receives a failure that names the unreachable runtime within the documented timeout, and
   the calling process stays healthy.
5. **Given** the active profile names a model the runtime does not have, **When** a generation is
   requested, **Then** the failure names that model specifically rather than reporting a generic
   error.

---

### User Story 2 - Embed text correctly without knowing how embedding works (Priority: P2)

A developer needs vectors for a batch of textbook passages, and later for a search query. They pass
the text and declare which of the two it is. The gateway applies the model's required task
framing internally, batches the work at the documented size, and returns one fixed-width vector per
input, in the order supplied. The developer never writes a prefix, never picks a batch size, and
cannot silently produce vectors of the wrong width.

**Why this priority**: Retrieval quality — the hard gate that blocks every generation milestone —
depends on the document/query framing being applied identically and on the vector width being
pinned. The plan measured this framing widening the relevant-vs-irrelevant margin; a single missed
prefix at one call site silently degrades the whole corpus with no visible error.

**Independent Test**: Embed a batch of passages and a query through the stand-in provider and
confirm one vector per input in input order, all of the profile's declared width; then configure the
provider to return a wrong-width vector and confirm the call fails loudly. No model required.

**Acceptance Scenarios**:

1. **Given** an active embedding profile, **When** a caller embeds a list of passages declared as
   documents, **Then** exactly one vector per input is returned, in the same order, each of the
   profile's declared width.
2. **Given** the same active profile, **When** a caller embeds a search query declared as a query,
   **Then** the gateway applies the query framing, which differs from the document framing.
3. **Given** a caller's code, **When** it is inspected, **Then** it contains no task-framing text —
   the framing exists only inside the gateway.
4. **Given** a returned vector whose width differs from the active profile's declared width,
   **When** the gateway receives it, **Then** the call fails with that mismatch named, and no vector
   is handed to the caller.
5. **Given** a batch larger than the configured batch size, **When** it is embedded, **Then** the
   gateway splits it internally and the caller still receives one correctly ordered result set.
6. **Given** an input list containing empty or whitespace-only text, **When** it is embedded,
   **Then** the outcome is explicit — either a named rejection or a defined result — never a
   silently shortened result set.

---

### User Story 3 - Change the model, or where it runs, without changing code (Priority: P3)

The operator decides to try a different model, or to move model serving off the laptop onto a GPU
machine. They edit the model profile in the Control Center — its endpoint, its model name, its
parameters — mark it active, and the running system uses it. No source file is touched, no
redeployment of business logic occurs, and the differences between serving runtimes are absorbed by
the gateway.

**Why this priority**: This is M1's stated acceptance criterion and the reason the abstraction
exists. It is also the project's insurance policy: the plan's model roster is provisional, the
laptop is a temporary host, and every later milestone would otherwise harden the wrong choice into
code.

**Independent Test**: With the system running, point the active generation profile at a different
endpoint and model, then re-run the same unchanged test suite and smoke command and confirm they
exercise the new target. Diff the repository to confirm zero business-code changes.

**Acceptance Scenarios**:

1. **Given** a running system, **When** the operator changes the active generation profile's endpoint
   and model name and saves, **Then** subsequent calls use the new target within the documented
   refresh window, with no restart of business logic and no code change.
2. **Given** two serving runtimes that express output-shape constraints differently, **When** the
   same structured request is issued against each, **Then** both return an object satisfying the same
   requested shape and the caller's code is identical in both cases.
3. **Given** the operator marks a second profile active for a role that already has one active,
   **When** the change is saved, **Then** the system resolves to exactly one active profile per role
   by a documented, deterministic rule — never two.
4. **Given** an embedding profile whose declared vector width differs from the current one, **When**
   it is registered, **Then** it is stored as an additional profile and the existing profile's
   vectors and configuration are left intact.
5. **Given** a profile that names a credential, **When** it is stored, **Then** the row holds a
   reference to an environment key, never the credential value itself.

---

### User Story 4 - Run the entire pipeline with no model at all (Priority: P4)

A developer or the quality gate runs the full test suite on a machine with no model runtime, no
accelerator and no network access to anything. Deterministic stand-in providers answer every model
and embedding call with canned, correctly shaped results, so tests exercise real pipeline logic and
produce the same outcome on every run. Tests that genuinely need a live model are separately marked
and are not part of the default gate.

**Why this priority**: The approved plan calls this the mechanism that makes the project executable
at all — without it, every later milestone's tests are slow, non-deterministic and dependent on a
model being loaded. It also keeps the quality gate honest on a machine whose memory is already
budgeted to the limit.

**Independent Test**: Run the quality gate with the model runtime stopped and no network reachable,
confirm it passes; run it repeatedly and confirm byte-identical results; confirm the live-model
tests were skipped and are individually runnable on demand.

**Acceptance Scenarios**:

1. **Given** no model runtime running and no external network access, **When** the quality gate is
   run, **Then** every test in the default suite executes and passes.
2. **Given** the same inputs, **When** a stand-in-backed test is run repeatedly, **Then** it produces
   identical results every time.
3. **Given** a stand-in generation provider, **When** it answers a structured request, **Then** its
   answer satisfies the requested shape, so tests exercise the same validation path as the real
   provider.
4. **Given** tests that require a live model, **When** the default quality gate runs, **Then** they
   are excluded, and **When** they are invoked deliberately with a runtime available, **Then** they
   execute.
5. **Given** the local model runtime is available, **When** the operator runs the documented smoke
   command, **Then** one real round-trip completes and reports the returned shape, the token counts
   and the measured duration.

---

### User Story 5 - Keep the machine alive under concurrent demand (Priority: P5)

Several background tasks want model work at the same time. The gateway admits one generation at a
time and one embedding at a time; the rest wait. A call that runs too long is abandoned at a
documented limit and its place in the lane is released. Transient failures are retried a bounded
number of times with spacing; after a run of consecutive failures the gateway stops attempting for a
while and fails fast, then recovers by itself.

**Why this priority**: The plan names uncontrolled concurrency as the thing that will otherwise break
this machine — the model runtime serialises on one hardware context, and the default worker settings
will queue-storm it and exhaust 16 GB. The safeguard has to exist before the milestones that issue
hundreds of calls per run, but it protects work that does not exist yet, so it follows the
capabilities it protects.

**Independent Test**: Issue several simultaneous generation requests against an instrumented
stand-in and confirm at most one is in flight at any moment while the rest complete in turn; force a
call to exceed the limit and confirm it is abandoned and the lane frees; force consecutive failures
and confirm calls then fail immediately rather than waiting, and that normal service resumes.

**Acceptance Scenarios**:

1. **Given** several callers request generation simultaneously, **When** they are admitted, **Then**
   at most one generation is in flight at any moment and every caller eventually receives a result or
   a failure.
2. **Given** generation and embedding are requested at the same time, **When** both run, **Then**
   they are admitted through separate lanes, each single-occupancy.
3. **Given** the request-serving process and several background worker processes all request
   generation at the same time, **When** they are admitted, **Then** still at most one generation is
   in flight across the whole machine — the limit is not per process.
4. **Given** a call exceeds the documented time limit, **When** the limit is reached, **Then** the
   call is abandoned, the caller is told it timed out, and the lane becomes available for the next
   caller.
5. **Given** a transient failure, **When** the gateway retries, **Then** it retries no more than the
   documented number of times, with spacing between attempts, before failing.
6. **Given** a failure caused by the caller's own request — an impossible shape, an unknown model —
   **When** it occurs, **Then** it is not retried and the caller is told immediately.
7. **Given** a documented number of consecutive failures against a profile, **When** the next call is
   made, **Then** it fails immediately instead of waiting for the timeout, and after the documented
   recovery interval normal attempts resume automatically.
8. **Given** calls that time out, fail or are cancelled — or a process that dies mid-call — **When** a
   long run of such calls completes, **Then** no lane capacity is permanently lost.

---

### User Story 6 - Know what every model call cost, without storing the book (Priority: P6)

The operator wants to know how much model time the system is spending and where it is failing. Every
call the gateway makes — successful or not — leaves a record: which profile, which operation, how
many tokens in and out, how long it took, and the outcome or error. The record carries a stable
fingerprint of the request instead of the request text, because that text is copyrighted textbook
content. Capturing the full text is possible but is an explicit, off-by-default choice.

**Why this priority**: The plan makes cost and latency per approved question a tracked metric and
makes prompt-and-model comparison the basis of every future quality decision; both read from these
records. Recording from the gateway's first day means M2 onward accumulate that history for free
instead of being retrofitted. It is last because nothing in M1 is blocked by it.

**Independent Test**: Issue successful and failing calls through the stand-in provider and confirm a
record exists for each with token counts, duration and outcome; confirm no record contains request
text while the debug capture setting is off; enable the setting and confirm capture happens and is
visibly on.

**Acceptance Scenarios**:

1. **Given** any completed model call, **When** it finishes, **Then** a record exists naming the
   profile, the operation, the input and output token counts, the duration and the outcome.
2. **Given** a failed model call, **When** it finishes, **Then** a record exists with the failure
   reason.
3. **Given** the debug capture setting is off — its default — **When** records are inspected,
   **Then** none contains request or response text, and each carries a stable fingerprint of the
   request instead.
4. **Given** the same request is issued twice, **When** the records are compared, **Then** their
   request fingerprints match.
5. **Given** recording itself fails, **When** a model call is made, **Then** the model call's own
   result is unaffected and the recording failure is visible in the logs.

---

### Edge Cases

- **The model runtime is unreachable** → a typed failure naming the runtime, returned within the
  documented timeout; never an indefinite hang.
- **The runtime answers but the named model is not installed** → the failure names the model, so the
  operator knows to install it rather than debugging the gateway.
- **The model returns valid data of the wrong shape** (missing field, extra field, wrong type) →
  retried within budget, then failed explicitly; a partially valid object is never handed to a caller.
- **A structured request describes an impossible or malformed shape** → rejected before any model
  call, and not retried.
- **Input exceeds the model's context window** → bounded and reported by the gateway rather than
  silently truncated by the runtime.
- **A batch embedding call fails part-way** → the whole batch fails, or every input's outcome is
  individually unambiguous; the caller never receives a quietly shortened list.
- **No profile is active for a requested role** → a startup-or-call-time failure naming the missing
  role, not a fallback to a hard-coded default.
- **Two profiles are marked active for the same role** → resolved deterministically to one by a
  documented rule; the ambiguity is surfaced to the operator.
- **An embedding profile's declared width is changed after vectors exist** → refused; a new width is
  a new profile, so existing vectors stay valid (they are stored from M4 onward).
- **A model call is cancelled while holding a lane** → the lane is released; repeated cancellation
  cannot starve the system.
- **The circuit breaker is open** → callers are told the breaker is open rather than receiving a
  timeout, and recovery needs no operator action.
- **Full-prompt capture is left switched on** → its state is visible to the operator, and it is off
  by default in shipped configuration.
- **A developer imports a model-runtime library outside the provider layer** → the quality gate fails
  the build; the architecture rule is mechanically enforced, not documented and hoped for.
- **The operator saves a profile pointing at an endpoint that does not answer** → the save is either
  refused or accepted with a visible warning; the operator is not left guessing why calls fail.

## Requirements *(mandatory)*

### Functional Requirements

**The gateway boundary**

- **FR-001**: The system MUST route every model and embedding call through one gateway; no other path
  to a model may exist.
- **FR-002**: Model-runtime-specific libraries, request shapes and response shapes MUST be confined to
  the provider layer, and this MUST be enforced automatically by the quality gate rather than by
  convention.
- **FR-003**: The gateway MUST offer plain text generation, returning the generated text together with
  the call's token counts and duration.
- **FR-004**: The gateway MUST offer structured generation against a caller-supplied output shape, and
  MUST return either an object that fully satisfies that shape or an explicit typed failure — never
  unvalidated text for the caller to parse.
- **FR-005**: The gateway MUST offer embedding of a single text and of a batch of texts, with the
  caller declaring whether the text is a document or a query.
- **FR-006**: The gateway MUST expose its capabilities as stable interfaces that both real and
  stand-in implementations satisfy, so callers depend on the interface and never on an implementation.
- **FR-007**: The gateway MUST NOT contain business rules; it selects providers, enforces limits,
  validates shapes and records calls, and nothing else.
- **FR-008**: Every gateway failure MUST identify its cause by a distinguishable category — the
  runtime is unreachable, the named model is unavailable, the request was rejected, the output
  violated the requested shape, the call timed out, or the profile is currently failing fast — and
  MUST name the specific model or profile involved. A caller MUST be able to tell a retryable
  condition from a permanent one without reading message text.

**Model profiles**

- **FR-009**: The system MUST store model profiles, each recording at minimum: a unique name, the
  provider kind, the endpoint, the model identifier, the role (generation or embedding), call
  parameters, the vector width for embedding roles, and whether it is active.
- **FR-010**: The system MUST seed the approved plan's model roster as profiles, and re-running the
  seed MUST NOT create duplicates or overwrite operator edits.
- **FR-011**: The system MUST resolve exactly one active profile per role, deterministically, and MUST
  fail with a message naming the role when none is active.
- **FR-012**: Changing which model is used, where it is served, or with which parameters MUST require
  zero changes to business code.
- **FR-013**: A change to the active profile MUST take effect within a documented bounded window
  without restarting business logic.
- **FR-014**: The provider layer MUST absorb differences in how serving runtimes express output-shape
  constraints, so one caller request works unchanged against any supported runtime.
- **FR-015**: A profile MUST NOT store a credential value; where a credential is needed the profile
  MUST reference an environment key whose value lives outside version control.
- **FR-016**: Registering a profile with a different vector width MUST be additive — it MUST NOT alter
  or invalidate any existing profile.
- **FR-017**: An embedding profile's declared vector width MUST be immutable once set.

**Embedding behaviour**

- **FR-018**: The gateway MUST apply the active embedding model's required task framing internally,
  using different framing for documents and for queries; callers MUST never supply framing.
- **FR-019**: The gateway MUST batch embedding work at a documented default size, configurable, and
  MUST split oversized caller batches internally.
- **FR-020**: Batch embedding MUST return exactly one vector per input, in the input order.
- **FR-021**: The gateway MUST reject any vector whose width differs from the active profile's
  declared width, name the mismatch, and hand nothing to the caller.
- **FR-022**: The gateway MUST define and document a single outcome for degenerate inputs — empty or
  whitespace-only text — applied identically to single and batch calls, and MUST NOT return a result
  set shorter than the input list under any circumstance.

**Deterministic offline operation**

- **FR-023**: The system MUST provide stand-in generation and embedding providers that satisfy the
  same interfaces as the real ones.
- **FR-024**: Stand-in providers MUST be deterministic — identical inputs produce identical outputs —
  and their structured answers MUST satisfy the requested shape, so tests exercise the real validation
  path.
- **FR-025**: Stand-in providers MUST be configurable to simulate failure modes — shape violations,
  timeouts, transport errors, wrong vector widths — so the gateway's error handling is testable.
- **FR-026**: The default test suite MUST pass with no model runtime running and with no external
  network access.
- **FR-027**: Tests requiring a live model runtime MUST be individually marked, excluded from the
  default quality gate, and runnable on demand.
- **FR-028**: The system MUST provide a documented command that performs one real round-trip against
  the local runtime and reports the returned shape, token counts and duration.

**Concurrency and resilience**

- **FR-029**: The gateway MUST admit at most one generation call at a time and at most one embedding
  call at a time, through separate single-occupancy lanes. The limit MUST hold **across every process
  that can make model calls** — the request-serving process and all background worker processes
  together — not merely within one process, because the constrained resource is the machine's single
  model runtime.
- **FR-030**: Every model call MUST have a per-call time limit with a documented default; exceeding it
  MUST abandon the call and inform the caller.
- **FR-031**: The gateway MUST retry transient failures a bounded, documented number of times with
  spacing between attempts.
- **FR-032**: Failures caused by the request itself — a malformed shape, an unknown model, an
  authentication rejection — MUST NOT be retried.
- **FR-033**: After a documented number of consecutive failures against a profile, the gateway MUST
  fail subsequent calls immediately rather than waiting for the timeout, and MUST resume attempting
  automatically after a documented interval.
- **FR-034**: Lane capacity and connections MUST be released on success, failure, timeout and
  cancellation alike; sustained failure MUST NOT permanently reduce capacity. A process that dies
  while holding a lane MUST NOT hold it permanently.
- **FR-035**: All concurrency, timeout, retry and circuit-breaker values MUST be documented and
  configurable, with defaults stated as safe for the project's 16 GB target machine.
- **FR-036**: Generation parameters that affect memory — context size and maximum output length — MUST
  be bounded per call from the active profile, with documented defaults.

**Call accounting**

- **FR-037**: The gateway MUST record every model call — successful or failed — with the profile, the
  operation, the input and output token counts, the duration and the outcome or failure reason.
- **FR-038**: Call records MUST NOT contain request or response text by default; each MUST instead
  carry a stable fingerprint of the request that is identical for identical requests.
- **FR-039**: Capturing full request and response text MUST be an explicit configuration choice that
  is off by default and whose current state is visible to the operator.
- **FR-040**: A failure to record a call MUST NOT fail the model call itself, and MUST be visible in
  the logs.
- **FR-041**: Call records MUST be able to reference the job and the prompt version that caused them
  once those exist in later milestones, without a rewrite of the record's shape.

**Control Center**

- **FR-042**: The Control Center MUST let an authenticated operator list, create, edit and deactivate
  model profiles, including endpoint, model identifier, parameters and active state.
- **FR-043**: The Control Center MUST prevent, at save time, states the gateway cannot resolve —
  notably leaving a role with no active profile, and changing an embedding profile's vector width.
- **FR-044**: The Control Center MUST NOT display or store a credential value in a profile; it MUST
  work with the environment key reference only.
- **FR-045**: The Control Center MUST let the operator test a profile's endpoint and report the
  outcome, so a misconfigured profile is caught at edit time rather than at call time.
- **FR-046**: All Control Center changes to profiles MUST be data changes only; the Control Center
  MUST NOT gain any schema-changing capability (M0's restricted database identity stands).

**Boundaries and safety**

- **FR-047**: All schema additions MUST be applied through the existing versioned migration mechanism,
  which remains the sole owner of the AI service's schema.
- **FR-048**: The system MUST NOT call any externally hosted AI provider; all model calls target a
  locally reachable runtime.
- **FR-049**: The system MUST NOT contain any credential, token or secret value in version-controlled
  files.
- **FR-050**: The system MUST NOT create, modify, delete or generate any file inside the `injazedu/`
  reference directory.
- **FR-051**: Documentation MUST record the model roster and which profile is active, the runtime
  settings the operator must apply, the procedure for switching model or endpoint, the concurrency and
  timeout defaults, the smoke command, and M1's known limitations.

### Out of Scope (deferred to named later milestones)

- Prompt templates, prompt versioning, and any Arabic prompt text — **M5** (answering) and **M7**
  (generation). M1 carries no prompt content.
- Token counting for chunk sizing. The approved plan routes it through the gateway; it is added with
  the milestone that consumes it — **M4**.
- Storing embeddings, vector indexes, and the re-embedding backfill path — **M4**. M1 produces vectors
  and pins their width; it persists none.
- Retrieval, hybrid search and result fusion — **M4**.
- Textbook upload, parsing and structure detection — **M2/M3**.
- Question extraction, AI answering, answer verification and self-consistency voting — **M5**.
- MCQ generation and the validation battery — **M7/M8**.
- Any InjazEdu API call or InjazEdu-side change — **M6**.
- Model and prompt A/B comparison, evaluation dashboards and the metrics that read call records —
  **M10**. M1 creates the records; it reports on nothing.
- Deploying a second serving runtime on other hardware. M1 builds and proves the seam; the migration
  itself is an operational decision, not a milestone deliverable.
- Reranking models, vision models and speech — not in the approved plan's v1.

### Key Entities

- **Model profile**: A named, operator-editable description of one model, at one endpoint, for one
  role, with its call parameters and — for embedding roles — its declared vector width. Choosing a
  different model means activating a different profile, never editing code.
- **Structured result contract**: The output shape a caller declares it needs. The gateway either
  satisfies it completely or fails; it is the boundary that keeps free-text parsing out of the system.
- **Text kind**: The caller's declaration that a text is a document or a query, which determines the
  task framing the gateway applies. Getting this wrong degrades retrieval silently, so it is an
  explicit part of every embedding request.
- **Execution lane**: The single-occupancy resource that serialises model work, one for generation and
  one for embedding, so the machine is never asked to run two model operations at once.
- **Call record**: The per-call accounting trace — profile, operation, token counts, duration, outcome
  — carrying a fingerprint of the request rather than its copyrighted text.
- **Stand-in provider**: A deterministic substitute for a model that returns canned, correctly shaped
  results and can be told to fail in specific ways, so the whole system runs and is tested offline.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of model and embedding calls in the codebase go through the gateway, and 0 direct
  references to a model-runtime library exist outside the gateway's provider layer — verified by an
  automated check that fails the quality gate when violated.
- **SC-002**: Switching the active generation profile to a different model at a different endpoint
  requires 0 changed lines of business code and 0 restarts of business logic, and the same unchanged
  test suite and smoke command then exercise the new target.
- **SC-003**: 100% of structured results handed to callers satisfy the requested shape; across a
  deliberate fault-injection run, 0 partially valid objects reach a caller.
- **SC-004**: 100% of embedding vectors returned match the active profile's declared width, and a
  deliberately mismatched width is rejected on 100% of attempts.
- **SC-005**: Task framing is applied by the gateway on 100% of embedding calls, and 0 framing strings
  appear anywhere outside the provider layer.
- **SC-006**: Under 8 simultaneous generation requests spread across the request-serving process and
  all background worker processes, at most 1 call is in flight at any observed moment, 100% of
  requests are eventually answered, and the machine records 0 out-of-memory failures while at least
  6 GB of system memory stays free for the model runtime.
- **SC-007**: Routing embedding work through the gateway costs no more than 10% throughput against a
  direct call at the documented batch size, measured on real textbook-sized passages.
- **SC-008**: A call exceeding the time limit is abandoned within that limit on 100% of attempts, and
  after a 100-call run mixing successes, timeouts, failures and cancellations, lane capacity is
  identical to its starting value.
- **SC-009**: After the documented number of consecutive failures, subsequent calls fail in under 1
  second instead of waiting for the full timeout, and normal service resumes with 0 operator actions
  once the runtime recovers.
- **SC-010**: The default quality gate passes with 0 model runtimes running and 0 external network
  calls, and completes in under 5 minutes.
- **SC-011**: A stand-in-backed test run repeated 10 times produces identical results 10 out of 10
  times.
- **SC-012**: 100% of model calls, successful or failed, produce a call record with token counts and
  duration; 0 records contain request or response text while full capture is off; identical requests
  produce identical fingerprints on 100% of comparisons.
- **SC-013**: Running the profile seed twice produces the same profile set with 0 duplicates and 0
  operator edits lost.
- **SC-014**: The operator changes a profile's endpoint and model in the Control Center and observes
  the change take effect in under 1 minute, and 100% of attempts to leave a role with no active
  profile or to change an embedding profile's vector width are refused.
- **SC-015**: The documented smoke command completes one real round-trip against the local runtime and
  reports a shape-valid result with its token counts and duration.
- **SC-016**: Every distinct failure condition — unreachable runtime, unavailable model, rejected
  request, shape violation, timeout, failing-fast profile — is reported as its own distinguishable
  category on 100% of fault-injection attempts, so a caller can branch on it without matching message
  text.
- **SC-017**: 0 secrets appear in version-controlled files and 0 files inside `injazedu/` are created,
  modified or deleted during M1 — both verified by a repository scan.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the approved plan, the constitution, measurements already recorded in the plan, or an
operator decision recorded during specification.

- **Operator decision — call accounting is in M1.** The milestone's one-line summary does not mention
  it, but the approved plan assigns token accounting to the gateway and defines both the record's
  contents and its redaction policy. Recording from the gateway's first day means M2 onward accumulate
  cost and latency history without a retrofit. Confirmed with the operator.
- **Operator decision — the currently installed generation model stays active.** The full recommended
  roster is seeded as profiles, but the model already present on the machine remains the active
  default, so M1 requires no multi-gigabyte download and no change to the memory budget. Promoting the
  plan's recommended larger generator is then a one-row edit — which is exactly the property M1 exists
  to prove. Confirmed with the operator.
- **Operator decision — the Control Center gets full profile management.** Profiles are created by the
  seed but are thereafter operator-editable through the Control Center, making the model swap an
  operator action rather than a database edit. Confirmed with the operator.
- **Single active profile per role.** The profile table supports many profiles so that later
  comparison work is additive, but M1 resolves exactly one active profile per role. Running two models
  side by side for comparison belongs to the evaluation milestone.
- **Call records reference later concepts loosely.** Records can point at the job and the prompt
  version that caused them, but those tables do not exist yet, so those references stay optional and
  unconstrained until the milestones that create them.
- **Vectors are produced, not stored.** M1 proves vectors come back correctly sized and correctly
  framed. Persisting them, indexing them and backfilling them when the model changes is the retrieval
  milestone's work.
- **Concurrency of one is a hardware fact.** The local runtime serialises on a single hardware context;
  single-occupancy lanes are a constraint, not a tuning preference. The values for timeout, retries and
  the failure threshold are the approved plan's, and are configurable.
- **The lane is machine-wide, not per process.** The approved plan pairs a single-occupancy lane with
  multiple worker processes, which is only coherent if the lane is shared across processes: the
  constrained resource is one model runtime on one machine, so a per-process limit would still admit
  one call per process and defeat the purpose. The environment already runs a shared coordination
  service from M0, so this adds no new infrastructure. Recorded here because the plan's wording is
  ambiguous and this reading changes the design.
- **Failures are a closed set of categories, not messages.** Retry policy, the circuit breaker, and
  every later milestone's error handling all branch on *why* a call failed. Making the categories part
  of the gateway's contract is what lets FR-032's "do not retry the caller's own mistake" rule be
  implemented at all.
- **Local-only model access.** No externally hosted AI provider is contacted, in line with the
  constitution's local-first rule and the copyright position on textbook content.
- **Fingerprinting over storage.** Request text is copyrighted textbook content, so records store a
  fingerprint by default. Full capture exists for debugging and ships off.
- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was
  added, and known limitations are written down.

## Dependencies

- **M0 must be complete and healthy**: the running environment, the vector-capable database with
  migrations as its sole schema owner, the queue and background worker, the Control Center with its
  restricted database identity, and the quality gate with its enforced test-database isolation.
- **The local model runtime installed natively** with the documented settings applied and at least the
  currently installed generation and embedding models available. Required for the marked live-model
  tests and the smoke command only — no test in the default quality gate depends on it.
- **The approved plan's model roster** (`§16.1`) as the source of the seeded profiles, and its
  concurrency, timeout and retry values (`§16.4`) as the documented defaults.
- **The `injazedu/` reference application remains read-only.** M1 needs nothing from it, and changes to
  InjazEdu are the InjazEdu team's work (Constitution Principle III).
- **Git operations** — branch creation, commits and any history change — are the operator's, not the
  agent's (Constitution Principle IV). The feature branch for this spec was created by the operator.
