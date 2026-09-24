# Specification Quality Checklist: TG-M3 — Deterministic Response Tracking

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-21
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

## Notes

**Iteration 2 (2026-09-22)** — all items pass. Ready for `/speckit-plan`.

The three open questions were resolved in `## Clarifications → Session 2026-09-22` and folded into the
requirements. Each was a genuine conflict or silence in the source plan, not a detail with a safe default:

1. **A moderator answers inside the settle window.** §7.2 schedules recognition for `sent_at + burst_gap`
   and §13.2 defines closure against *open* items, but neither says what happens when the answer precedes
   the item. Resolved: the item opens and opening evaluates already-stored messages through the **same**
   matcher, so the fastest responses keep their true times and stay in the distribution — FR-026, FR-027,
   SC-023.
2. **An edit that adds a question.** §13.4 requires a new item for a burst that "previously did not
   qualify", but TG-M2's own clarification left no stored pre-edit text to establish it. Resolved: the
   rules judge the current text and an item opens only when the burst has none, anchored on the edited
   message and dated from the edit — FR-022 … FR-024, SC-024. Recovering pre-edit text from the captured
   event was rejected because that payload expires, which would make the same edit produce different items
   over time.
3. **Messages stored before the rules existed.** Resolved: no automatic backfill; the operator's existing
   re-derivation command gains an idempotent, reporting opt-in — FR-082, FR-083, SC-025. This mirrors
   TG-M2's decision on re-derivation and strictly contains the do-nothing option.

**Iteration 1 (2026-09-21)** — one item failing: the three `[NEEDS CLARIFICATION]` markers above. Every
other item passed on the first pass and none needed a spec change.
