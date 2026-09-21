# Quickstart: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Audience**: the operator, on this MacBook. Runbook context:
`docs/runbooks/tg-operator-prerequisites.md` §C, TG-M2 row.

---

## 0. Before you start

From the runbook's TG-M2 row: **collect your own Telegram user id and the two test accounts' ids.**

They are numeric and you need them written down. Every one of them can be mapped before the person has
posted anything (research D-TG-52), so you do not have to choreograph who speaks first.

```bash
curl -s "https://api.telegram.org/bot<DEV_TOKEN>/getUpdates" \
  | python3 -m json.tool | grep -A4 '"from"'
```

§B from TG-M1 must still hold: both bots created with privacy disabled **before** the first group add,
the development group with two extra accounts in it, the bot promoted to administrator there, and the
development token in `.env`.

Everything below except §4 works with **no** token and **no** network. The smoke test is the only part
that needs a real group.

---

## 1. Migrate

```bash
make up
make migrate                      # 0003 → 0004_moderation_actors
make psql
  \d telegram_messages
  \d moderator_group_assignments
  \di uq_assignment_one_current_primary
```

Four new tables, no altered ones, and no `GRANT` — the panel's role already reaches anything the
migrator creates (research probe 9).

Roll it back and forward once, because the reverse is part of the contract:

```bash
make migrate-down && make migrate
```

---

## 2. Mark the group measured, and map yourself

Open <http://localhost:8080/admin>. Two things are new: a **Moderation Intelligence** navigation group
with **Telegram Groups** and **Moderators**, and Model Profiles has moved under **Platform**.

1. **Telegram Groups** → your development group is already there, discovered by TG-M1. Check the
   columns: bot standing should read `administrator`; if it reads anything else, several event kinds are
   not reaching you and the rest of this walkthrough will be misleading. Fix that in Telegram first.
2. Switch **measured** on. Nothing else happens — deliberately. No job starts. Events from **now**
   onward will become messages; §5 covers catching up on earlier ones.
3. **Moderators** → add yourself: a display name of your own choosing (it is stable and independent of
   your Telegram profile) and your numeric id. Add the two test accounts as *non*-moderators by simply
   not creating records for them.
4. On your moderator record, open **Assignments** and assign yourself as **primary** of the development
   group, with a `valid_from` of now.

Confirm the group no longer shows as unassigned.

---

## 3. Hand over ownership, and check that history holds

This is the milestone's actual claim, and it is worth two minutes.

1. Add a second moderator (one of your test accounts).
2. On the group, use **Reassign** to hand primary ownership to them.
3. In `make psql`:

```sql
SELECT moderator_id, valid_from, valid_to
  FROM moderator_group_assignments
 WHERE assignment_role='primary' ORDER BY valid_from;
```

**The incumbent's `valid_to` and the successor's `valid_from` must be the identical value.** If they
differ — even by microseconds — there is a hole in ownership history that no constraint will catch and
that later reports will render as "Unassigned" (research Finding 2). That identity is the check.

4. Ask who was responsible at an instant *before* the handover:

```sql
SELECT moderator_id FROM moderator_group_assignments
 WHERE telegram_chat_id = :chat AND assignment_role='primary'
   AND valid_from <= :t AND (valid_to IS NULL OR valid_to > :t);
```

It must return **you**, not the new owner. Reassign again and ask the same question with the same `:t`:
the answer must not move. That is the whole contract.

---

## 4. Smoke test

From the runbook: *"Mark the dev group monitored, map yourself as moderator, post as both identities,
confirm `is_from_moderator`."*

```
in the development group:
  post as a test account      →  "الكتاب مش ظاهر عندي"
  post as yourself             →  "تم حل المشكلة"
```

```bash
make psql
  SELECT message_id, sent_at, is_from_moderator, media_kind,
         left(original_text, 30) AS raw, left(normalized_text, 30) AS norm
    FROM telegram_messages ORDER BY sent_at DESC LIMIT 5;
```

Expected: two rows. The test account's row `is_from_moderator = f`, yours `= t`. `sent_at` is Telegram's
own timestamp, not when derivation ran. `normalized_text` has the tashkeel and tatweel stripped and the
alef forms folded; `original_text` is byte-identical to what you typed.

