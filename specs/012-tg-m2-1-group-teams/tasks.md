# Tasks: TG-M2.1 — Group Teams and First-Action Assignment

Every test runs on `injaz_ai_test`: there is no model runtime, no credential and no network. Git steps belong
to the operator.

## Phase 1: Schema (FR-401, FR-414, FR-420)
- [x] **T401** Write revision `0011_group_teams`.
  - Swap the index: drop `uq_assignment_one_current_primary`, add `uq_assignment_one_current_membership`.
  - Add `attention_items.closed_by_moderator_id`.
  - Add the views `moderation_team_intervals`, `attention_item_assignee` and `moderation_incident_assignee`.
  - The downgrade restores the index and refuses while a group has two current members.
  - Test: `tests/moderation/actors/test_migration_0011.py`.
- [x] **T402** Bring ORM parity to `models_moderation.py` for the index and the column.

## Phase 2: Teams (US2; FR-401–FR-406)
- [x] **T403** In `assignments.py`:
  - add `team_at`, which reads the view;
  - `open_assignment('primary')` adds a member, with the T4 refusals;
  - `handover(…, replacing=)` replaces a member (T5);
  - add `end_assignment` and `deactivate_moderator` (T6);
  - the migration refusal says "current team" (T7).
  - Tests: `test_team_at.py` (it replaces `test_responsible_at.py`), `test_group_teams.py`, and updated
    `test_handover.py`, `test_db_invariants.py` and `test_migration_repoint.py`.

## Phase 3: Assignment (US1; FR-410–FR-415)
- [x] **T404** `open_item` and `insert_incident` stop resolving an owner (G1). Update the attribution tests in
  `attention/`, `incidents/` and `classification/`.
- [x] **T405** Test the assignee views in `tests/moderation/incidents/test_team_assignment.py`:
  - reply, dismissal, and reaction on the anchor and on a burst member;
  - a non-team actor; an unlinked operator; an act after the end; a reversal;
  - the tie-break; the migration hop; a member added after the act.

## Phase 4: Figures (US4; FR-440–FR-442)
- [x] **T406** F1 in `metrics.py`, the four statements.
  - Test: a one-member team gives the old figure; a miss counts once per member and once per group.
- [x] **T407** F3 `attention_work_stats` and F4 `incident_work_stats`, checked against a hand-computed fixture
  (`tests/moderation/incidents/test_team_assignment.py`).

## Phase 5: Panel (US1–US4; FR-420–FR-434)
- [x] **T408** The `ModeratorGroupAssignment` model:
  - `teamAt`, `scopeCurrentMembers`, `addMember` (T4), `end`, `replaceWith` (T5);
  - remove `scopeResponsibleAt` and `handover`;
  - `Moderator` deactivation ends memberships (T6).
- [x] **T409** C1 snapshots:
  - the queue's dismissal sets `closed_by_moderator_id`;
  - `insertGuardedAction` sets `actor_moderator_id`;
  - `openOn` and `openByHand` stop writing `responsible_moderator_id`.
- [x] **T410** Team management:
  - Moderators › Assignments gets Add to group (with Since), End, and Replace with…;
  - a new Groups › Team relation manager;
  - the Groups list's Team column.
- [x] **T411** Assigned column and Mine filter (default on for linked users), on both the queue and Incidents.
  On Incidents, an "Assigned to" filter. On the incident page, Team at flagging and Assigned.
- [x] **T412** Figures:
  - By moderator becomes My groups (F1) plus My work (F3/F4), on both pages;
  - the PHP SQL is identical to Python.
- [x] **T413** `lang/ar.json` entries for every new string. Feature tests, updated and new (`TeamMembershipTest`,
  `TeamAssignmentPanelTest`).

## Phase 6: Close
- [x] **T414** Add dated "Amended by TG-M2.1" notes to the 005/006/007 contracts and master plan §12, and
  update `CLAUDE.md`'s active feature.
- [x] **T415** Run `make check` (2026-10-19): ruff, architecture, mypy, pytest 1408 passed / 9 skipped, PHP 219
  tests, secret scan — ALL CHECKS PASSED.
- [ ] **T416** *(operator)* Development smoke (quickstart §2).
- [ ] **T417** *(operator)* Deploy, migrate, add the production group's second moderator, and link panel
  accounts (quickstart §3).
