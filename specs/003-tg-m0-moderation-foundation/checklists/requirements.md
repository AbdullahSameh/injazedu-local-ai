# Specification Quality Checklist: TG-M0 — Moderation Intelligence Domain Foundation

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-09
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

## Validation Notes

**Iteration 1 — all items pass.** Findings worth recording, because two of them were judgement
calls rather than clean passes:

1. **"No implementation details" — passes, but this milestone is structural by nature.** TG-M0's
   deliverable *is* a code-organisation constraint, so the spec necessarily talks about a domain
   boundary and about one part of the system importing another. It stays technology-agnostic where
   it counts: no language, framework, library, file path, tool or command name appears anywhere in
   the requirements or success criteria. "Quality gate", "provider area" and "model gateway" are the
   house vocabulary already established by `specs/002-m1-model-gateway/spec.md` and are used
   consistently with it.

2. **"Written for non-technical stakeholders" — passes with the same caveat as M1.** The reader of
   this milestone is the operator and the developer, not a business stakeholder; the milestone
   produces no visible behaviour. Every user story is still written as an outcome someone
   experiences (the build refuses a bad change; the same question matches however it was typed;
   nothing identifying reaches a model; the stack runs with no credential; an update can be traced),
   not as a task list.

3. **Zero clarification markers.** Every value this milestone needs — the 90-second burst window, the
   24-hour maximum item age, the 90-day retention period, the six correlation identifiers, the four
   redaction patterns, the three permitted shared dependencies — is fixed by
   `docs/plan/telegram/telegram-moderation-intelligence.md` and cited in Assumptions. The source
   plan's own §28 confirms no open question blocks TG-M0.

4. **One genuine external dependency is flagged rather than assumed away**: a fixture set of real
   Arabic group messages with known-correct normalised forms. Without it, SC-007 through SC-010 can
   be executed but not meaningfully validated against the dialect-recall risk they exist to reduce.
   Listed under Dependencies.

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
