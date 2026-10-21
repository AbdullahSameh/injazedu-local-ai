# Implementation Plan: TG-M2.1 — Group Teams and First-Action Assignment

**Branch**: `m2.1/group-teams-first-action`, created by the operator (constitution IV).
**Date**: 2026-10-19
**Spec**: `spec.md`
**Contract**: `contracts/group-teams.md`
**Plan of record**: `docs/plan/telegram/tg-group-teams-first-action-plan.md` (approved 2026-10-19)

## Summary

A group gets a **team** of one or more moderators: several current `primary` memberships, defined once in
the view `moderation_team_intervals`.

Nothing is assigned at creation. An item's or incident's **assigned moderator** is derived by two views as
the first team member who acted on it while it was live:
- a reply, a dismissal or a reaction, for an attention item;
- any non-reversal evidence, for an incident.

**What else changes:**
- **Panel acts:** they now record the linked moderator.
- **Figures:** every per-moderator figure swaps its `responsible_moderator_id = M` predicate for "M was on the
  team then". A "My work" block is added.
- **Screens:** the panel gains Assigned, Mine, and team management.
- **`responsible_moderator_id`:** no longer written.

## Technical Context

- **Language/Version:** Python 3.12 (`apps/ai-api`) and PHP ^8.2 / Laravel 12 / Filament 5 (`apps/ai-control`),
  both existing.
- **Primary Dependencies:** the existing ones (SQLAlchemy async, Alembic, Filament). Nothing new is added.
- **Storage:** PostgreSQL, through one revision, `0011_group_teams` (data-model §1–§5).
- **Testing:**
  - pytest on `injaz_ai_test`;
  - PHPUnit feature tests with `DatabaseTransactions` on `injaz_ai_test`;
  - `make check`.
- **Target Platform:** Docker Compose in development; the Contabo production host.
- **Project Type:** a web service and workers, plus an admin panel.
- **Performance Goals:** the queue and incident list stay inside the 15 s poll at production volume (research
  §2).
- **Constraints:**
  - no message text in any log;
  - no state, route or eligibility computed in PHP (the panel reads views);
  - no average and no composite score;
  - bilingual strings.
- **Scale/Scope:** a handful of groups, one to three moderators each.

## Constitution Check

*It must pass before Phase 0, and again after the Phase 1 design. It passes both times.*

**1. Which behaviours need tests, and which are exempt (I)?**
- **Tested** (data integrity and business rules):
  - `team_at` at the four boundaries, with two concurrent members;
  - add, end and replace, including the T4 refusals, and T6 deactivation;
  - the 0011 constraints, with planted violations;
  - each G-rule of the assignee views (reply, dismissal, reaction on a burst member, non-team actor,
    unlinked operator, act after the end, reversal, tie-break, migration hop);
  - C1 snapshots;
  - F1 equal to the old figure for a one-member team;
  - the F2 double count;
  - F3/F4 against a hand-computed fixture;
  - the Mine default;
  - translation coverage.
- **Exempt:** the Filament layout and badge colours (framework).

**2. Do any tests touch a database (II)?** Yes, `injaz_ai_test` only, through the existing fixtures. PHP
uses `DatabaseTransactions`, never `RefreshDatabase` or `migrate:fresh`.

**3. Anything inside `injazedu/` (III)?** No.

**4. Any Git actions (IV)?** None by the agent. Spec Kit's commit hooks are surfaced only.

**5. Is every task traceable to the spec (V)?**

| Work | Traces to |
|---|---|
| Revision 0011, team view, `team_at`, add/end/replace, deactivation, migration | FR-401–FR-406 |
| Assignee views, stop writing `responsible_moderator_id` | FR-410–FR-415 |
| Panel act snapshots | FR-420–FR-421 |
| Assigned column, Mine, incident page, team management, translations | FR-430–FR-434 |
| Re-scoped figures, My work, no averages | FR-440–FR-442 |
| Contract amendment notes | spec Provenance |

## Project Structure

**Python** (`apps/ai-api/`)
- `alembic/versions/0011_group_teams.py`
- `app/infrastructure/models_moderation.py`: parity for the new index and column.
- `app/application/moderation/assignments.py`: `team_at`, the reworked `open_assignment` and `handover`,
  `end_assignment`, `deactivate_moderator`, `RepointConflictError`.
- `app/application/moderation/attention.py`, `incidents.py`: G1.
- `app/application/moderation/metrics.py`: F1, plus `attention_work_stats` and `incident_work_stats`.
- `tests/moderation/actors/`, `attention/`, `incidents/`: the existing tests are updated; `test_team_at.py`,
  `test_group_teams.py` and `test_assignee_views.py` are new.

**Panel** (`apps/ai-control/`)
- Models:
  - `ModeratorGroupAssignment`: `teamAt`, `scopeCurrentMembers`, `addMember`, `end`, `replaceWith`;
  - `Moderator`: deactivation ends memberships;
  - `AttentionItem` and `ModerationIncident`: C1, plus the assignee readers;
  - `TeamDisplay` support.
- `Filament/Resources/Moderators/RelationManagers/AssignmentsRelationManager.php`
- `Filament/Resources/TelegramChats/RelationManagers/TeamRelationManager.php` (new)
- `Filament/Resources/TelegramChats/Tables/TelegramChatsTable.php`
- `Filament/Pages/LiveAttentionQueue.php` and `Pages/Concerns/AttentionMetrics.php`
- `Filament/Resources/Incidents/{Tables/IncidentsTable,Concerns/IncidentMetrics,Pages/ListIncidents,Schemas/IncidentInfolist}.php`
- Two blades, `lang/ar.json`, and feature tests.

**Docs**
- Dated amendment notes in `specs/005…/contracts/moderator-ownership.md`, `specs/006…/contracts/{attention-rules,attention-metrics,control-panel-attention}.md`,
  `specs/007…/contracts/{incident-lifecycle,incident-metrics,control-panel-incidents}.md`,
  `specs/005…/contracts/control-panel-moderation.md` and master plan §12.
- `CLAUDE.md`'s active feature.

## Implementation order

1. Revision 0011 and ORM parity.
2. Python teams: `team_at` and the writes. Update the existing actor tests.
3. G1 in `open_item`/`insert_incident`, plus the assignee-view tests.
4. Figures (F1, then F3/F4) in Python.
5. Panel models, team management, columns and filters, figures, translations.
6. Contract notes, then `make check`.

## Complexity Tracking

None. The index swap is the one non-additive DDL, and its downgrade refuses rather than guesses (data-model
§1).
