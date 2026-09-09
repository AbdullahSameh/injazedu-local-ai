# Runbook: Telegram Moderation Intelligence — operator prerequisites

**Audience**: the operator, on this MacBook. This is the checklist you work through *before and
alongside* the Telegram Moderation Intelligence milestones. The design it serves is
[`docs/plan/telegram/telegram-moderation-intelligence.md`](../plan/telegram/telegram-moderation-intelligence.md);
this file is only the human steps.

Builds on [`m0-foundation.md`](m0-foundation.md) and [`m1-model-gateway.md`](m1-model-gateway.md) —
`make up`, `make doctor` and the model gateway still apply unchanged.

---

## Two facts that drive every step below

1. **One bot token has exactly one update consumer.** `getUpdates` and a webhook are mutually
   exclusive, and two simultaneous pollers on one token get
   `409 Conflict: terminated by other getUpdates request` and drop updates on both sides.
   → **You need two bots: one dev, one live.** This is not tidiness, it is correctness.
2. **Telegram keeps undelivered updates for at most 24 hours and offers no history API.** A poller
   that is off longer than that loses those messages permanently, and a gap looks identical to
   "the moderator was fast".
   → **Where the live poller runs is a decision, not a detail** (§C, TG-M3 row).

---

## A. Before TG-M0 — one sitting, no Telegram involved

### A.1 Stack prerequisites

```bash
make doctor        # must be green before anything starts
```

It will flag the one real outstanding item carried forward from M0/M1: **the four Ollama launch
variables are still unset**. They are not needed until TG-M5, but set them now:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_FLASH_ATTENTION 1
# then quit Ollama from the menu bar and relaunch — it reads these only at launch
make doctor        # should now print "All four are set for the next Ollama launch."
```

No model needs pulling: TG-M5 uses `gemma4:e2b-it-qat`, which is already installed and is the
active `llm` profile.

### A.2 Seven decisions

These are the plan's §28 open questions. The first four block a specific milestone; make them now
so nothing stalls mid-implementation.

| Decide | Needed by | What it blocks if undecided |
|---|---|---|
| Which Telegram group is the **pilot**, and who is its moderator | TG-M3 | The first vertical slice has no subject |
| Does a **private moderators' group** exist, or do you create one | TG-M6 | It is the alert destination chat id |
| **Quiet hours** — any window where no alert should fire | TG-M6 | Decides whether overnight items count as unanswered |
| **Alert language** — Arabic only, or bilingual | TG-M6 | Message templates |
| Grant the bot `can_delete_messages`? | TG-M1 | v1 never deletes; granting now avoids re-promoting later |
| **Tell the moderation team what is measured** | before the pilot | The "assistance, not surveillance" framing only works if it is said out loud |
| Pull `pg_dump` encryption forward? | later | This domain adds student PII to the database |

---

## B. Creating the Telegram bots

**When:** create **both bots at TG-M1**. Only add the live one to real groups at the TG-M3 pilot.
BotFather setup is fiddly enough that doing it once, properly, beats rushing it later.

### B.1 BotFather — order matters

```
/newbot
  name:     InjazEdu Moderation (Dev)
  username: InjazModerationDevBot
  → save the token

