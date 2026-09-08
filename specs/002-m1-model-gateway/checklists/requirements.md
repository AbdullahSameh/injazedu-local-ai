# Specification Quality Checklist: M1 — Model Gateway

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution Alignment (project-specific)

- [x] **I. Risk-proportional testing** — M1's test surface is exactly the constitution's named
      high-risk categories: a public contract (the gateway interfaces, FR-001–FR-008), retry
      safety and idempotent seeding (FR-010, FR-031–FR-034), and security boundaries
      (FR-015, FR-038, FR-044). No requirement demands tests of trivial wiring, and the
      Control Center CRUD in FR-042–FR-046 is explicitly framework behaviour whose only
      test-worthy part is the save-time invariant in FR-043.
- [x] **II. Test database isolation** — M1 adds two tables and a Control Center write path,
      so it inherits M0's `_test` guard rather than restating it. FR-026 keeps the default
      suite offline; nothing in M1 relaxes M0's FR-027–FR-030.
- [x] **III. `injazedu/` is read-only** — FR-050 and SC-017 state it as a verifiable outcome.
      M1 has no InjazEdu integration at all (deferred to M6 in "Out of Scope").
- [x] **IV. Git is operator-owned** — the mandatory `before_specify` branch-creation hook was
      **NOT** executed. The branch `m1/model-gateway` already existed, operator-created;
      this is recorded in the spec header and under Dependencies.
- [x] **V. Stay inside approved scope** — every requirement traces to the M1 row of the
      approved plan's milestone table or to §16.1–§16.5, §5.1–§5.2, §10.3 and §18.6 of the
      same plan. Three scope decisions that the milestone row did not settle were put to the
      operator rather than guessed (see Validation Notes). "Out of Scope" names the milestone
      that owns each deferred capability.

## Validation Notes

**Operator decisions taken during specification** (Principle V — presented rather than guessed):

1. *Call accounting in M1?* The M1 milestone row does not mention it, but §5.2 assigns token
   accounting to the gateway and §8/§17/§18.6 define the record and its redaction policy.
   **Operator chose: include in M1.** → FR-037–FR-041, SC-012.
2. *Which generator is active at the end of M1?* §16.1 recommends a ~5.2 GB model that is not
   installed; §3.1 records what is. **Operator chose: seed the full roster, keep the installed
   model active.** M1 therefore requires no download and no memory-budget change. → FR-010,
   Assumptions.
3. *How much Control Center surface?* §5.2 lists model management as an ai-control
   responsibility; the M1 row mentions no UI. **Operator chose: full profile CRUD.** →
   FR-042–FR-046, SC-014. Note this makes the model swap of SC-002 an operator action rather
   than a database edit, which strengthens the milestone's headline criterion.

**Iteration 1 findings and fixes applied:**

1. *Ambiguity with a material design consequence* — the plan pairs a "concurrency 1" lane with
   2 worker processes, which only achieves its stated purpose if the lane is shared across
   processes; a per-process reading would admit one call per process and defeat it. FR-029 now
   states the limit is machine-wide, US5 gained a cross-process acceptance scenario, SC-006
   measures across processes, and the reasoning is recorded in Assumptions. **Fixed.**
2. *Acceptance scenario with no backing requirement* — US2's degenerate-input scenario (empty /
   whitespace-only text) had no functional requirement. Added FR-022. **Fixed.**
3. *Untestable failure handling* — several scenarios required a failure to "name" its cause, and
   FR-032 requires distinguishing a caller's mistake from a transient fault, but nothing made the
   failure categories part of the contract. Added FR-008 (closed set of distinguishable failure
   categories) and SC-016. **Fixed.**
4. *Implementation-detail leak* — SC-001 named a language-level construct. Reworded to describe
   the boundary by its outcome. **Fixed.**
5. *Lane leak on process death* — FR-034 and US5 scenario 8 originally covered only in-process
   failure paths; a machine-wide lane can also be orphaned by a dying process. Both extended.
   **Fixed.**

**Open items carried into planning (not blockers):**

- SC-007 (gateway overhead ≤ 10% of a direct call) needs the plan's measured baseline of
  10.2 chunks/s at batch 32 (§3.2) re-measured on the operator's machine at planning time; the
  criterion is the ratio, not the absolute figure.
- The plan's §16.2 runtime settings are an operator prerequisite documented in M0. SC-006's
  memory headroom assumes they are applied; planning should re-verify rather than assume.
- Token counting is routed "via the gateway" by §10.2 but consumed only by chunking. Deferred to
  M4 by "Out of Scope"; the M4 plan will extend the gateway interface rather than add a second
  path. Flagged so the M1 interface design leaves room for it.
- The plan's four open questions (§23) concern M2, M6 and M9. None affects M1.

**Status: all checklist items pass. Ready for `/speckit-plan`.**
