# Feature Specification: TG-M2.1 — Group Teams and First-Action Assignment

**Feature Branch**: `m2.1/group-teams-first-action` (created by the operator; Git is operator-owned, constitution IV)
**Created**: 2026-10-19
**Status**: Implemented (T401–T415); development smoke and production follow-through are the operator's (T416–T417)
**Input**: "In production, one group has one bot and two moderators. When an attention item or an incident
opens, assign it to one moderator from this group's assigned moderators. A Telegram group generally has one
moderator, but when it has many members it will need more than one. Also track each moderator's actions and
work, for reports later." (operator, 2026-10-19). The plan of record is
`docs/plan/telegram/tg-group-teams-first-action-plan.md`. It holds decisions D1–D4 and rules R1–R7.

## Provenance: what this milestone changes, and what it keeps

- **TG-M2** (`specs/005…/contracts/moderator-ownership.md`) gave a group **exactly one** current primary
  owner.
  - It has a database guarantee: `uq_assignment_one_current_primary`.
  - O1: `responsible_at(chat, t)` returns at most one moderator.
  - §4: every item and incident snapshots that one owner at creation.
  - Backups are recorded and are never responsible (O4).
- **TG-M3 / TG-M4** snapshot that owner onto `responsible_moderator_id`.
  - Attention: A1/A3/A4 at `opened_at`.
  - Incidents: I5/A1/A2 at `detected_at`.
  - Every per-moderator figure filters on the snapshot.
  - TG-M4 H7 never credits a moderator for a panel act.
- **TG-M2.1** replaces "one owner per group" with a **team** of one or more equal moderators. It replaces
  "the owner at creation" with **the first team member to act**.
  - A one-member team keeps today's figures exactly.
  - Every superseded statement gets a dated "Amended by TG-M2.1" note beside it; none is deleted.
- **Kept unchanged:**
  - the half-open interval algebra and O2/O3/O5;
  - the handover protocol's three clauses (now applied to one named membership);
  - chat-migration re-pointing;
  - every closing rule ("any moderator's reply closes an item");
  - incident status;
  - the rule set, the bursts and the models;
  - TG-M5's and TG-M5.3's switches.

## Clarifications

### Session 2026-10-19 (operator, while planning)

- Q: How do the two moderators share the group? → A: **Both watch all day.** Whoever sees a message first
  answers it.
- Q: Who uses the panel? → A: **Moderators and the operator.** Moderators use it to catch every question
  that needs a response and every incident that needs action. The operator uses it to watch every group
  and what each moderator does.
- Q: How is the one assigned moderator picked? → A: **By first action.**
  - Nobody is assigned when an item or incident opens.
  - The first moderator on that group's team to take **any** action on it becomes its assigned moderator,
    for good. This applies to attention items and incidents alike.
  - There is no "Take it" button; acting is taking.
- Q: Who does a miss count against? (A question nobody answers, or an incident nobody handles.) → A:
  **Every team member.** Each moderator on the team at the time counts it once, and the group counts it
  once.

## User Scenarios & Testing *(mandatory)*

### User Story 1: a group has a team, and an item belongs to whoever acts first (P1)

The operator adds moderators A and B to group G's team. A student asks a question.
1. The Live Attention Queue shows the item as **"Team: A, B"**.
2. B reacts 👍 to the question in Telegram. The item now shows **"B · via reaction"** and stays open.
3. A replies. The item closes as answered by A and stays **assigned to B**.

An advert is flagged in G and A acknowledges it in the panel. The incident is **assigned to A**.

**Why this priority**: this is the operator's problem as stated. Without it the second moderator's work
is invisible.

**Independent test**: with only US1 built, the "Assigned" column and the incident page show the right
moderator for every one of the acts below.

**Acceptance**:
1. A team member's reply, panel dismissal or reaction (on any of the item's messages) on an open item assigns it to them. The earliest
   such act wins.
2. A team member's reaction, direct reply, ban/expulsion/restriction, panel Acknowledge, panel Resolve
   or panel "Not a violation" on an incident assigns it to them.
3. An act by a moderator who is not on G's team at that moment, or by an operator whose panel account is
   not linked to a moderator, assigns nobody. It still closes or resolves exactly as today.
4. An act that lands after the item or incident ended assigns nobody, for example a reaction after expiry.
5. A `reversal` (an undone ban or restriction) assigns nobody.
6. Once assigned, an item or incident keeps its moderator whatever happens next.

### User Story 2: the operator manages each group's team (P1)

