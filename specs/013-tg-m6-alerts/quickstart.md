# Quickstart: TG-M6 — Alerts

Every step is the operator's except where marked "agent". Git is the operator's throughout.

## §1 — Development: the alert group and the probes

1. Create a private Telegram group, "Moderators — dev". Make it a **supergroup** before adding anyone.
   Telegram does this when "Chat history for new members" is set to visible. This avoids V5's migration
   failure.
2. Add the development bot and one test moderator account. The bot needs no admin right there.
3. Run `make migrate`. Rebuild the `migrate` image first if it may be stale. Then restart `ai-worker` and
   `ai-telegram`.
4. Panel → Telegram Groups → the new group → **Use as alert destination**.

   **If Telegram promoted the group after the bot joined** (found 2026-11-17): Telegram Groups lists the
   group twice. The old basic-group row ("Group", bot "Member") is dead; the panel no longer offers it as
   the destination. The new supergroup row may show the bot as **Restricted**: Telegram restricts members
   carried over by the promotion, which the destination does not accept. Make the bot an administrator of the
   alert group with every right switched off (Group → Administrators → Add admin). Its row then reads
   "Administrator" and offers **Use as alert destination**.
5. Run `make tg-doctor`. It should report "alert destination: designated, bot can post, not monitored".
6. Run the probes (research §0b) and record the results in `research.md`:
   - **P1:** after 3 days, check that a dev alert can still be edited.
   - **P2:** check whether a URL button pointing at `http://localhost:8080` is accepted.
   - **P3:** press a button about 20 minutes after the alert, and note the answer error.
   - **P4:** with the group muted on the test phone, check that a mention still notifies.

## §2 — Development smoke (the master plan's)

1. Panel → Alert Rules → new rule: **Question waiting**, all groups, threshold 2 minutes, no repeats,
   enabled.
2. Post a question in the dev student group and leave it unanswered.
3. Within about 2.5 minutes the dev alert group shows **one** alert. Check six things:
   - the group title;
   - the excerpt, with any link shown as «رابط»;
   - the times;
   - "الفريق: …";
   - the message link;
   - 🙋 أتولّاه.
4. Wait two more ticks. There is still one alert.
5. Press 🙋 أتولّاه. The toast reads "تم: السؤال لك" and the alert reads "🙋 يتولّاه …". The queue shows the item
   as "… · via alert".
6. Answer the question in the student group. Within one tick the alert reads "✅ أُجيب عنه — …" and has no
   buttons.
7. Add a rule: **Incident flagged**, all groups, enabled. Flag a message from the panel. An alert arrives with
   ✅ and 🚫.
8. Press ✅ تمت المعالجة. The incident shows as resolved in the panel, "Resolved from the alert" by the
   moderator, and the alert reads "✅ عولجت — … · من التنبيه".
9. Press it again. The toast reads "انتهى هذا البند: …" and nothing new is recorded.
10. **Read the dev student group and confirm the bot posted nothing.**

## §3 — Agent checks

Run `make check`. It runs ruff, mypy, pytest (including `tests/moderation/alerts/` and the rewritten
`test_no_outbound.py`), the PHP feature tests and the secret scan.

## §4 — Production

1. Create the production "Moderators" supergroup with every moderator and the bot. Set "Chat history for
   new members" to visible **before** adding the bot; otherwise follow §1 step 4's recovery note.
2. Deploy. The migration is `0013`. Take a `pg_dump` first, as for every production write.
3. Set `MODERATION_PANEL_BASE_URL` in the production `.env`, and recreate `ai-worker` and `ai-telegram`.
4. Designate the group in the panel, then run `tg-doctor` the way `docs/runbooks/production-deployment.md`
   describes.
5. Agree the first rules with management, as data only. What each trigger and option means:
   `docs/runbooks/tg-alert-rules.md`. A suggested start, since the team works incidents today:
   - **Incident flagged**, all groups;
   - **Incident unhandled**, with a threshold you choose.

   Add question rules when the queue restarts.
6. Read every student group the next day and confirm the bot posted nothing.

## §5 — Rollback

- **Quietest:** disable every rule. Nothing fires, and pending alerts are never delivered once their subjects
  end.
- **Stop sending at once:** clear the destination with "Stop using". Every pending alert becomes `not_sent /
  no_destination`.
- **Code:** `scripts/prod/deploy.sh <previous sha>`. The `0013` downgrade refuses while button acts exist
  (data-model §6). The intent is that 0012's code can run on the 0013 schema:
  - the new tables are unread;
  - the state view's existing columns are unchanged;
  - the two appended columns are unused.

  **Checked 2026-11-15 (T549), by reading the panel at `79e7898`: no downgrade is needed first.** Nothing
  throws on an act kind or `assigned_via` it does not know:
  - `IncidentDisplay::kindLabel` falls back to the raw kind (`KIND_LABELS[$kind] ?? $kind`);
  - `strengthLabel` falls back the same way;
  - `TeamAssignment::viaLabel`'s `match` has `default => $via`;
  - every other `match` in that panel has a default.

  What the old panel shows instead:
  - the evidence trail and "Resolved by" read the raw `alert_handled` / `alert_false_positive`;
  - the Assigned column reads "… · alert";
  - a false-positive closure from the alert reads "by a panel account — —", because the old
    `correctedText` reads only `closed_by_user_id` and `close_reason`;
  - "My work"'s via split omits `via_alert`, so it no longer sums to "assigned";
  - switching on monitoring for the destination fails on `ck_chat_destination_not_monitored` as a
    database error, not a sentence;
  - the old panel has no Alert Rules, Alerts or destination screens. The old workers neither fire, send nor
    edit, so nothing reaches Telegram. Rules, alerts and the destination flag stay as data, and come back
    into force on a redeploy of 0013's code. Disable the rules first if they should not.
