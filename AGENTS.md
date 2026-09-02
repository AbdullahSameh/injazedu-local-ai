<!-- SPECKIT START -->
Active feature: **M0 — Local AI Service Foundation** (`specs/001-m0-foundation/`)

Read before working on this feature:

- `specs/001-m0-foundation/plan.md` — implementation plan, Constitution Check, project structure
- `specs/001-m0-foundation/spec.md` — requirements (FR-001…FR-034) and success criteria
- `specs/001-m0-foundation/research.md` — 22 decisions with rationale and rejected alternatives
- `specs/001-m0-foundation/data-model.md` — the one table, the DB roles, the Redis keyspace
- `specs/001-m0-foundation/contracts/` — HTTP surface, DB privileges, env vars, make targets
- `specs/001-m0-foundation/quickstart.md` — operator prerequisites and the acceptance walkthrough

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
