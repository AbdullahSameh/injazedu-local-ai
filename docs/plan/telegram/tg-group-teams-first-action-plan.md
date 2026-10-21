# Group Teams and First-Action Assignment — plan

> **Status (2026-10-19): implemented** in `specs/012-tg-m2-1-group-teams/` (T401–T415, `make check` green).
> The development smoke and the production follow-through are the operator's (quickstart §2–§3).
> Working label **TG-M2.1** (it amends TG-M2's ownership contract). The label is my call; rename freely.

## Context

In production one group has one bot and **two moderators who both watch it all day**. The schema allows
exactly one current `primary` per group (`uq_assignment_one_current_primary`, 0004), and every attention
item and incident snapshots that single primary at open (`responsible_at`, `assignments.py:28`). So:

- the second moderator's work is credited nowhere;
- "By moderator" figures (`LiveAttentionQueue.php:505`, `ListIncidents.php:97`) charge everything to one person;
- as the bot joins many groups, busy groups will need two or three moderators, and the model can't express it.

The operator wants:
1. a group to have **several moderators**;
2. each attention item and incident to be **assigned to one of them**;
3. **each moderator's actions and work tracked** for reports.

The panel serves moderators (catch what needs answering or acting on in Telegram) and the operator (watch
every group and every moderator).

## Decisions taken with the operator (2026-10-19)

| # | Decision |
|---|---|
| D1 | A group has a **team** of one or more moderators, all equal. A one-member team behaves like today's single primary. |
| D2 | **Nobody is assigned when something opens.** The **first team member to act on it becomes its assigned moderator, for good.** This holds for attention items and incidents alike. There is no "Take it" button; acting is taking. |
| D3 | Both moderators use Telegram **and** the panel. The operator uses the panel to watch everything. |
| D4 | **Misses count against every team member.** If a question goes unanswered or an incident goes unhandled, each moderator on the team at the time counts it as missed. "Unanswered" and "unhandled" keep today's definitions. The group's own total counts it once. Covering by a moderator outside the team is not a miss, as today (`moderator-ownership.md:139`, A4). |

## The rules

### R1 — Team membership (amends `moderator-ownership.md`)
- A membership is an existing `moderator_group_assignments` row with `assignment_role = 'primary'`. It
  keeps its half-open `[valid_from, valid_to)` interval, and **several can be current at once**.
- `backup` stays in the vocabulary: recorded, not on the team, never assigned. The DB values are kept
  to avoid churn; the UI says "Team member".
- `team_at(chat, t)` is the set of moderators whose membership covers `t`. It replaces `responsible_at`
  everywhere. O2, O3 and O5 still hold, now for a set. O1 ("at most one") is withdrawn.
- §2's protocol (close before open, one timestamp, one transaction) still governs **replacing** a member,
  but closes **only the named membership**.
  - Today's `handover` closes every current primary in the chat (`ModeratorGroupAssignment.php:115`,
    `assignments.py:70`), which in a team would end the whole team.
  - **Adding** is a plain open; **removing** is a plain close.
- Opening a membership is refused:
  - for an inactive moderator (`is_active = false`);
  - when it would overlap that moderator's own interval in that group;
  - when it is backdated before the moderator was declared (`moderators.created_at`). Before that
    instant their messages were never flagged as a moderator's (`messages.py:290`), and their reactions
    were never recorded (`evidence.py:104`). A membership covering that time would charge misses for
    questions they actually answered.
- **Deactivating a moderator ends their current memberships** in the same transaction, with the same
  timestamp. Otherwise someone who left keeps collecting misses.
- §6, chat migration: re-point all members unchanged. The refusal when the surviving row already has a
  current team stays.

### R2 — What counts as an act, and who it is credited to
Every act is already recorded immutably, so **the assigned moderator is derived, never written**. It is
read from two new views (R3); nothing stores it and nothing updates it.

