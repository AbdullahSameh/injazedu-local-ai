# Specification Quality Checklist: TG-M6 — Alerts

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-12
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs). See note 1.
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain. The three were answered 2026-11-12 (Q1 A, Q2 C, Q3 A).
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
- [x] No implementation details leak into specification. See note 1.

## Notes

1. **Named project artefacts are provenance, not design.** These names appear in the spec:
   - `make tg-doctor`, `MODERATION_TICK_INTERVAL_S`, `MODERATION_TEXT_RETENTION_DAYS` and `lang/ar.json`;
   - `callback_query`, `confirmation` and revision `0013`.

   Each names something that already exists, or a slot a prior contract reserved. This follows the track's
   house style (master plan §30; `specs/012-…/spec.md` does the same). No table, column, module or code
   shape is designed here; that is `/speckit-plan`'s.
2. Validation pass 1 (2026-11-12): every item passes except the three open questions. They are deferred to
   the operator because each is a decision the master plan left to TG-M6: §28 items 6 and 7, and the
   2026-10-21 note on student text.
3. Validation pass 2 (2026-11-12), after the operator's answers:
   - **Q1 A:** quiet hours per rule, suppressed and never sent → FR-543, SC-509.
   - **Q2 C:** a short redacted excerpt on question and incident alerts → FR-531. Two requirements were added
     to keep D-TG-11's 90-day promise: FR-535 removes the excerpt at the retention age, and FR-536 stores no
     excerpt. SC-510 covers both.
   - **Q3 A:** Arabic only → FR-533.

   Every item passes.