From a moderator's page or a group's page, the operator can do three things:
- **adds** a moderator to a group (from now, or backdated to a chosen instant);
- **ends** a membership;
- **replaces** one member with another at one instant.

The Groups list shows each group's team and flags a monitored group with nobody on it.

**Why this priority**: US1 needs a team to exist. Production needs the second moderator added.

**Independent test**: add A and B to one group and confirm both are current. End A and confirm that B
alone remains. Replace B with C and confirm there is no gap and no overlap at the handover instant.

**Acceptance**:
1. Several moderators can be current members of one group at once.
2. Adding is refused in four cases:
   - the moderator is inactive;
   - the new membership would overlap that moderator's own membership in that group;
   - the start is in the future;
   - the start is before the moderator was declared.
3. Replacing closes only the named membership and opens the successor, both at one instant. Other members
   are untouched.
4. Deactivating a moderator ends every current membership they hold, at the deactivation instant.
5. A chat migration carries every membership to the surviving group unchanged. It is refused, and the
   conflict surfaced, when the surviving group already has a current team.

### User Story 3: a moderator sees their own work first (P2)

When a moderator who is linked to a panel account opens the Live Attention Queue or the Incidents list,
the **"Mine"** view is on by default. It shows unassigned items in groups where they are on the team, plus
anything assigned to them. One click shows everything. An operator with no linked moderator sees
everything by default.

**Acceptance**:
1. "Mine" is the default for a linked user and off for an unlinked one.
2. "Mine" never hides anything permanently. It is a filter, not access control.

### User Story 4: reports show each moderator's share of the team's work and misses (P2)

Each moderator's row has two parts.
- **"My groups"** shows today's figures, counted over the groups they were on the team of when each item
  opened or incident was flagged:
  - attention: asked, answered, first-response times, unanswered;
  - incidents: flagged, handled, missed, within window, false positive.
- **"My work"** shows:
  - what was assigned to them, by how it was taken and how it ended (expired included);
  - what they answered and how fast;
  - what they did in groups outside their team.

**Acceptance**:
1. For a group with one member, "My groups" equals the figures that member saw before TG-M2.1.
2. An expired question in a two-member group counts once in each member's "My groups" unanswered, and
   once in the group's.
3. An item B took with 👍 and then let expire shows in B's "My work" as assigned → expired, **and** in both
   members' "My groups" as unanswered.
4. No figure is an average across moderators and no composite score exists.

### Edge Cases

- **Two acts at the same instant**: the existing tie-break decides them.
  - Incidents: `(occurred_at, source_rank, evidence_id)` (D-TG-106).
  - Attention: instant, then reply before dismissal before reaction, then id.
- **A moderator added after the act**: the act was not a team member's, so it assigns nobody.
- **Correcting history**: backdating a membership (a correction) re-derives the assignments of acts inside
  the corrected interval. This is the intended effect of a correction and is documented as a limitation.
- **A group with nobody on its team**: items show "No team" and stay assignable by nobody.
- **A moderator with no panel link** acting through Telegram is still credited. A linked moderator's panel
  act is credited to them. An unlinked panel user's act is credited to that user.
- **Group migration**: an item on the superseded chat is judged against the team of that chat or its
  successor.
- **Legacy rows** opened before TG-M2.1 keep their `responsible_moderator_id`. Their assignment is derived
  the same way as new rows'.

## Requirements *(mandatory)*

### Functional Requirements

**Teams (amends TG-M2)**
- **FR-401**: A group MUST be able to have several current team members, each a time-versioned membership
  `[valid_from, valid_to)`. One moderator MUST NOT hold two current memberships in one group.
- **FR-402**: `team_at(group, t)` MUST return every moderator whose membership covers `t`. The interval
  includes `valid_from` and excludes `valid_to`. A backup is never on the team, and today's team is never
  substituted for a past instant.
- **FR-403**: Add, end and replace MUST each be one transaction. Replace MUST close only the named
  membership and open the successor at **one** timestamp.
- **FR-404**: Opening a membership MUST be refused in four cases:
  - the moderator is inactive;
  - it overlaps the moderator's own membership in that group;
  - its start is in the future;
  - its start precedes the moderator's declaration.
- **FR-405**: Deactivating a moderator MUST end their current memberships at the same instant, in the same
  transaction.
- **FR-406**: A chat migration MUST re-point every membership without opening or closing an interval. It
  MUST refuse when the surviving group already has a current team.

