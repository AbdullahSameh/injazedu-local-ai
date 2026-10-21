# Contract: Group Teams and First-Action Assignment (TG-M2.1)

**Status**: the durable contract of TG-M2.1. It amends `specs/005…/contracts/moderator-ownership.md` §0, §2–§4.
It also amends `specs/006…/contracts/attention-rules.md` A1/A3/A4 and `specs/007…/contracts/incident-lifecycle.md`
I5/A1/A2/H7. Every superseded clause there carries a dated "Amended by TG-M2.1" note pointing here.

**Consumers**: TG-M3 (who an item is assigned to), TG-M4 (who an incident is assigned to), TG-M6 (who an
alert names), TG-M7 (every per-moderator figure).

---

## §0 — The promise

> **Asked who was on group *C*'s team at instant *T*, the platform answers with everyone who was on it
> *then*. Asked who an item or incident is assigned to, it answers with the first team member who acted
> on it while it was live, or with nobody. No later change moves either answer, except a correction of
> the team history itself.**

---

## §1 — Teams (T)

| # | Rule |
|---|---|
| **T1** | A team membership is a `moderator_group_assignments` row with `assignment_role = 'primary'` and a half-open interval `[valid_from, valid_to)`. Several memberships of one group may be current at once. `backup` rows are recorded and are never on a team. |
| **T2** | One moderator holds at most one current membership per group (`uq_assignment_one_current_membership`). Historical overlaps of one moderator in one group are refused at write time (T4) and caught by tests, not by the database (as `moderator-ownership.md` §7). |
| **T3** | `team_at(C, t)` is the set of moderators whose membership covers `t` on *C*, **or on the group *C* migrated into** (one hop, as in `moderation_incident_evidence` (c)). It is defined once, in the view `moderation_team_intervals`, and read by Python, by the panel and by every other view. O2 (nothing covers `t` ⇒ the empty set, never today's team), O3 (half-open) and O5 (stable) hold for the set. O1 ("at most one") is withdrawn. |
| **T4** | **Add:** one insert. It is refused when the moderator is inactive, when it would overlap that moderator's own interval in that group, when `valid_from` is in the future, or when `valid_from` precedes `moderators.created_at`. The last is the instant from which their messages were flagged and their reactions recorded. |
| **T5** | **End:** sets `valid_to` on one current row. **Replace:** one transaction, close before open, **one timestamp** bound to the incumbent's `valid_to` and the successor's `valid_from`. It touches only the named incumbent's row; other members are untouched. |
| **T6** | **Deactivation** (`is_active` true → false) ends every current membership of that moderator, in the same transaction, at one timestamp. |
| **T7** | **Chat migration** (§6 of the ownership contract) re-points every membership unchanged. It refuses when the surviving group already has a current team. |

---

## §2 — Acts and assignment (G)

| # | Rule |
|---|---|
| **G1** | Nothing is assigned at creation. `responsible_moderator_id` is no longer written for new rows; existing values are kept, never rewritten and never read by a figure. |
| **G2** | **Attention item acts**, each with an actor, an instant and a rank: (1) the answering reply, `first_response_moderator_id` at `first_response_at`, when `status = 'answered'`; (2) a panel dismissal, `closed_by_moderator_id` at `closed_at`, when `status = 'dismissed'`; (3) a `reaction` in `moderation_actions` by a declared moderator, targeting the item's anchor or any message whose `attention_item_id` is the item, at its `occurred_at`. |
| **G3** | **Incident acts:** every row of `moderation_incident_evidence` with a non-NULL `actor_moderator_id`, **except** `kind = 'reversal'`. |
| **G4** | An act **qualifies** only when both hold: its actor ∈ `team_at(item's group, act instant)`; and the act is at or before the end. An item's end is `COALESCE(first_response_at, closed_at)`, with none while open. An incident's end is the earlier of `resolved_at` and `closed_at` from `moderation_incident_state`, with none while neither is set. The closing act itself qualifies. |
| **G5** | The **assigned moderator** is the actor of the earliest qualifying act. Attention ties break by `(instant, rank, id)`; incident ties by D-TG-106's `(occurred_at, source_rank, evidence_id)`. |
| **G6** | Assignment is **derived**, never stored. It lives in the views `attention_item_assignee` and `moderation_incident_assignee`: one row per item or incident, with `assigned_moderator_id`, `assigned_at` and `assigned_via`. All three are NULL when there is no qualifying act. `assigned_via` is `reply`, `dismissal` or `reaction` for items, and the evidence `kind` for incidents. |
| **G7** | An act that does not qualify still does everything it did before: a reply still answers, a resolve still resolves. It only assigns nobody. |

> **Amended by TG-M4.1 (2026-10-21, `docs/plan/telegram/tg-eyes-reaction-resolution-plan.md`).** A moderator's 👀 on a flagged message is recorded as a `reaction` with `confirmation` strength, so it is still a G3 act (it assigns when it is the first qualifying one) and it now also resolves the incident. The resolver is read from `moderation_incident_state`, so a colleague who acted first stays assigned. On a question, 👀 is a G2 reaction like any other: it takes the item and never closes it. This feature's examples of "I'm on it" use 👍, so 👀 keeps one meaning for moderators: *handled*.

---

## §3 — Crediting panel acts (C) — amends TG-M4 H7

| # | Rule |
|---|---|
| **C1** | A panel act by a user linked to a moderator (`moderators.user_id`, revision 0009) records that moderator **at write time**. An attention dismissal records it as `attention_items.closed_by_moderator_id`; an incident panel act as `moderation_actions.actor_moderator_id`. The moderator is never recomputed afterwards (as V5). |
| **C2** | `closed_by_user_id` and `panel_user_id` are still written on every panel act. An unlinked user's act is credited to that user and assigns nobody. |

---

## §4 — Figures (F) — amends `attention-metrics.md` and `incident-metrics.md`

| # | Rule |
|---|---|
| **F1** | **"My groups"**: every statement that took `:moderator_id` as `responsible_moderator_id = :moderator_id` now takes `EXISTS (SELECT 1 FROM moderation_team_intervals t WHERE t.telegram_chat_id = <row>.telegram_chat_id AND t.moderator_id = :moderator_id AND t.valid_from <= <row>.<instant> AND (t.valid_to IS NULL OR t.valid_to > <row>.<instant>))`. `<instant>` is `opened_at` for items and `detected_at` for incidents. Nothing else in the statement changes. `:moderator_id IS NULL` still means "no filter". |
| **F2** | One consequence of F1: a miss in a group with *n* members appears in each of the *n* members' rows and once in the group's. For a one-member group, F1 equals the old figure. |
| **F3** | **"My work", attention**: per moderator *M* and period (by `opened_at`): `assigned` (assignee = *M*), split by `assigned_via` and by status (answered, dismissed, open, expired); `answered_by_me` (`first_response_moderator_id = M`, `status = 'answered'`), with median, p90 and max of `first_response_at − opened_at` under the existing small-sample rule; `outside` (answered by *M* while *M* was not on that group's team at `first_response_at`). |
| **F4** | **"My work", incidents**: per *M* and period (by `detected_at`): `assigned`, split by current status and by `assigned_via`; median, p90 and max of `assigned_at − detected_at` over non-negative values, with negative values counted as `before_flagging` (as M12); `outside` (incidents with an act by *M* while *M* was not on the team at that act's instant). |
| **F5** | Detection latency stays group- and source-level only (M16). No average, no composite score, no ranking (M14, D-TG-92). |

---

## §5 — Screens (S)

| # | Rule |
|---|---|
| **S1** | Live Attention Queue and Incidents show **Assigned**: the assignee's name and how they took it; otherwise, while the row is still live, "Team: names" (the current team) or "No team" (a red badge); once it has ended untaken (answered, dismissed or expired; resolved or not a violation), "Not taken by the team" (amended 2026-10-21, operator). It reads the views and computes nothing. |
| **S2** | **Mine**: rows assigned to me, plus unassigned rows whose group has me on its current team. It is on by default when the signed-in user is linked to a moderator, and off otherwise. It is a filter, not access control. |
| **S3** | Incidents' "Responsible" filter becomes **Assigned to**, read from `moderation_incident_assignee`. The incident page shows **Team at flagging** (`team_at(group, detected_at)`) and **Assigned**. |
| **S4** | Moderators › Assignments and Groups › Team offer **Add** (with a "since" field, by T4), **End** and **Replace with…** (by T5). Groups lists each current team and flags a monitored group with nobody on it. Both history tables list newest first, ten to a page (2026-10-21). |
| **S5** | Every new string goes through `__()`, with Arabic in `lang/ar.json`. No deletion word appears on incident screens. |

---

## §6 — Never (N)

| # | Never |
|---|---|
| **N1** | An item or incident shows two assigned moderators. |
| **N2** | An assignment is written, updated or deleted as a value. |
| **N3** | A moderator who was not on the team at the act's instant is assigned. |
| **N4** | An act after the item or incident ended assigns anyone. |
| **N5** | Today's team is substituted for a past instant. |
| **N6** | A per-moderator figure reads `responsible_moderator_id`. |

---

## §7 — Limitations

- A correction of team history (a backdated "since", or ending a membership early) re-derives the
  assignment of acts inside the corrected interval. That is a correction's purpose. It differs from the
  old frozen snapshot.
- Telegram reports no deletion. A moderator who silently deletes spam leaves no act and is not assigned
  (master plan §18.6).
- A Telegram act is credited only to a declared moderator. A panel act is credited only through the
  account link.
- `moderation_team_intervals` follows a migration one hop, as the evidence view does.
