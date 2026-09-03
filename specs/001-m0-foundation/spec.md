# Feature Specification: M0 — Local AI Service Foundation

**Feature Branch**: `001-m0-foundation` *(operator-created; see Principle IV)*
**Created**: 2026-09-02
**Status**: Draft
**Milestone**: M0 (first milestone of `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`)
**Input**: User description: "read the constitution, and read carefully the core plans in docs/plan/core/, then start specify the first Milestone (m0)"

## Overview

M0 delivers the **foundation the whole InjazEdu Local AI service is built on**: a local,
self-hosted runtime environment that the operator can start with one command, verify with one
health check, evolve safely through versioned schema migrations, and prove correct with a
quality gate that runs without any AI model present.

M0 deliberately produces **no AI behaviour and no InjazEdu integration**. Its entire value is
that every later milestone — model gateway, textbook parsing, retrieval, question answering,
publishing — starts from an environment that is reproducible, memory-safe on a 16 GB machine,
and impossible to accidentally point at real data.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start and verify the whole local environment (Priority: P1)

The operator sits down at the machine, runs a single documented command, and the complete local
AI environment starts: the request-handling service, the background worker, the database, the
queue/broker, and the control panel. A single health check then tells the operator, in one
response, whether each component is reachable and ready — including the locally hosted model
runtime that lives outside the container environment.

**Why this priority**: Nothing else in the project can be built, demonstrated, or debugged until
the environment starts reliably and reports its own state. This is the minimum viable slice: on
its own it already replaces "is anything broken?" guesswork with a definitive answer.

**Independent Test**: On a machine with only the documented prerequisites installed, run the
start command from a clean checkout and call the health check. Fully testable with no AI model,
no textbook, and no InjazEdu access.

**Acceptance Scenarios**:

1. **Given** a clean checkout and a completed environment configuration file, **When** the
   operator runs the documented start command, **Then** all required components start and the
   health check reports every one of them as healthy.
2. **Given** a fully healthy environment, **When** the operator stops the database and re-runs
   the health check, **Then** the response identifies the database specifically as unhealthy,
   still reports the status of every other component, and the service itself does not crash.
3. **Given** a fully healthy environment, **When** the locally hosted model runtime is not
   running, **Then** the health check reports the model runtime as unreachable while the rest of
   the environment stays usable and is reported healthy.
4. **Given** a stopped environment that has been used before, **When** the operator starts it
   again, **Then** previously stored data is still present.
5. **Given** an environment configuration that is missing a required value, **When** the operator
   starts the environment, **Then** startup fails immediately with a message naming the missing
   configuration value.

---

### User Story 2 - Own the database schema safely through migrations (Priority: P2)

The operator evolves the AI service's database structure exclusively through versioned,
reviewable migrations that can be applied forward and rolled back. The database provides vector
similarity search, which later milestones depend on. The control panel reads and writes data but
is structurally incapable of changing the schema.

**Why this priority**: The schema is the contract every later milestone extends. Establishing a
single owner of schema changes — and denying that power to the control panel — prevents the
class of accident that silently corrupts the corpus later.

**Independent Test**: Apply migrations to an empty database, confirm the vector search capability
is enabled, roll back and re-apply, then attempt a schema change using the control panel's
database credentials and confirm it is refused.

**Acceptance Scenarios**:

1. **Given** an empty database, **When** the operator applies all migrations, **Then** the schema
   reaches the current version and the vector similarity capability is reported as available.
2. **Given** a fully migrated database, **When** the operator applies migrations again, **Then**
   nothing changes and the command succeeds.
3. **Given** a fully migrated database, **When** the operator rolls back the most recent migration
   and re-applies it, **Then** the schema returns to the same version with no manual repair.
4. **Given** the control panel's database credentials, **When** any schema-changing statement is
   attempted with them, **Then** the database refuses it.
5. **Given** the control panel is running, **When** the operator inspects how it starts, **Then**
   it never applies schema changes of its own.

---

### User Story 3 - Prove background work is actually processed (Priority: P3)

The operator submits a trivial diagnostic task, and a background worker — a separate process from
the one serving requests — picks it up, runs it, and records the outcome where the operator can
see it. A task that fails is visibly recorded as failed rather than disappearing.

**Why this priority**: Every expensive operation in this project (parsing, embedding, answering,
generating, publishing) runs as background work. Proving the enqueue → execute → observe loop
now means later milestones debug their own logic, not the plumbing underneath it.

**Independent Test**: Enqueue the diagnostic task and observe it complete; enqueue a task designed
to fail and observe it recorded as failed. No AI model required.

