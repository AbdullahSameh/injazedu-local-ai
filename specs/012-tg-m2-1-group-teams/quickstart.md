# Quickstart: TG-M2.1 — Group Teams

## 1. Migrate

1. Rebuild the `migrate` image if it may be stale.
2. Run `make migrate`. Head is now `0011_group_teams`.

## 2. Development smoke (moderators A and B, one monitored test group G)

| Step | Action | Expected result |
|---|---|---|
| 1 | Groups › G › Team › **Add member** A. Then add B. | The Groups list shows "A, B". |
| 2 | A student asks a question in G. | The queue shows **Team: A, B**. |
| 3 | B reacts 👍 to the question. | **B · via reaction** on the next refresh. The item stays open. |
| 4 | A replies. | The item leaves the queue as answered by A. The assignee view still says B. |
| 5 | Flag an advert in G. A presses **Acknowledge**, signed in with A's linked panel account. | **Assigned: A · via panel acknowledge**. |
| 6 | Let one question expire. | Figures › By moderator › My groups: A and B each count it as unanswered once. By group: G counts it once. |
| 7 | B reacts to that expired question. | Nothing changes (G4). |
| 8 | Sign in as A. | **Mine** is on. Signed in as the operator, it is off. |

> **2026-10-21:** step 3's reaction is 👍, not 👀. Since TG-M4.1, 👀 on a *flagged* message resolves the incident, so it is kept for "handled" (`docs/plan/telegram/tg-eyes-reaction-resolution-plan.md`). On a question any reaction, 👀 included, still only takes it.

## 3. Production follow-through (operator)

1. Confirm the second moderator's declaration date. This is a read-only query.
   ```sql
   SELECT id, display_name, created_at, is_active FROM moderators ORDER BY id;
   ```
2. Groups › the group › Team › **Add member**, with "Since" no earlier than that `created_at`.
3. Link each moderator's panel account (Moderators › Panel account), so their panel acts are credited.

## 4. Rollback

`make migrate-down` restores `uq_assignment_one_current_primary`. It refuses while any group has two current
members: end the extra memberships first.