Then three quick negatives, each of which is a guarantee rather than a nicety:

| Do this | Expect |
|---|---|
| Reply to the test account's message, then check `reply_to_message_id` | It holds Telegram's own message id — no foreign key, so a reply to something from before measurement also works |
| Edit your message in Telegram | `original_text` and `normalized_text` change, `edited_at` is set, **`sent_at` does not move**, `is_from_moderator` does not change |
| Map the *test account* as a moderator now, and re-check its earlier message | `is_from_moderator` is **still `f`**. The flag was written once and is never recomputed |

That last one is the milestone. A transcript now shows the same person flagged both ways, which looks
inconsistent and is the correct record — see §7.

---

## 5. Catching a group up on events captured before you switched it on

TG-M1 stored events for the group before it was measured. One command brings them in:

```bash
docker compose -f infra/docker-compose.yml exec ai-worker \
  python -m app.scripts.rederive_chat --chat <chat_id> --since 2026-09-01
```

It reports three numbers — examined, derived, skipped — and is safe to run twice: the second run derives
nothing. It refuses a group that is not measured, and it counts an event whose payload has already been
purged as skipped rather than making a hollow row.

**Read §7's second bullet before running it over a range that spans a moderator mapping change.**

---

## 6. Verify

```bash
make check                        # must pass with Ollama quit and no token set
TELEGRAM_BOT_TOKEN= make check    # proves nothing here needs the credential
```

`make check` also runs the boundary gate. Note that its no-message-text rule (check 4) greps for a
logging call on a line that also mentions `original_text` or `normalized_text` — this is the first
milestone that handles those columns heavily, so expect that rule to earn its place.

---

## 7. Known limitations

Stated here so none is rediscovered as a surprise.

- **A transcript spanning a promotion shows the same person flagged both ways.** The moderator flag is
  a snapshot at the message's insert. It looks wrong and is right: a live lookup would silently convert
  last month's student questions into last month's moderator answers, flattering every historical
  number.
- **Re-derivation resolves that flag as of the moment it runs.** `moderators` carries no interval, so
  "was X a moderator on 3 August" is not answerable — the flag *is* the record. For a range spanning a
  mapping change, a re-derive writes flags live derivation would not have. Already-derived messages are
  never touched, so the effect is bounded to rows that had no flag at all.
- **Pre-edit text lives only in the captured event.** There is no text-version table. Once
  `telegram_updates.payload` is purged for that event, the pre-edit text is gone; the post-edit text and
  every timestamp survive.
- **Only the *current* primary owner is constrained.** A backdated correction that overlaps a closed
  interval is caught by a test, not by the database — the stricter constraint needs an extension enabled
  at database creation on an already-shipped database.
- **Assigning and reassigning at the same instant is refused.** A zero-width interval covers no instant,
  so it would be an ownership record that exists and is invisible.
- **The panel is entirely left-to-right; only the Arabic content fields are direction-aware.** Filament
  sets direction once on the document root from the application locale, so "RTL for this navigation
  group only" is not something the framework can do (research Finding 1). Arabic titles and names read
  correctly; the chrome around them is English.
- **Anonymous administrators and channel posts are never flagged as a moderator's.** Telegram withholds
  who acted, and the database refuses the flag without a personal sender.
- **Nothing is judged.** No question is recognised, no item opened, no response matched, no duration
  computed, no model called. Those are TG-M3 onwards.
- **Nothing is purged.** The removal markers exist on names and text; the job is TG-M10.
- **A supergroup promotion now carries measurement forward** — it did not before this milestone
  (research Finding 3). If the surviving group already has a current primary owner, the re-point refuses
  and surfaces the conflict rather than picking a winner; resolve it in the Assignments view.

---

## 8. Next

TG-M3 — the first usable slice. A student question opens an attention item, a moderator reply closes it,
and the panel shows a correct first-response time attributed to the moderator responsible **at that
time**. It needs one decision from you that this milestone deliberately did not pre-empt: **which group
is the pilot, and who is its moderator** (runbook §A.2, open question 5).