**Acceptance Scenarios**:

1. **Given** a healthy environment, **When** the operator enqueues the diagnostic task, **Then** a
   background worker executes it and the successful outcome is observable.
2. **Given** a healthy environment, **When** an enqueued task raises an error, **Then** the failure
   and its reason are recorded and observable, and the worker stays available for the next task.
3. **Given** the background worker is stopped, **When** a task is enqueued, **Then** the task waits
   and is executed once the worker is started again.

---

### User Story 4 - Sign in to the AI Control Center (Priority: P4)

The operator opens the control panel in a browser and signs in with an account stored in the AI
service's own database. This is the shell that every human review screen in later milestones is
added to.

**Why this priority**: All human review — the part of this project that gates AI output before it
reaches learners — happens here. M0 needs the authenticated shell to exist and to be backed by
the correct database; the review screens themselves belong to later milestones.

**Independent Test**: Create the initial account with the documented command, sign in through the
browser, sign out, and confirm an incorrect password is rejected.

**Acceptance Scenarios**:

1. **Given** the environment is healthy and no account exists, **When** the operator runs the
   documented account-creation step, **Then** an account is created in the AI service's database.
2. **Given** that account exists, **When** the operator signs in with the correct credentials,
   **Then** they reach the control panel's authenticated home screen.
3. **Given** that account exists, **When** an incorrect password is submitted, **Then** access is
   refused and no session is established.
4. **Given** no valid session, **When** any control panel screen is requested directly, **Then**
   the request is redirected to sign-in rather than served.

---

### User Story 5 - Run the quality gate against an isolated test database (Priority: P5)

The operator runs a single command that formats/lints, type-checks, and tests the project. The
tests run offline with no AI model, and any test touching a database uses a disposable test
database whose name marks it as such. If the test configuration would point at a non-test
database, the run refuses to start.

**Why this priority**: This is the mechanism by which every later milestone can be called "done"
(the approved plan requires the full quality gate to pass before any milestone is called done) and the mechanism that enforces
the constitution's non-negotiable test-database isolation rule.

**Independent Test**: Run the quality gate on a clean checkout with no model running and confirm
it passes; then point the test database configuration at a non-test database name and confirm the
run aborts before executing any test.

**Acceptance Scenarios**:

1. **Given** a clean checkout with no AI model running, **When** the operator runs the quality
   gate, **Then** linting, type checking, and tests all execute and pass.
2. **Given** the test configuration names a database without the test marker, **When** the
   operator runs the tests, **Then** the run aborts with an explanatory message before any test
   executes and before any data is modified.
3. **Given** a database-backed test has just run, **When** the operator inspects the development
   and any imported datasets, **Then** they are unchanged.
4. **Given** the test database does not exist, **When** the operator runs the tests, **Then** it is
   created from migrations and fixtures without manual steps.

---

### Edge Cases

- **A required port is already in use** → startup fails with a message naming the port and the
  component that wanted it, rather than a partially started environment.
- **The vector similarity capability is unavailable in the database** → migration fails loudly and
  the health check reports the database as not ready; it must never be silently skipped.
- **Migrations are interrupted midway** → re-running them either completes or fails with a clear
  message; the schema version is never left ambiguous.
- **The queue/broker is unreachable while a task is enqueued** → enqueueing fails visibly to the
  caller instead of silently dropping the task.
- **The machine is under memory pressure** → optional components (workflow automation) are not
  started by default, so the default environment fits the memory budget.
- **The operator has an existing container memory allocation that is too large** → documented as a
  prerequisite check with the required value, verifiable before starting.
- **The environment is started twice** → the second start is a no-op or reports the existing
  environment, rather than creating a conflicting duplicate.
- **A secret is added to the repository by mistake** → the quality gate or repository configuration
  prevents it from being committed.
- **The reference application directory is touched** → any write inside `injazedu/` is a violation;
  M0 reads from it only if it reads from it at all.

## Requirements *(mandatory)*

### Functional Requirements

**Environment lifecycle**

- **FR-001**: The system MUST start every required component of the local AI environment from a
  single documented command run from the repository root.
- **FR-002**: The system MUST stop and restart cleanly with the same command family, preserving all
  stored data across restarts.
- **FR-003**: The system MUST keep optional, non-essential components (workflow automation) excluded
  from the default start, and MUST document how to start them deliberately.
- **FR-004**: The system MUST read all environment-specific settings and credentials from an
  environment configuration file that is excluded from version control, and MUST ship a documented
  example file containing no real secrets.
- **FR-005**: The system MUST fail fast at startup with a message naming the specific missing or
  invalid configuration value.

