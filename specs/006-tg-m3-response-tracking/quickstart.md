# Quickstart: TG-M3 — Deterministic Response Tracking

**Feature**: `specs/006-tg-m3-response-tracking` · **Audience**: the operator, on this MacBook

This is the milestone the runbook marks 🎯 — the first vertical slice, and the first smoke test that
runs against a **real group with real students in it**. Read `docs/runbooks/tg-operator-prerequisites.md`
§C's TG-M3 row and §D before starting.

---

## 0. Before you start

Everything from TG-M0…TG-M2 still holds: `make doctor` green, both bots created with privacy disabled
before the first group add, the dev group with its two extra accounts, the bot an administrator, the
dev credential in `.env`, and at least one group marked measured with a moderator mapped and an
assignment open.

Two decisions become prerequisites at this milestone and are **yours, not the agent's**:

1. **Name the pilot group and its moderator.** This is open question 5 of the source plan's §28. The
   first vertical slice has no subject without it.
2. **Decide where the live capture process runs** — runbook §D. A sleeping laptop over a weekend
   permanently loses that window, and the resulting gap is *indistinguishable from a fast moderator*.
   Pick one: `caffeinate -s` the machine, move the `ai-telegram` container to an always-on host, or
   accept nightly gaps explicitly and remember that this milestone does not yet mark a report
   incomplete where it overlaps one.

Neither is needed to develop or test this milestone. Every automated test runs with no credential, no
network and no model runtime.

---

## 1. Migrate

```bash
make migrate
make psql
```

```sql
\d attention_items
\d+ telegram_messages          -- attention_item_id, attention_evaluated_at at the end
SELECT version_num FROM alembic_version;   -- 0005
```

Nothing else changed. No `GRANT` was needed.

---

## 2. Watch a question become an item

In your **dev** group, as the test "student" account:

```
الكتاب مش ظاهر عندي
```

Ninety seconds later:

```sql
SELECT id, telegram_chat_id, telegram_message_id, opened_at, source, rule_version,
       responsible_moderator_id, status
FROM attention_items ORDER BY id DESC LIMIT 5;
```

`opened_at` is **the message's own send time**, not ninety seconds later. `source='rule'`,
`rule_version=1`, and `responsible_moderator_id` is whoever owned the group at that instant.

Now post three messages in a row, a few seconds apart, only the last of which asks anything:

```
السلام عليكم
أنا مشترك في الدورة
ولكن المحاضرة مش ظاهرة
```

One item, dated from the **first** of the three. That is what the student actually waited.

Then post `شكرا` on its own. No item — the acknowledgement stoplist.

---

## 3. Watch a reply close it

Reply to the question as the mapped moderator:

```sql
SELECT status, first_response_kind, first_response_at - opened_at AS frt,
       responsible_moderator_id, first_response_moderator_id
FROM attention_items WHERE id = :id;
```

`direct_reply`, and the gap is the number. Now try the other three cases:

| Try this | Expect |
|---|---|
| Three questions waiting, one plain moderator message (no reply) | **Only the oldest** closes |
| A direct reply to the *second*-oldest | That one closes, out of order |
| A moderator *reaction* (✅) on a waiting question | **Nothing closes.** A reaction is not an answer |
| A reply from the second test account (not a moderator) | Nothing closes |

---

## 4. Smoke test — the runbook's own

In the **pilot** group, with the live bot admin and the live credential on the machine that will run it:

1. Post a question at, say, **10:03**.
2. Reply as the moderator at **10:11**.
3. Open **Live Attention Queue**. The item shows **8m**, `direct_reply`, attributed to the moderator
   responsible **at 10:03**.
4. Now reassign the group to someone else in **Moderators → Assignments**.
5. Look at the item again. **The number and the name have not moved.**

Step 5 is the milestone. If the attribution follows the reassignment, ownership history is not being
used and every historical report is wrong.

Then confirm the silence: read the student group. The bot has posted nothing.

---

## 5. Correcting the rules

The rule set will be wrong. That is the design — the corrections are the measurement.

- Dismiss a false positive from the queue (*not a real question*).
- Find a real question the rules missed and **open an item by hand** against it.

```sql
SELECT rule_version,
       count(*) FILTER (WHERE source='rule')                          AS rule_opened,
       count(*) FILTER (WHERE source='rule' AND status='dismissed')   AS dismissed,
       count(*) FILTER (WHERE source='operator')                      AS operator_added
FROM attention_items GROUP BY rule_version;
```

`precision = 1 − dismissed ÷ rule_opened`. That number is the baseline TG-M5's model has to beat. Look
at it after a week of the pilot, not after an afternoon.

---

## 6. Catching a group up

Only if you want history. Nothing backfills on its own.

```bash
docker compose -f infra/docker-compose.yml exec ai-worker \
  python -m app.scripts.rederive_chat --chat-id -100123456789 --with-attention --since 2026-09-15
```

It reports **opened / answered / expired**. Read those three numbers before you read any figure: a
backfill over a window nobody was watching writes unanswered history, and questions that *were* answered
come back answered with their real times. Running it twice changes nothing.

---

## 7. Verify

```bash
make check      # ruff, mypy, pytest, the PHP feature suite, the secret scan
```

Passes offline, with Ollama quit and **no Telegram token set**.

---

## 8. Known limitations

1. **An unobserved window looks like a fast moderator.** A question asked while capture was down was
   never captured and opens no item; an answer given then closes none. The windows are recorded, but
   nothing renders a report incomplete over them until TG-M7. Run the smoke test in a window you know
   was observed. This is why §D's decision matters now.
2. **No expiry and no sweep while the capture process is stopped.** Both recurring steps are enqueued
   by the poll loop's tick (D-TG-86). With no credential configured nothing is captured either, so
   nothing is lost — but a long stand-down after repeated conflicts stops ageing too.
3. **A lost delayed judgement is covered, but only on the next tick.** The sweep is authoritative, so a
   Redis flush costs latency, not items — up to one tick interval.
4. **`من` over-fires.** It means "who" and is also the commonest preposition in Arabic. It is kept in
   rule set v1 deliberately so its cost lands in the measured false-positive rate rather than in an
   unrecorded judgement call. Expect dismissals.
5. **A student answering their own question does not close the item.** They are not a moderator. It ages
   until a moderator responds, you dismiss it, or it expires.
6. **An edit that removes a question does not retract the item**, and an edit to a burst whose item was
   dismissed or expired does not bring it back.
7. **A dismissed item never comes back**, on any later message.
8. **Expired items are counted unanswered forever.** They contribute no response time and never appear
   in "oldest waiting". That asymmetry is deliberate.
9. **p90 is suppressed below 10 answered items**, with a reason rather than a number. Four samples
   produce an authoritative-looking figure built from four points.
10. **No average, and no score for anyone.** Not deferred — excluded from v1.
11. **Telegram reports no deletion and no deleter.** *Message removed* is your judgement, recorded as
    yours.
12. **No incident, no alert, no model, no outbound message.** TG-M4, TG-M5, TG-M6.

---

## 9. Next

TG-M4 — policy incidents: the OPEN → ACKNOWLEDGED → RESOLVED lifecycle, moderator actions, and the
enforcement evidence from `chat_member` and `message_reaction` that this milestone deliberately leaves
uninterpreted. Have a disposable third account in the dev group you are willing to ban.