| Object | Acts (any of these, the earliest wins) | Already recorded as |
|---|---|---|
| Attention item | A moderator's reply that answers it | `attention_items.first_response_moderator_id`, `first_response_at` |
| | A panel dismissal (any of the four reasons) | `closed_at` plus **new** `closed_by_moderator_id` (R4) |
| | A moderator's reaction on the item's anchor message, posted after the anchor (signals "I'm on it"; it assigns, **does not close**) | `moderation_actions` with `action_type='reaction'` and `target_message_id = anchor` (`evidence.py:58`) |
| Incident | Rows of `moderation_incident_evidence`: a reaction, a direct reply, a ban/expulsion/restriction, or a panel Acknowledge, Resolve or Not a violation. A `reversal` (an undo) does not assign | its `actor_moderator_id`. Panel acts will now carry it too (R4) |

An act assigns only if both conditions hold:
- **its actor was on the group's team at the act's instant**: `team_at(chat, act.occurred_at)`; after a
  chat migration, the team of the item's chat or its successor;
- **it landed while the item or incident was still live**, at or before its end. For an item that is
  `closed_at`, the closing act itself counts. For an incident it is the resolving or false-positive
  evidence. A reaction after expiry, or after an outsider's answer, assigns nothing, so it cannot
  erase a miss.

**Acts that assign nobody:**
- a moderator from another group: the act still closes or resolves as it does today, and is credited
  as "covered from outside";
- an operator whose panel account is not linked to a moderator.

**Tie-break:** reuse D-TG-106's `(occurred_at, source_rank, evidence_id)`. For attention, order by
instant, then reply < dismissal < reaction, then id.

### R3 — Two views, revision `0011`
- **`attention_item_assignee`**: `(attention_item_id, assigned_moderator_id, assigned_at, assigned_via)`,
  where `assigned_via` is `reply`, `dismissal` or `reaction`. Each value comes from the earliest
  qualifying act; all are NULL when there is none.
- **`moderation_incident_assignee`**: the same shape. `assigned_via` is the evidence `kind`, read from
  `moderation_incident_evidence`.
- Both are separate views; **0006's two views are not touched**.
- The panel reads both and computes nothing (panel rule: no state in PHP).

### R4 — Panel acts credit the linked moderator (amends TG-M4 H7)
- When the acting panel user has a linked moderator (`moderators.user_id`, 0009), the act snapshots
  that moderator's id at write time:
  - attention dismissals set the new column `attention_items.closed_by_moderator_id` inside the
    existing `closeIfOpen`;
  - incident acts set `moderation_actions.actor_moderator_id` inside `insertGuardedAction`
    (`ModerationIncident.php:229`).
- No constraint change is needed; `ck_actions_provenance` is satisfied.
- `panel_user_id` and `closed_by_user_id` are still written.
- **What this changes on screen:**
  - An unlinked operator's acts stay the operator's.
  - A linked moderator's panel act now displays as that moderator; `IncidentDisplay::actorLabel`
    already prefers the moderator (`IncidentDisplay.php:182`). That is intended.
  - 0006's state view starts filling `acknowledged_by_moderator_id` and `resolved_by_moderator_id` for
    panel acts. Its definition is unchanged; its output is not.
  - The comment at `ModerationIncident.php:179` is rewritten.

### R5 — `responsible_moderator_id` is frozen
- New rows get NULL. `open_item` (`attention.py:392`), `insert_incident` (`incidents.py:85`), the
  panel's hand-open (`LiveAttentionQueue.php:399`) and `openOn` (`ModerationIncident.php:89`) stop
  calling `responsible_at`.
- Legacy rows keep their value as history; the column is never dropped or rewritten.
- Every per-moderator figure moves to the assignee views plus team history. Legacy rows are covered
  too, because the views derive from acts.

### R6 — Per-moderator figures: two scopes (amend `attention-metrics.md`, `incident-metrics.md`)
For moderator *M* in period *P* (items by `opened_at`, incidents by `detected_at`), each moderator row
has two parts.

**(a) "My groups": today's figures, unchanged, re-scoped.**
- The figures are today's exact SQL:
  - attention: asked, answered, median, p90 and max first-response time, unanswered past
    `MODERATION_ITEM_MAX_AGE_S`;
  - incidents: flagged, handled, missed, within window, false positive, acknowledged-not-handled.
