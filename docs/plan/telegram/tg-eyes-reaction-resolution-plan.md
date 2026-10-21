# 👀 Resolves an Incident, and the Assigned Display Fix — plan

> **Status:** approved by the operator 2026-10-21 ("Now" scope), implemented on branch
> `m2.1/group-teams-first-action`. Working label **TG-M4.1**: it amends TG-M4's incident lifecycle
> (`specs/007-tg-m4-policy-incidents/contracts/incident-lifecycle.md`) and TG-M2.1's screens
> (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` S1). TG-M6's shared alert group is
> recorded in the master plan and is **not** built here.

## Context

The development smoke of TG-M2.1 (2026-10-20/21) showed that a moderator who handles spam in
Telegram, for example by deleting it, leaves nothing the bot can see: Telegram sends bots no
deletion event. The incident then stays open until someone resolves it in the panel.

The operator wants Telegram and the panel to be **two interfaces for one workflow**:
1. see an incident in Telegram;
2. acknowledge it with any reaction except 👀;
3. handle it;
4. react 👀 to mark it resolved;
5. see the right status and history in the panel.

**Why 👀 and not ✅:**
- Members must not read a moderator's reaction on an advert as approval; 👀 is neutral.
- ✅ is not in Telegram's reaction set anyway, so it could not be a reaction at all.

## Review of the current code and contracts

| Finding | Where | Consequence |
|---|---|---|
| A moderator's reaction is recorded as one `moderation_actions` row, `action_type = 'reaction'`, strength `acknowledgement`. Only declared moderators' reactions are kept, only *added* reactions count, at most one row per captured event. | `evidence.py:58`, lifecycle V7–V10, V13 | The recording path already gives idempotency (V13) and safe removal (V7: a removal adds nothing, so it records nothing). |
| `ck_actions_strength` pins reaction to `acknowledgement`. S4: "Acknowledgement never resolves." N1: "Resolution from acknowledgement alone" is forbidden. | 0006, lifecycle S4/N1 | **Conflict.** The constraint and S4 must change for reactions. N1 still holds: a 👀 is recorded as a *confirmation*, not as an acknowledgement. |
| The evidence view passes each row's own strength through. The state view resolves on the earliest `enforcement` or `confirmation`. | 0006 views | Once a 👀 row carries `confirmation`, status, resolution moment, resolver and trail all follow, with **no view change**. |
| Reaction inserts take no lock, because "two acknowledgements racing are harmless". Membership inserts take `moderation:incidents` because they can resolve. | lifecycle H4, `locks.py` | **Conflict.** A resolving reaction must take the lock too. Otherwise it could race a panel "Not a violation" and an incident would end up `closed_false_positive` over a real resolution (research probe 8). |
| `moderator_id_for` deliberately ignores `is_active`. | `identities.py:79` | Bans need admin rights; a reaction needs none. A deactivated moderator who stays in a group could close incidents. See decision E3. |
| TG-M2.1's attention view counts any reaction on a question as taking it. Its spec, plan and quickstart use 👀 as the example "I'm on it". | 0011, `specs/012…` | **Conflict of meaning.** The examples move to 👍; the behaviour on questions is unchanged (E8). |
| TG-M2.1's incident assignee view takes any non-reversal evidence. | 0011 | A 👀 by a team member assigns as its first act, with no change. The resolver is read separately from the state view, so the person who resolved is recorded even when someone else took it first. |
| Incident figures time confirmations and count confirmations dated before the flag in `conf_before_flagging`, never in a percentile (M12). | `metrics.py:273` | A 👀 is a confirmation and needs no new figure. Enforcement stays a separate measure: no ban is claimed. |
| The Assigned column shows the *current* team for every unassigned row, even closed ones; the incident page says "Not yet — the first team member to act takes it" after resolution. | `TeamAssignment::label`, `IncidentInfolist::assignedText` | The operator's display fix (part A). |
| The panel's `Resolve` already works from `open`. | lifecycle H1 | Nothing to change. |

## Part A — Assigned display (approved)

- **Open, unassigned:** "Team: names" (current team), or "No team" in red when nobody is on it. Unchanged.
- **Closed, never assigned:** "Not taken by the team", in grey.
  - For attention items, "closed" means answered, dismissed or expired.
  - For incidents, it means resolved or not a violation.
- **Assigned:** unchanged.
- The incident page's "Assigned" says the same for a closed incident.
- No change to assignment or reporting.

## Part B — 👀 resolves an incident (approved)

**E1. What is recorded.**
- The same `reaction` row as today.
- Its strength is decided once, at write time, by a pure domain function:
  - `confirmation` when the added reactions include the standard emoji 👀 and the reactor is an
    active moderator;
  - `acknowledgement` otherwise.
- Nothing already recorded is reinterpreted. Development's earlier 👀 rows stay acknowledgements,
  and so will production's.
- A new check, `ck_actions_reaction_confirmation`, refuses a confirming reaction row whose added
  reactions lack 👀.

**E2. Which 👀 counts.**
- Exactly the standard emoji 👀 (U+1F440).
- A custom (Premium) emoji that looks like eyes does not count, and neither does a paid ⭐.
- It must be **on the flagged message itself**, by someone other than its author. This is the
  evidence view's existing reaction rule.
- An anonymous administrator ("posting as the group") names no person and records nothing (V8).

**E3. Who can resolve.**
- An **active** declared moderator. A deactivated moderator's 👀 stays an acknowledgement, exactly
  as before this change.
- A non-moderator's reaction is still not recorded at all (V9).
- Any active moderator may resolve, on the group's team or not, as with a ban or a panel Resolve.
  - From outside the team it does not assign (G-rules).
  - It is counted as "outside" in that moderator's "My work" (A4).

**E4. Lock.** A confirming reaction takes `pg_advisory_xact_lock(hashtext('moderation:incidents'))`
before its insert, as membership evidence does (H4). An acknowledging reaction still takes no lock.

**E5. Order and changes.** S1's precedence is unchanged.

| Moderator does | Result |
|---|---|
| 👀 first | Open → **Resolved** directly |
| 👍 then 👀 | Acknowledged, then Resolved; acknowledger and resolver may differ |
| 👍 → 👀 (changes the reaction) | Adds 👀 → Resolved |
| 👀 → 👍 (changes the reaction) | Adds 👍 → an acknowledgement row only; still Resolved |
| Removes 👀 | Adds nothing → nothing recorded; still Resolved |
| 👀 again later | Another confirmation row in the trail; `resolved_at` stays the first |
| 👀 after "Not a violation" | Listed in the trail; still Not a violation (H5) |
| Same event processed twice | One row (V13) |

**E6. 👀 before the flag.**
- A moderator who handles spam before the model flags it leaves a 👀 dated before `detected_at`.
- The incident then appears already resolved, shown as "acted before flagging".
- It is counted in `conf_before_flagging`, never in a percentile, so there is no negative duration
  (M12).

**E7. What 👀 never does.** It only records the moderator's word that the violation was handled.
The bot still bans, restricts, deletes, reacts and posts nothing (N5).

**E8. Questions.**
- On an attention item any reaction, 👀 included, still only takes the question (TG-M2.1 G-rules)
  and never closes it. A question closes only by an answer, dismissal or expiry.
- The TG-M2.1 documents' "I'm on it" example becomes 👍, so moderators learn one meaning for 👀:
  *handled*.

**E9. Allowed in the groups.**
- 👀 is in the Bot API's standard reaction list.
- A group's administrators can still limit reactions. `make tg-doctor` therefore reads each
  monitored chat's `available_reactions` through a read-only `getChat` and flags any chat where 👀
  is not allowed.
- The operator runs it in production, read-only, before relying on 👀 there.

**E10. A false flag is not "handled".** 👀 means "this was a violation and I handled it". A flag
that was wrong should still be closed with the panel's "Not a violation", so the model's
false-positive count (C3) stays true. This is training for moderators, not code.

## Files
- **Python** (`apps/ai-api/`):
  - `alembic/versions/0012_eyes_confirmation.py`: replaces `ck_actions_strength` and adds
    `ck_actions_reaction_confirmation`. Its downgrade refuses while a confirming reaction exists.
  - `models_moderation.py`: parity.
  - `domain/moderation/incident.py`: `RESOLVING_REACTION` and `reaction_strength`.
  - `application/moderation/evidence.py`: strength, active check, lock.
  - `providers/telegram/client.py`: read-only `get_chat_available_reactions`.
  - `scripts/tg_doctor.py`.
  - Tests.
- **Panel** (`apps/ai-control/`):
  - `TeamAssignment` (label and colour take "is it still live?");
  - `LiveAttentionQueue`, `IncidentsTable`, `IncidentInfolist`;
  - `IncidentDisplay` (a 👀 row reads "Reaction 👀 — handled");
  - `lang/ar.json`;
  - tests.
- **Contracts**: dated "Amended by TG-M4.1 (2026-10-21)" notes in:
  - `specs/007…`: `incident-lifecycle.md`, `data-model.md`, `control-panel-incidents.md`;
  - `specs/012…`: `contracts/group-teams.md` S1, plus the 👍 examples in spec, plan and quickstart;
  - the master plan's D-TG-07 and §14.2/§14.3.

## Known limitations
- A moderator posting as the group (anonymous administrator) cannot resolve with 👀; their
  reaction names nobody.
- 👀 on a *copy* or a reply resolves nothing; it has to be on the flagged message.
- A 👀 the bot never receives cannot count. This covers a group where the bot is not an
  administrator, and a chat whose reactions exclude 👀. `make tg-doctor` reports both.
- Re-deriving a chat (`rederive_chat.py --with-evidence`) records an event that was never recorded
  under today's rule, so a 👀 captured but never recorded would now resolve. Already-recorded rows
  never change.

## Verification
- pytest:
  - the pure strength function;
  - the recorder for every E5 row, a non-moderator, an inactive moderator, an anonymous reactor
    and a custom emoji;
  - the migration's checks;
  - resolver differs from assignee;
  - the panel guard refusing "Not a violation" after a 👀.
- PHP:
  - Assigned states (open / closed / no team);
  - a 👀 trail row's label;
  - translation coverage.
- `make check`.
- Development smoke, by the operator in the test group: 👍 → acknowledged; 👀 → resolved with the
  resolver; 👀 first on a fresh flag → resolved; remove 👀 → still resolved. Then `make tg-doctor`.
- **No production deploy.**
