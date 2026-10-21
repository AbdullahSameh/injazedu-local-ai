# Research: TG-M2.1 — Group Teams and First-Action Assignment

The source is the plan of record, `docs/plan/telegram/tg-group-teams-first-action-plan.md`, approved
2026-10-19. A builder check ran on 2026-10-19 and its findings are folded into R1, R2, R4 and R6. Decisions
continue the domain's numbering from D-TG-200.

## §0 — Findings (code read 2026-10-19)

- **Finding 20: one owner is enforced in four places.**
  - The database: `uq_assignment_one_current_primary` (0004:196).
  - Python `open_assignment('primary')`, which closes every current primary (`assignments.py:70`).
  - PHP `handover()`, the same (`ModeratorGroupAssignment.php:115`).
  - The panel's only write, "Reassign" (`AssignmentsRelationManager.php:54`).

  Backups have no production write path.
- **Finding 21: every act this milestone needs is already recorded, immutably, with its actor.**
  - Attention: `first_response_moderator_id`/`first_response_at` (`attention.py:601`), and `reaction` rows
    from declared moderators on any message (`evidence.py:58`).
  - Incidents: the four branches of `moderation_incident_evidence` (0006:220).
  - Missing: panel acts carry only the user (H7; `ModerationIncident.php:179`, `LiveAttentionQueue.php:278`).
- **Finding 22: a migration moves memberships but leaves items behind.** `repoint_for_migration` moves
  assignment rows to the surviving chat (`assignments.py:197`). Items and incidents stay on the superseded row
  (D-TG-107). A team check therefore has to follow `migrated_to_chat_id` one hop, as evidence (c) already
  does.
- **Finding 23: a one-member group's figures can stay exactly as they are.** Every per-moderator statement
  filters only `responsible_moderator_id = :m` (`metrics.py:44,62,235,275`; `AttentionMetrics.php`,
  `IncidentMetrics.php`). Swapping that one predicate for "on the team at the same instant" reproduces the old
  figure whenever the team is one person.

## §1 — Decisions

- **D-TG-201: a team is several current `primary` rows, not a new table or role.**
  - The column values stay, to avoid churn across two languages and the history. The UI says
    "Team member".
  - *Rejected:* renaming `primary` to `member`, which would rewrite history rows; a new
    `group_teams` table, which would be a second source of truth for the same interval facts.
- **D-TG-202: assignment is derived in views, never stored.**
  - Every act is already immutable evidence (Finding 21). A view is the project's existing idiom for derived
    state (N6, `moderation_incident_state`). There is no write path to race and no "write-once" update to
    guard.
  - *Rejected:* a stored `assigned_moderator_id` set by the first act. That needs a guarded update in each
    of six code paths (Telegram reply, reaction, ban; three panel acts) across two languages.
- **D-TG-203: one definition of the team, `moderation_team_intervals`.**
  - Python `team_at`, the PHP scopes, both assignee views and every F1 predicate read it, so the
    migration hop (Finding 22) is written once.
  - *Rejected:* a SQL function, a new kind of schema object this repository has none of; mirrored
    Python/PHP predicates, two definitions that could drift.
- **D-TG-204: only acts while live assign (G4); `reversal` never assigns (G3).**
  - From the builder check: otherwise a late 👍 after expiry, or after an outsider's answer, would make its
    author the assignee retroactively and wipe the team's miss.
- **D-TG-205: misses are counted by re-scoping today's figures (F1), not by a new "missed" definition.**
  - The operator chose "every team member" (D4). Re-scoping gives exactly that, keeps "covered from outside
    is not a miss" (`moderator-ownership.md` §4, A4), and leaves one-member groups unchanged (Finding 23).
  - An item taken with 👍 and then expired appears as the taker's *assigned → expired* in "My work" (F3) and as
    every member's unanswered in "My groups".
- **D-TG-206: the panel act snapshots the linked moderator at write time (C1).**
  - Consistent with V5, and a later re-link never moves history.
  - *Rejected:* a read-time join through `moderators.user_id`.
- **D-TG-207: backdating is floored at `moderators.created_at` (T4).**
  - Before a moderator was declared, their messages were never flagged `is_from_moderator`
    (`messages.py:290`, never recomputed) and their reactions were never recorded (`evidence.py:104`). A
    membership covering that time would charge them and their colleagues misses for questions they answered.
- **D-TG-208: deactivation ends memberships (T6).**
  - Otherwise someone who left stays in "Team: …" and keeps collecting misses.
  - *Rejected:* blocking deactivation while memberships are current, which adds friction for no information
    gain.
- **D-TG-209: Python keeps `handover` for the one-member case.**
  - `handover(chat, successor)` replaces the sole current member. With several current members it requires
    `replacing=<moderator_id>`. `open_assignment('primary')` now adds a member.
  - `responsible_at` is removed; `team_at` returns a sorted list.
  - Existing single-owner tests keep their meaning; team tests are new.
- **D-TG-210: "Mine" is a table filter defaulted per user, not a scope or policy.**
  - Access control is out of scope (spec Assumptions).

## §2 — Not measured here

- Query cost of the assignee views. At the current production volume (a few groups, tens of items per day)
  both are well inside the panel's 15 s poll. A covering index waits for a measured query over ~300 ms
  (master plan TG-M7).