/setprivacy    → select the bot → Disable      ← DO THIS BEFORE ADDING IT ANYWHERE
/setjoingroups → Enable                         (default — confirm it)
/setdescription, /setuserpic                    optional
```

> **Why privacy first.** A bot that is a group **administrator** receives all messages regardless of
> the privacy setting, so admin status alone is technically sufficient. But a privacy-mode change
> only takes effect after the bot is **re-added** to every group it is already in. Disabling it
> before the first group add means you never have to re-add anything later. Two clicks now versus
> re-adding the bot to every student group.

Repeat for the live bot: `InjazEdu Moderation` / `InjazModerationBot`.

### B.2 The dev group

1. Create a throwaway group.
2. Put **two accounts in it besides you** — one to play "student", one to play a second moderator.
   You need a third identity you are willing to ban when TG-M4 tests enforcement.
3. Add the bot to the group.
4. **Promote it to administrator.** The plan needs admin *status*, not any particular right — you
   can leave every toggle off. If a client insists on at least one, `can_delete_messages` is the
   one decision A.2 already covers.

### B.3 Getting the numeric `chat_id`

It is negative, and it is what every table keys on.

```bash
curl -s "https://api.telegram.org/bot<DEV_TOKEN>/getUpdates" | python3 -m json.tool | grep -A3 '"chat"'
```

After TG-M1 ships you will not need this — the group appears in `telegram_chats` automatically from
the `my_chat_member` update fired when you added the bot.

### B.4 Token handling

```
.env             TELEGRAM_BOT_TOKEN=<dev token>     # gitignored, this machine
live host .env   TELEGRAM_BOT_TOKEN=<live token>    # never both on one machine
```

Never in a spec, a commit, or a database column. TG-M0 adds the token's shape to
`scripts/scan_secrets.sh`.

**Before the live poller ever starts, stop the dev poller.** Otherwise both get `409`.

---

## C. What you do at each milestone

| Milestone | Before the agent starts | At the smoke test |
|---|---|---|
| **TG-M0** | §A done: Ollama variables set, seven decisions made | Confirm `make check` passes with **no token set** |
| **TG-M1** | §B done: both bots created, dev group live, bot admin, dev token in `.env` | Post in the dev group → raw row visible via `make psql`. Stop the container 5 min, restart, watch the backlog drain |
| **TG-M2** | Collect your own Telegram user id and the two test accounts' ids | Mark the dev group monitored, map yourself as moderator, post as both identities, confirm `is_from_moderator` |
| **TG-M3** 🎯 | **Name the pilot group and its moderator.** Add the *live* bot to it as admin; live token on the machine that will run it | Post a question, reply 8 minutes later, confirm the dashboard says 8m and attributes it to the moderator assigned **at that time**. Then change the assignment and confirm the number does *not* move |
| **TG-M4** | Have a disposable third account in the dev group you are willing to ban | Open an incident, react ✅ → ACKNOWLEDGED, restrict the account → RESOLVED with your name |
| **TG-M5** | Ollama running. Write down 5–10 real Arabic messages whose correct label you already know | `make smoke-moderation` classifies your fixtures correctly |
| **TG-M6** | **Create the private moderators' group**, add the bot as admin, record its chat id. Agree thresholds and quiet hours with management | Set "question waiting > 2 min", leave one unanswered → **one** alert (not two), press ✅ Handled, incident resolves. **Then read the student group and confirm the bot posted nothing** |
| **TG-M7** | Nothing | Check a week's numbers against a hand-computed spreadsheet |
| **TG-M8** | Budget an hour reviewing real classifications | Correct a wrong label; confirm the original prediction, model and confidence are still visible |
| **TG-M9** | Generate an `N8N_ENCRYPTION_KEY` | `make automation-up`, import the workflow, trigger the digest manually |
| **TG-M10** | Confirm the retention window (the plan says 90 days) | Backdate a message, run the purge, confirm text is gone and the metric row is intact |

---

## D. The one thing to settle before the TG-M3 pilot

Decide where the **live poller** runs. A sleeping laptop over a weekend permanently loses that
window (fact 2 above), and the resulting gap is indistinguishable from good performance.

Pick one:

1. **`caffeinate -s`** the machine and keep it awake and plugged in — fine for a two-week pilot.
2. **Move only the `ai-telegram` container to an always-on host** — it needs Postgres and Redis, not
   Ollama, because it makes no model calls. This is the answer before anyone acts on the numbers.
3. **Accept nightly gaps explicitly** and set `alert_rules.quiet_hours` to match, so overnight items
   are not counted as unanswered.

---

## E. Go-live checklist

Nothing here is architectural. No DNS record, no TLS certificate, no `setWebhook` call, no firewall
change — going live is a token, a host, and a set of `is_monitored` flags.

```
[ ] live bot created; added as ADMIN to every group to be monitored
[ ] make tg-doctor  → getMe ok · webhook NOT set · allowed_updates correct
                      · bot is administrator in every chat · no unassigned monitored chat
[ ] live TELEGRAM_BOT_TOKEN on the live host only; dev token never there
[ ] dev poller STOPPED before the live poller starts        ← otherwise both get 409
[ ] telegram_chats.is_monitored enabled per group, deliberately, one at a time
[ ] moderators mapped and assignments opened with a real valid_from
[ ] alert destination = the private moderators' group; verify no rule resolves to a student chat
[ ] alert thresholds reviewed with management (they are data, not code)
[ ] MODERATION_TEXT_RETENTION_DAYS confirmed; purge job scheduled
[ ] host stays awake / always-on decision made (§D)
[ ] the moderation team has been told what is measured
[ ] one full smoke pass in the live pilot group before enabling the rest
```

---

## F. What this system will never tell you

Stated here so it is not rediscovered as a surprise mid-pilot. The Telegram Bot API exposes:

- **no update when a message is deleted in a group**, and **no way to learn who deleted it** — the
  admin log is an MTProto feature a bot cannot read;
- **no history API**, so nothing before the bot joined, and nothing during a gap longer than 24
  hours, can ever be recovered.

The design measures what is actually observable — replies, reactions, bans and restrictions, each
with an attributable actor and a timestamp — and labels absences as absences.