- Only the selector changes: from `responsible_moderator_id = M` to
  "*M* ∈ `team_at(chat, opened_at | detected_at)`".
- **A one-member team gives exactly today's numbers**, because the sole member's scope is the old
  owner's scope.
- **D4 falls out:** an unanswered question or a missed incident appears in every member's row, and
  once in the group's.
- Covering from outside stays "answered" or "handled", as today, and is not a miss.

**(b) "My work": new, from the assignee views and the recorded acts.**
- **Assigned to me**, split:
  - by `assigned_via`;
  - by outcome: answered, dismissed, still open, **expired**.
- An item B took with 👍 and then let expire therefore shows in B's own row as *assigned → expired*,
  **and** stays a miss in (a) for the whole team.
- **Answered by me**: count, plus median, p90 and max of `first_response_at − opened_at` where
  `first_response_moderator_id = M`, with today's small-sample suppression.
- **Covered outside my groups**: *M* answered or acted where *M* was not on the team.
- **Incidents assigned to me**: by status, plus the time from `detected_at` to the assigning act.
  Detection latency stays group-level only (P15/M16).

Group rows keep today's totals. There is no average across moderators and no composite score (panel
rule).

### R7 — Screens (bilingual; every new string goes through `__()` and `lang/ar.json`)
**Moderators › Assignments**
- "Add to group": choose a group, and a "since" time that defaults to now. It may be backdated, but
  never before the moderator was declared and never into the future.
- Row action "End" sets `valid_to = now`.
- Row action "Replace with…" replaces the "Reassign" button (`AssignmentsRelationManager.php:54`) and
  closes only that one membership (R1).
- **Groups gets a "Team" relation manager** with the same actions.
- The Groups "Owner" column becomes **Team**, showing names, red when the group is monitored and
  nobody is on its team.

**Live Attention Queue**
- The "Responsible" column becomes **"Assigned"**:
  - the name plus "via reaction" when someone has taken it;
  - otherwise "Team: A, B";
  - otherwise "No team" (red).
- A **"Mine"** filter: my groups' unassigned items plus items assigned to me. It is **on by default
  for a user linked to a moderator** and off for the operator.
- The "By moderator" figures are replaced with R6.

**Incidents**
- The same "Assigned" column and "Mine" filter.
- The "Responsible" SelectFilter becomes "Assigned to".
- The incident page shows its team and its assigned moderator.

A "Mine" filter is a default, **not access control**. Every panel operator still sees everything.

## Files

**Python** (`apps/ai-api/`)
- `alembic/versions/0011_group_teams.py`:
  - drop `uq_assignment_one_current_primary`;
  - add `uq_assignment_one_current_membership` on `(telegram_chat_id, moderator_id) WHERE valid_to IS NULL`;
  - add `attention_items.closed_by_moderator_id` (nullable FK to `moderators`);
  - create the two views.
  - No `GRANT`.
- `app/infrastructure/models_moderation.py`: ORM parity.
- `app/application/moderation/assignments.py`: `team_at`, `add_member`, `end_member`, `handover`
  (replace), `repoint_for_migration`. `responsible_at` and its tests are removed.
- `app/application/moderation/attention.py` and `incidents.py`: R5.
- `app/application/moderation/metrics.py`: R6, one function per figure.

**Panel** (`apps/ai-control/`)
- `app/Models/ModeratorGroupAssignment.php`: `scopeTeamAt`, `addMember`, `endMember`, `handover`.
  `scopeResponsibleAt` is removed.
- `AttentionItem.php` and `ModerationIncident.php`: R4, plus assignee relations read from the views.
- `Moderators/RelationManagers/AssignmentsRelationManager.php`; a new Groups "Team" relation manager;
  `TelegramChatsTable.php`.
- `Pages/LiveAttentionQueue.php`, `Pages/Concerns/AttentionMetrics.php`, `Incidents/Tables/IncidentsTable.php`,
  `Incidents/Concerns/IncidentMetrics.php`, `Incidents/Pages/ListIncidents.php`, `Incidents/Schemas/IncidentInfolist.php`,
  and the two blades.