**Assignment (amends TG-M3 A1/A3/A4, TG-M4 I5/A1/A2)**
- **FR-410**: A new item or incident MUST be created with no assigned moderator.
- **FR-411**: An item's assigned moderator MUST be the actor of its earliest qualifying act. The acts are:
  - a moderator's reply that answered it;
  - a panel dismissal;
  - a moderator's reaction on one of its messages (the anchor or a burst member), while it was live.
- **FR-412**: An incident's assigned moderator MUST be the actor of its earliest qualifying evidence row,
  excluding `reversal`.
- **FR-413**: An act MUST qualify only if both hold:
  - its actor was on the group's team at the act's instant;
  - it happened at or before the item's or incident's end (`closed_at`; for an incident, the resolving or
    false-positive evidence).
- **FR-414**: The assigned moderator MUST be derived from recorded acts and team history. It is never
  written or updated as a value.
- **FR-415**: `responsible_moderator_id` MUST no longer be written for new rows. Existing values are kept
  unchanged and never rewritten.

**Crediting panel acts (amends TG-M4 H7)**
- **FR-420**: When the acting panel user is linked to a moderator, the moderator MUST be recorded on the
  act at write time:
  - on an attention dismissal;
  - on every incident panel act.
- **FR-421**: The panel user MUST still be recorded on every panel act.

**Screens**
- **FR-430**: The Live Attention Queue and the Incidents list MUST show **Assigned**:
  - the moderator's name and how it was taken; otherwise
  - "Team: …" with the current team's names; otherwise
  - "No team".
- **FR-431**: Both screens MUST offer **Mine**: unassigned items in my current groups, plus items assigned
  to me. It is on by default for a user linked to a moderator. The Incidents "Responsible" filter becomes
  "Assigned to".
- **FR-432**: The incident page MUST show the incident's team and its assigned moderator.
- **FR-433**: The Moderators page and the Groups page MUST offer Add to group / Add member, End and
  Replace. The Groups list MUST show each team and flag a monitored group with an empty team.
- **FR-434**: Every new string MUST be bilingual: English as the key, Arabic in `lang/ar.json`.

**Figures (amends `attention-metrics.md`, `incident-metrics.md`)**
- **FR-440**: Every per-moderator figure that today selects `responsible_moderator_id = M` MUST instead
  select "M was on the group's team at `opened_at` / `detected_at`". The figure definitions are otherwise
  unchanged.
- **FR-441**: Per moderator, "My work" MUST report:
  - items assigned, by how they were taken and by outcome (answered, dismissed, open, expired);
  - items answered, with first-response median, p90 and max, under today's small-sample rule;
  - acts outside their own groups;
  - incidents assigned, by status, with the time from detection to the assigning act.
- **FR-442**: Detection latency MUST stay group-level only. There MUST be no average across moderators and
  no composite score.

### Key Entities

- **Team membership**: a moderator on a group over `[valid_from, valid_to)`. It is an existing assignment
  row with the `primary` role. Several can be current at once.
- **Act**: a recorded thing a moderator did to an item or incident, in Telegram or in the panel. Each act
  is already stored immutably, with its actor and its instant.
- **Assigned moderator**: derived per item and per incident as the earliest qualifying act's actor, with
  the act's instant and kind.

## Success Criteria *(mandatory)*

- **SC-401**: In a group with two team members, 100% of items and incidents that a team member acted on
  show that member as assigned. The second moderator's work is visible on every screen and in every
  per-moderator figure.
- **SC-402**: For every group with one team member, every pre-existing per-moderator figure is identical
  before and after TG-M2.1, checked against a hand-computed fixture.
- **SC-403**: A miss in a two-member group appears once in each member's figures and once in the group's,
  never zero and never three times.
- **SC-404**: The operator can add the production group's second moderator in under a minute, and the
  queue shows "Team: A, B" on the next refresh.
- **SC-405**: No item or incident ever shows two assigned moderators. An assignment never changes once
  shown, unless team history is corrected.

## Assumptions

- Moderators and the operator are the only panel users, and every panel user may see every group. Access
  control per moderator is a later change.
- A Telegram act is credited only to a declared moderator (`moderators`). A panel act is credited only
  through the panel-account link (revision 0009).
- Telegram never reports deletions, so a moderator who silently deletes spam leaves no act (master plan
  §18.6).
- No alerts exist yet (TG-M6). When they do, an alert will go to the team while an item is unassigned, and
  to the assignee after.

## Out of Scope

- A "Take it" button, reassigning one item, and rotation or load balancing.
- Access control per moderator.
- Alerts (TG-M6).
- The full performance dashboard (TG-M7).
- Any change to closing rules, incident status, the rule set, bursts, the models, or `responsible_moderator_id`'s stored values.