**Health and observability**

- **FR-006**: The system MUST expose a single health check that reports overall status plus an
  individually named status for: the database, the queue/broker, the background worker, and the
  locally hosted model runtime.
- **FR-007**: The health check MUST return a definitive per-component result even when one or more
  components are down, and MUST NOT itself fail because a dependency is unavailable.
- **FR-008**: The system MUST classify the locally hosted model runtime as an informational
  dependency in M0: its unavailability MUST NOT mark the environment as failed.
- **FR-009**: Every component MUST emit startup and error output the operator can read from the
  environment's logs without attaching a debugger.

**Data store and schema ownership**

- **FR-010**: The system MUST provide a relational data store that supports vector similarity search,
  and MUST verify that capability is enabled as part of migration and health checks.
- **FR-011**: All schema changes MUST be applied exclusively through versioned migrations that record
  the current schema version and support rollback of the most recent change.
- **FR-012**: Applying migrations to an already-current database MUST be a safe no-op.
- **FR-013**: The system MUST provide the control panel with a database identity that can read and
  write data but CANNOT create, alter, or drop schema objects.
- **FR-014**: The control panel MUST NOT run any schema-management step of its own against the AI
  service database, at startup or otherwise.
- **FR-015**: The initial migration MUST create only what M0 requires — the schema-version tracking,
  the vector capability, and the control panel's account/authentication storage. Domain tables for
  documents, chunks, questions, drafts, and jobs are out of scope for M0.

**Background processing**

- **FR-016**: The system MUST run background task processing in a process separate from the one
  serving requests.
- **FR-017**: The system MUST provide a diagnostic task that can be enqueued and whose successful
  completion is observable by the operator.
- **FR-018**: A task that fails MUST be recorded with its failure reason and MUST NOT stop the worker
  from processing subsequent tasks.
- **FR-019**: Tasks enqueued while no worker is running MUST be processed once a worker starts.
- **FR-020**: The system MUST constrain background processing concurrency to values documented as
  safe for a 16 GB machine.

**Control panel**

- **FR-021**: The system MUST provide an authenticated control panel served locally, backed by the AI
  service's own database.
- **FR-022**: The system MUST provide a documented, repeatable step to create the initial operator
  account without hard-coding credentials in the repository.
- **FR-023**: Unauthenticated requests to any control panel screen MUST be redirected to sign-in.
- **FR-024**: The control panel MUST NOT hold or use credentials for any InjazEdu business database.

**Quality gate and test safety**

- **FR-025**: The system MUST provide a single command that runs formatting/lint checks, static type
  checks, and the automated test suite.
- **FR-026**: The entire test suite MUST pass with no AI model running and with no network access to
  any external service.
- **FR-027**: Any test that touches a database MUST use a dedicated test database whose name contains
  the `_test` marker and which is configured through the testing environment.
- **FR-028**: The test run MUST abort before executing any test if the configured test database name
  does not carry the `_test` marker.
- **FR-029**: The test database MUST be creatable and re-creatable from migrations and fixtures with
  no manual steps.
- **FR-030**: Destructive database operations MUST be impossible to run against development, imported,
  mirrored, or production datasets from the test suite.

**Repository and boundaries**

- **FR-031**: The repository MUST establish the directory layout that later milestones extend, so no
  later milestone needs to relocate existing code to add its own.
- **FR-032**: The system MUST NOT create, modify, delete, or generate any file inside the `injazedu/`
  reference directory.
- **FR-033**: The system MUST NOT contain any credential, token, or secret value in version-controlled
  files.
- **FR-034**: Documentation MUST record the prerequisites, the memory allocation the operator must
  configure, the local model runtime settings, the start/stop/health commands, and the known
  limitations of M0.

### Out of Scope (deferred to named later milestones)

- Any AI model call, prompt, or model-provider abstraction — **M1**.
- Textbook upload, parsing, structure detection, or versioning — **M2/M3**.
- Text normalisation, chunking, embeddings, or retrieval — **M4**.
- Question extraction, AI answering, or the review queue screens — **M5**.
- Any InjazEdu API call, publishing, or InjazEdu-side change — **M6**.
- MCQ generation, validation battery, quiz building — **M7/M8**.
- Corpus-wide sync and scale-out — **M9**.
- Evaluation dashboards and model A/B comparison — **M10**.
- Workflow automation and messaging integrations — **M11–M13**.
- Any student- or customer-facing AI feature — explicit non-goal until **M13**.

### Key Entities

- **Environment configuration**: The set of settings and credentials that make the environment run on
  a specific machine. Lives outside version control; has a documented, secret-free example.