- `lang/ar.json`.

**Contracts to amend**
- `specs/005-…/contracts/moderator-ownership.md`:
  - §0;
  - §2's failure table (it names the dropped index, `:64`);
  - §3 O1/O4;
  - §4's attribution table and its "snapshot, never join" paragraph (`:142-144`).
- `specs/006-…/contracts/attention-rules.md` A1, A3, A4 (`:200-206`) and `attention-metrics.md`.
- `specs/007-…/contracts/incident-lifecycle.md` I5, A1, A2, H7 (`:27`, `:184`) and `incident-metrics.md`.
- Screen contracts:
  - `control-panel-attention.md:19`;
  - `control-panel-incidents.md:24,28,84-85`;
  - `control-panel-moderation.md:109,153,203`.
- Master plan §12.

## Non-goals
- Per-moderator **access control** (a moderator seeing only their groups) is a later roles change.
- No "Take it" button, no reassigning a single item, no rotation, no alerts. TG-M6 will later notify
  the team while unassigned, then the assignee.
- No full Team Performance dashboard; that is TG-M7, which will build on R6.
- No change to closing rules: any moderator's reply still closes an item.
- No change to the rule set, the models or incident status.

## Known limitations
- Correcting team history (including a backdated "since") **re-derives** assignments for acts inside
  the corrected interval. That is what a correction is for, but it is not a frozen snapshot, unlike
  today's `responsible_moderator_id`.
- A Telegram act is credited only if the person is declared as a moderator (`moderators.telegram_user_id`).
  A panel act is credited only if the panel account is linked to a moderator.
- Telegram never reports deletions, so a moderator who silently deletes spam leaves no act and is not
  assigned (master plan §18.6).

## Verification
- **Python (pytest, `_test` DB)**:
  - `team_at` at the four boundary positions, with two concurrent members;
  - view derivation:
    - reaction then reply (assigned via reaction to B, answered by A);
    - dismissal by a linked panel user;
    - a non-team moderator's reply (closes, no assignee);
    - an operator act (no assignee);
    - a membership starting after the act;
    - tie-break;
    - a chat migration;
  - an act after the end (assigns nothing);
  - a reversal (assigns nothing);
  - deactivation ending memberships;
  - the backdating floor;
  - every R6 figure against a hand-computed fixture:
    - a one-member team equals today's figures;
    - a miss appears in both members' rows and once in the group's;
    - an item taken by reaction and then expired.
  - `make check` stays green: architecture checks, no text in logs.
- **Panel (`DatabaseTransactions` on `injaz_ai_test`)**:
  - add, end and replace a member; overlap and inactive refusals;
  - the R4 snapshots;
  - the "Mine" default for linked and unlinked users;
  - `PanelTranslationCoverageTest` and `IncidentWordingArabicTest`.
- **Dev smoke**: one test group with moderators A and B.
  1. A student asks; the queue shows "Team: A, B".
  2. B reacts 👍; it shows "B, via reaction".
  3. A replies; the item closes as answered by A and stays assigned to B.
  4. Flag an advert; A acknowledges in the panel and it is assigned to A.
  5. Let one question expire: A's and B's "My groups" each show one unanswered, and the group shows one.
  6. B reacts after it expired: nothing changes.
- **Production follow-through**:
  1. Run `make migrate` on a rebuilt `migrate` image.
  2. Add the second moderator to the group's team, backdated no earlier than their declaration.
  3. Check that declaration date first (read-only `psql`), since only acts after it were recorded.

## Calls made on the builder's behalf (check these)
- The R1 backdating floor: no earlier than the moderator's declaration.
- Deactivating a moderator ends their memberships.
- A reversal doesn't assign.
- Acts after the end don't assign.
- The R6 two-scope design, which keeps one-member groups' figures identical to today. An item that was
  taken and then expired shows as both B's *assigned → expired* and the team's miss.
- Backups stay in the DB vocabulary.
- `responsible_moderator_id` is frozen rather than dropped.
- The assignee is derived in views, not stored.
