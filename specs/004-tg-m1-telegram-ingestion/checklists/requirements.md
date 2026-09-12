# Specification Quality Checklist: TG-M1 — Telegram Event Ingestion

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

**Iteration 1 — all items pass.** Five findings worth recording, because several were judgement
calls rather than clean passes:

1. **"No implementation details" — passes, and was actively enforced.** The Requirements, Out of
   Scope, Key Entities and Success Criteria sections were checked mechanically for the names of every
   library, service, product and command in this stack: none appears. Throughout those sections the
   Telegram Bot API is *"the platform"*, the poller is *"the capture process"*, Postgres is *"the
   store"*, the Redis lease is *"a local mutual-exclusion mechanism"*, Alembic is *"a migration"*, the
   webhook is *"the platform's inbound delivery mechanism"*, and the mock transport is *"a scripted
   stand-in"*. Telegram is named only in the title, the Overview's framing and the Dependencies list,
   where it identifies the source documents — the same convention `specs/003-…` uses.

2. **"Written for non-technical stakeholders" — passes with the same caveat as TG-M0.** This
   milestone produces no visible behaviour; its reader is the operator and the developer. Every user
   story is still framed as an outcome someone experiences — every event is captured once; a restart
   resumes rather than restarts; a window nobody observed is marked as unobserved; groups appear by
   themselves and losing coverage is visible; the operator can tell capture is healthy; the bot stays
   silent and the machine stays closed — rather than as a task list.

3. **Zero clarification markers, but one value was chosen rather than inherited.** Every other number
   comes from `docs/plan/telegram/telegram-moderation-intelligence.md`: the subscription set (§9), the
   four unobserved-window reasons (§10.2), the health section's fields (§21), the 24-hour retention
   fact (§5.2). The **5-minute minimum silence before an unobserved window is recorded** has no source
   value — the plan requires the window without naming a threshold. It is set as a configurable
   default rather than raised as a clarification, because leaving it unset would make the record
   either noisy or useless and any reasonable value is changeable without code. Recorded explicitly in
   Assumptions so `/speckit-plan` can revisit it as a research item rather than inherit it silently.
   → **Resolved in the 2026-09-09 clarification session**: the operator confirmed 5 minutes, and the
   value is now stated in FR-025 rather than carried only as an assumption.

4. **Two requirements are stated as prohibitions and are the sharpest tests here.** FR-016 (consumption
   is confirmed only after durable storage, and the position never runs ahead of what is stored) and
   FR-038 (no send, reaction, deletion, removal or restriction exists in the change set) are the two
   whose violation is invisible in normal operation and catastrophic in a real group. Both are given
   explicit measurable outcomes — SC-004 and SC-015 — rather than left as prose.

5. **The genuine external dependency is flagged rather than assumed away**: the runbook's §B operator
   steps — two bots created with privacy disabled *before* the first group add, a development group
   with two additional accounts, the bot promoted to administrator, and the development credential in
   the local environment. Without them the milestone is fully developable and fully testable against
   the scripted stand-in, but **not** smoke-testable. Listed under Dependencies and called out in
   Assumptions.

## Clarification Session 2026-09-09 — re-validation

Four questions asked and answered; all 16 checklist items still pass after integration. What changed:

- **Two-consumer conflict is now a stand-down, not an indefinite retry** (FR-004a/004b, US3 scenarios
  3a/3b, SC-022). This closed the one genuinely dangerous gap the original spec carried: FR-004 as
  first written would have had two consumers alternate forever, losing events on *both* sides while
  each reported itself healthy — the precise failure the operator runbook's opening fact warns about.
- **The 5-minute window threshold is confirmed and promoted into a requirement** (FR-025), rather than
  living only in Assumptions as an invented default. See note 3 above.
- **Identity-resolution failure is now specified** (FR-007a–007d, US5 scenario 2a, SC-023). The spec
  previously assumed identity "is resolved at startup" without saying what happens when it is not —
  a total failure mode, since identity is half the idempotency key. It is also now explicitly
  distinguishable from the supported "no credential configured" state that the offline quality gate
  depends on.
- **A scale assumption exists** (FR-005a/005b, SC-024). The *Data volume* taxonomy category was the
  last Missing one; the batch ceiling it produces interacts directly with FR-016, and FR-005b records
  the non-obvious constraint that a slow drain can push a recoverable backlog past the platform's
  retention window and make it permanent loss.

Requirement count after integration: **53 functional requirements, 24 measurable outcomes.**

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