- **Schema version record**: The stored marker of which migrations have been applied, making the
  database's structural state unambiguous and rollback possible.
- **Control Center account**: An operator/reviewer identity stored in the AI service's database, used
  to sign in to the control panel. Distinct from any InjazEdu user.
- **Health report**: The per-component readiness snapshot returned by the health check: database,
  queue/broker, background worker, model runtime.
- **Background task record**: The observable trace of an enqueued unit of work — its identity, state,
  and, on failure, its reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Starting from a clean checkout on a machine with only the documented prerequisites, the
  operator reaches a fully healthy environment in under 15 minutes following the documentation alone,
  with no undocumented step.
- **SC-002**: On a warm machine, the environment reaches fully healthy within 90 seconds of the start
  command, and the health check answers in under 2 seconds.
- **SC-003**: The health check names the status of all 4 required components in a single response, and
  when exactly one component is stopped it identifies that component correctly on the first check —
  verified for each component in turn.
- **SC-004**: The default running environment stays within the documented 5 GB container memory
  allocation while idle, leaving at least 6 GB of system memory free for the locally hosted model.
- **SC-005**: 100% of schema changes are applied by the migration tool; 0 schema changes originate
  from the control panel, and every attempted schema change using the control panel's database
  identity is refused.
- **SC-006**: A migrate → roll back → re-migrate cycle on an empty database returns the schema to the
  identical version with 0 manual repair steps.
- **SC-007**: An enqueued diagnostic task is executed and its outcome is observable within 10 seconds;
  a failing task is recorded with a reason in 100% of attempts, and the worker remains available.
- **SC-008**: The operator signs in to the control panel and reaches the authenticated home screen in
  under 1 minute after running the documented account-creation step; incorrect credentials are
  refused 100% of the time.
- **SC-009**: The full quality gate completes in under 3 minutes and passes with 0 AI models running
  and 0 external network calls.
- **SC-010**: 0 automated tests execute against a database whose name lacks the `_test` marker —
  enforced by an abort that triggers 100% of the time when misconfigured, verified by deliberate
  misconfiguration.
- **SC-011**: 0 secrets are present in version-controlled files, verified by a repository scan.
- **SC-012**: 0 files inside the `injazedu/` directory are created, modified, or deleted during M0 —
  verified by the repository's own change listing.
- **SC-013**: Restarting the environment preserves 100% of previously stored data.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the approved plan, the constitution, or measurements already recorded in the plan.

- **Operator and machine**: A solo operator working on the Apple Silicon laptop with 16 GB of memory
  described in the plan's ground-truth section. Multi-developer setup, CI infrastructure, and
  non-macOS hosts are out of scope for M0.
- **Local-first**: Nothing in M0 is exposed to the public internet and no inbound network access is
  required. The environment binds locally.
- **Model runtime placement**: The locally hosted model runtime runs natively on the host (not inside
  the container environment) because hardware acceleration is unavailable to containers. M0 only
  checks that it is reachable and that its documented settings are applied; using it is M1's work.
- **Schema ownership**: The migration tool is the sole owner of the AI database schema. The control
  panel is a data consumer with a restricted database identity — this is an architecture rule from the
  approved plan, not a preference.
- **M0's migration content**: The first migration establishes only schema-version tracking, the vector
  capability, and control panel account storage. The domain data model from the plan is introduced by
  the milestones that need it.
- **Account creation**: The initial control panel account is created by a documented command reading
  credentials from the environment configuration; no default or hard-coded credentials ship.
- **Test isolation**: Enforced by both naming (`_test`) and a runtime guard, per the constitution's
  non-negotiable rule.
- **Deterministic offline tests**: M0's tests require no AI model. Any test that would need one is
  deferred to the milestone that introduces the model abstraction.
- **Definition of done**: A milestone is done only when implementation exists, tests exist and pass,
  docs and configuration are updated, a manual smoke test succeeds, no unrelated scope was added, and
  known limitations are written down.

## Dependencies

- **Container runtime** installed on the operator's machine, with its memory allocation reduced to the
  documented value before M0 can meet its memory success criterion.
- **Locally hosted model runtime** installed natively with the plan's models available. Required for
  the health check to report it as reachable; not required for any M0 test to pass.
- **The `injazedu/` reference application** is read-only. M0 needs nothing from it, and changes to
  InjazEdu are the InjazEdu team's work, listed as such (Constitution Principle III).
- **Git operations** — branch creation, commits, and any history change — are the operator's, not the
  agent's (Constitution Principle IV). The feature branch for this spec is created by the operator.
