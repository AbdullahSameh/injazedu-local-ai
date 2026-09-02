<!--
Sync Impact Report
==================
Version change: (template, unversioned) → 1.0.0
Rationale: First ratification. All template placeholders replaced with concrete,
enforceable rules for the InjazEdu Local AI project.

Principles defined (5):
  I.   Risk-Proportional Testing
  II.  Test Database Isolation (NON-NEGOTIABLE)
  III. The injazedu/ Directory Is Read-Only (NON-NEGOTIABLE)
  IV.  Git Is Operator-Owned (NON-NEGOTIABLE)
  V.   Stay Inside the Approved Scope

Sections added:
  - Additional Constraints (data safety & AI output)
  - Development Workflow
  - Governance

Sections removed: none (template placeholders [SECTION_2_NAME]/[SECTION_3_NAME] resolved)

Template consistency:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate is generic
     ("[Gates determined based on constitution file]"); the gate list in
     "Development Workflow" below is what plans must instantiate. No edit required.
  ✅ .specify/templates/spec-template.md — no constitution-specific slots. No edit required.
  ✅ .specify/templates/tasks-template.md — task categories already allow
     risk-proportional test tasks. No edit required.
  ✅ .specify/extensions.yml — Git auto-commit hooks remain registered but are
     operator-triggered only; see Principle IV.
  ⚠ CLAUDE.md / AGENTS.md — currently contain only the Spec Kit stub. Consider adding a
     pointer to this constitution so agents load it without being asked.

Deferred TODOs: none
-->

# InjazEdu Local AI Constitution

InjazEdu Local AI is a locally hosted service that turns Arabic exam textbooks into
reviewed-before-publish MCQ drafts and integrates with the existing production
Laravel + MySQL InjazEdu application across a network boundary. It is built by a
solo operator with a code agent, using Spec Kit.

This constitution is short on purpose. Every rule below is a rule an agent or a
reviewer can check mechanically.

## Core Principles

### I. Risk-Proportional Testing

Automated tests are required only for behavior that is important, high-risk, or
business-critical. Tests are NOT required for trivial CRUD, framework behavior,
simple wiring, or low-risk implementation details.

Write focused tests that protect:

- Contracts and public interfaces (HTTP APIs, job payloads, model gateway boundaries)
- Textbook parsing and structure recovery
- AI pipeline behavior (prompting, schema validation, generation output shape)
- Validation and business rules
- Publishing and approval flows
- Security and authorization
- Idempotency and retry safety
- Data integrity and migrations that transform data

**Rationale:** Exam content is human-approved before publish, so the value of a test
lies in protecting the pipeline that produces and gates that content — not in
re-testing Laravel.

### II. Test Database Isolation (NON-NEGOTIABLE)

Any automated test that touches a database MUST use a dedicated test database that:

- is separate from development, production, imported, mirrored, and any real dataset;
- contains `_test` in its database name;
- is configured through the testing environment (e.g. `.env.testing`, `phpunit.xml`);
- is disposable and reproducible from migrations plus test fixtures.

`RefreshDatabase`, `DatabaseMigrations`, and `migrate:fresh` MUST NOT run against any
non-test database. Destructive test operations MUST NEVER run against development or
imported datasets.

If a test cannot be made safe under these rules, do not run it — raise it with the
operator instead.

**Rationale:** Imported and mirrored InjazEdu data is irreplaceable locally. One
`migrate:fresh` against the wrong connection destroys it.

### III. The `injazedu/` Directory Is Read-Only (NON-NEGOTIABLE)

`/Users/abdullah/Projects/injazedu-local-ai/injazedu` is strictly read-only.

The code agent MUST NOT create, modify, delete, rename, move, format, or generate
files anywhere inside that directory — including generated files, caches, lockfiles,
and formatter or linter output.

The agent MAY read and inspect files there to understand the existing application,
schema, APIs, and integration constraints.

Any change that InjazEdu itself needs MUST be written up as work for the human
operator or the InjazEdu team and implemented outside this directory, unless the
operator explicitly lifts this rule.

**Rationale:** That directory mirrors a production application this project does not
own. It is a reference, not a workspace.

### IV. Git Is Operator-Owned (NON-NEGOTIABLE)

All repository-changing Git actions belong to the human operator.

The code agent MUST NOT: create, rename, switch, merge, or delete branches; commit;
push or pull; create or merge pull requests; or rebase, reset, stash, tag, or
otherwise modify history.

The agent MAY inspect Git state — `status`, `diff`, `log`, `show`, branch listings.

Spec Kit Git hooks (`.specify/extensions.yml`) are informational: the agent may
surface them, but only the operator executes them.

**Rationale:** Version history is the operator's undo button for everything the agent
does. The agent must not be able to move it.

### V. Stay Inside the Approved Scope

The agent implements the code, migrations, tests, configuration, and documentation
required by the active Spec Kit task — and nothing else.

- Work stays within the approved specification and the current milestone.
- Scope is never silently expanded; unrelated refactors are not introduced.
- When a decision would materially change architecture, data safety, security, or the
  approved specification, the agent STOPS and presents the decision to the operator
  rather than guessing.

Out-of-scope observations are recorded as notes or follow-up tasks, not implemented.

**Rationale:** A solo operator reviews everything by hand. Small diffs that match the
spec are reviewable; opportunistic ones are not.

## Additional Constraints

- **Human approval before publish.** AI-generated exam content is always a draft.
  Nothing reaches learners without an explicit human approval step.
- **MySQL is the business source of truth.** The AI service is a separate system; it
  must not become a second authority over business data.
- **Local-first.** The service runs self-hosted. Do not introduce a dependency on an
  external hosted AI provider without operator approval (Principle V).
- **Secrets stay out of the repo.** Credentials live in environment files, never in
  committed code, specs, or docs.

## Development Workflow

Every plan's **Constitution Check** gate MUST answer these five questions:

1. Which behaviors here are high-risk enough to need tests, and which are explicitly
   exempt under Principle I?
2. Do any tests touch a database — and is the `_test` database wired through the
   testing environment (Principle II)?
3. Does anything in this work require writing inside `injazedu/`? If yes, it is
   operator work and must be listed as such (Principle III).
4. Are there Git actions in the task list? If yes, they are operator steps, not agent
   steps (Principle IV).
5. Is every task traceable to the approved spec and current milestone (Principle V)?

A plan that cannot answer all five does not proceed to implementation. Violations that
are genuinely necessary go in the plan's Complexity Tracking table with a justification
and the rejected simpler alternative.

## Governance

This constitution supersedes other working practices in this repository. Where a Spec
Kit template, skill, or hook conflicts with it, this document wins.

**Amendment.** The operator is the sole amending authority. Amendments are made by
editing this file, bumping the version, and recording the change in the Sync Impact
Report comment at the top.

**Versioning.** Semantic versioning:

- **MAJOR** — a principle is removed or redefined in a backward-incompatible way.
- **MINOR** — a principle or section is added, or guidance is materially expanded.
- **PATCH** — clarifications, wording, and non-semantic fixes.

**Compliance.** The Constitution Check gate in every plan is the review point. The
agent must self-check against these principles before reporting a task complete, and
must say so plainly when it has not.

**Version**: 1.0.0 | **Ratified**: 2026-09-02 | **Last Amended**: 2026-09-02
