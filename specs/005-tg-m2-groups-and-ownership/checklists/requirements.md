# Specification Quality Checklist: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-12
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

**Iteration 1 — all sixteen items pass.** Six findings worth recording, because several were
judgement calls rather than clean passes.

1. **"No implementation details" — passes, and was verified mechanically.** The Requirements, Out of
   Scope, Key Entities and Success Criteria sections were scanned for the name of every library,
   service, product and tool in this stack. One leak was found on the first pass — the word *Filament*
   in an Assumption — and was replaced with *control-panel*. After that, the Bot API is *"the
   platform"*, Postgres is *"the store"*, the Dramatiq worker is *"the background worker"*, Alembic is
   *"a migration"*, Filament is *"the control panel"*, the mock transport is *"a scripted stand-in"*,
   and InjazEdu is *"the organisation's main application"*. The word *Telegram* appears only in the
   header's milestone reference, the verbatim `Input` line, and the Dependencies paths — the same
   convention `specs/003-…` and `specs/004-…` use.

2. **Three clarifications were asked rather than guessed, and all three were genuine contradictions or
   gaps in the source plan — not preferences.** This is the material difference from TG-M1, whose
   session produced four questions about values the plan simply did not name:
   - **Retroactive derivation** — TG-M1's spec *promised* that measuring a group later works
     retroactively within the retention window, and TG-M1 stores events for unmeasured groups solely to
     make that possible. But TG-M1's handling step marks every captured event handled, so ordinary
     draining will never revisit them. The promise had no mechanism. Resolved as one explicit operator
     command (FR-020–FR-023).
   - **Edited messages** — the plan's §9 says the new text is "stored as a new version of the text,
     never overwriting the original", while §10.6 gives the message record a single verbatim/normalised
     pair and an edit timestamp, and no version table exists in the plan's own fifteen-table list. A
     literal reading required a table the plan never budgeted. Resolved by recognising that the
     append-only captured event already *is* the archive (FR-010), with the retention consequence
     recorded in Assumptions rather than left to be discovered.
   - **Moderator mapping before observation** — the moderator record links to a sender identity that
     only exists once that person has posted, yet the runbook's TG-M2 row has the operator collect
     numeric identifiers first. Following the schema literally would have made the milestone's own
     smoke test order-dependent, and would have left a moderator's first message flagged as a
     student's permanently. Resolved with placeholder identities (FR-027, FR-028).

3. **The two hardest requirements to get right are stated as exact boundaries, not as prose.**
   FR-044 (an ownership interval includes its effective instant and excludes its expiry) and FR-036
   (at most one *current* primary owner, enforced by the store) are the ones whose violation produces a
   plausible-looking wrong answer at precisely the moment someone disputes a number. Each has a
   boundary-position measurable outcome — SC-014 tests four positions rather than "around" the
   boundary, and SC-012/SC-013 test the refusal and the atomicity separately.

4. **One deliberate imperfection is documented rather than specified away.** The moderator flag is a
   snapshot, so a transcript spanning a promotion shows the same person flagged both ways. That looks
   like a bug and is the correct record; the alternative — a live lookup — silently flatters every
   historical number in the promotion's direction. Recorded in Assumptions and in the Edge Cases, and
   given a measurable outcome (SC-011) across all three mutation events: mapping, unmapping and
   deactivation.

5. **A trade-off the source plan already made is restated so a later milestone does not "fix" it.**
   Only the *current* primary owner is enforced unique; historical overlap is covered by a test. The
   plan explicitly rejected the stricter range-exclusion constraint because it needs an extension
   enabled at database-creation time on an already-shipped database. Carried into Assumptions with the
   reasoning, because an unexplained partial constraint reads like an oversight.

6. **The genuine external dependency is flagged rather than assumed away**: the runbook's §C TG-M2 row
   — the operator's own numeric identifier and those of the two test accounts — on top of §B still
   holding from TG-M1. Without them the milestone is fully developable and fully testable against
   scripted stand-ins, but **not** smoke-testable. Listed under Dependencies and in Assumptions.

**Requirement count: 70 functional requirements, 35 measurable outcomes, 6 prioritised user stories.**

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
- Because the three questions above were asked and answered during specification, `/speckit-clarify`
  has no outstanding ambiguity to resolve. The next step is `/speckit-plan`.
