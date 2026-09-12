# Quickstart: TG-M1 — Telegram Event Ingestion

**Audience**: the operator, on this MacBook. What to do before, during and after TG-M1, what "working"
looks like, and what this milestone will never be able to tell you.

Prerequisites: [`docs/runbooks/tg-operator-prerequisites.md`](../../docs/runbooks/tg-operator-prerequisites.md)
§B (bot creation) in full, and §C's TG-M1 row. Everything from M0, M1 and TG-M0 still applies.

---

## 1. Before the agent starts

TG-M0 needed nothing from Telegram. **TG-M1 needs both bots created**, and the runbook is emphatic
that the order matters.

```
/newbot
  name:     InjazEdu Moderation (Dev)
  username: InjazModerationDevBot
  → save the token

/setprivacy    → select the bot → Disable      ← BEFORE adding it anywhere
/setjoingroups → Enable                        (default — confirm it)
```

**Why privacy first.** A privacy-mode change only takes effect after the bot is **re-added** to every
group it is already in. Two clicks now versus re-adding the bot to every student group later.

Then the dev group: create a throwaway group, put **two other accounts** in it (one to play
"student", one a second moderator — you will want a third identity you are willing to ban at TG-M4),
add the bot, and **promote it to administrator**. The plan needs admin *status*, not any particular
right; every toggle may stay off.

Repeat for the live bot (`InjazEdu Moderation` / `InjazModerationBot`) but **do not add it to any real
group** — that is TG-M3.

```bash
# .env, this machine only. Never both tokens on one machine.
TELEGRAM_BOT_TOKEN=<dev token>
```

> **One token has exactly one consumer.** Two pollers on one token both get
> `409 Conflict` and drop updates on both sides. Stop the dev poller before a live poller ever starts.

---

## 2. Bringing it up

```bash
make doctor && make up && make migrate     # 0003 creates the four tables
make health | python3 -m json.tool         # telegram_ingestion block present
make tg-doctor                             # the setup check
```

`make tg-doctor` is the new command, and it is the one to run when something looks wrong:

```
Telegram ingestion diagnostics
  credential            present (dev)
  getMe                 ok — @InjazModerationDevBot (id 8123456789)
  webhook               NOT set                              ← required
  allowed_updates       matches configuration (6 kinds)
  chats
    تجريبي — dev                  administrator   can_delete=no    monitored
  ingestion             last event 12s ago · 0 pending · 0 open gaps · not stood down
```

**With no credential at all it exits 0 and says so.** That is a supported state, not a failure — it
is what lets `make check` pass on a machine that holds no credential.

---

## 3. The smoke test — the runbook's TG-M1 row

Two parts. The first proves capture; the second proves recovery, and it is the one worth doing
properly.

**Part 1 — an event lands.**

```bash
# Post any message in the dev group, then:
make psql
```
```sql
select id, update_id, update_type, chat_id, received_at, processed_at
  from telegram_updates order by update_id desc limit 5;

-- the group discovered itself, with no id copied by hand:
select chat_id, title, chat_type, bot_status, bot_can_delete, is_monitored, last_event_at
  from telegram_chats;
```

Expect a row within seconds, `processed_at` set shortly after (the interpreting stub), and a
`telegram_chats` row created from the `my_chat_member` update fired when you added the bot.

**Note `is_monitored` is `false`.** That is deliberate — being measured is always a deliberate act,
and TG-M1 ships no screen for it. For the rest of the smoke test:

```sql
update telegram_chats set is_monitored = true where chat_id = <your dev group id>;
```

**Part 2 — stop it for five minutes, and watch the backlog drain.**

```bash
docker compose -f infra/docker-compose.yml stop ai-telegram
# post 3–4 messages in the dev group while it is down, wait past 5 minutes
docker compose -f infra/docker-compose.yml start ai-telegram
```
```sql
-- every message posted during the outage is here:
select update_id, update_type, received_at from telegram_updates order by update_id desc limit 10;

-- and the window is recorded honestly:
select gap_start_at, gap_end_at, reason, unrecoverable, note from ingestion_gaps order by id desc;
```

Expect exactly **one** gap row, `reason = 'downtime'`, `unrecoverable = false`. A shorter pause — say
thirty seconds — must produce **no** row at all; the five-minute minimum exists so ordinary restarts
do not fill the table with noise that would make the marker meaningless.

---

## 4. What healthy looks like

```bash
make health | python3 -m json.tool
```
```json
"telegram_ingestion": {
  "status": "ok", "required": false,
  "ingestion": {
    "credential": "configured", "bot_identity": "resolved",
    "last_update_at": "2026-09-09T13:04:11Z", "seconds_since_last_poll": 12,
    "pending_updates": 0, "consecutive_failures": 0, "stood_down": false,
    "monitored_chats": 1, "chats_silent_over_6h": 0, "open_gaps": 0,
    "bot_not_admin_in": []
  }
}
```

`"required": false` — a deliberately stopped bot never makes the system look unready.

**The field to watch is `bot_not_admin_in`.** A bot demoted without being removed keeps receiving
ordinary messages while `chat_member` and `message_reaction` **silently stop arriving**, with no error
anywhere. It is the failure most likely to go unnoticed, which is why it gets its own field rather
than a log line.

---

## 5. Known limitations — read these before the TG-M3 pilot

**Inherited from Telegram, permanent:**

- **No update is emitted when a message is deleted in a group**, and no way exists to learn who
  deleted it. Not a gap to be closed later.
- **No history API.** Nothing before the bot joined, ever.
- **Undelivered updates are kept at most 24 hours.** A poller off longer than that loses that window
  permanently. On a dev group that is fine. On a real student group, **a gap looks identical to "the
  moderator was fast"** — which is why runbook §D asks you to decide where the live poller runs
  *before* the pilot, not after.

**Introduced by this design, deliberately:**

- ⚠ **After a full week with no updates at all, Telegram picks a random next update identifier**,
  which may be *lower* than the last one stored. The poller detects the stall and re-syncs by asking
  without an offset, then records `reason = 'update_id_reset'`. **That row is not a data loss** —
  nothing went missing, Telegram simply renumbered — and reports overlapping it are not marked
  incomplete. Without this handling the poller would go silent forever while every health signal
  stayed green.
- ⚠ **A recycled identifier after such a reset is silently dropped.** If a randomly chosen identifier
  collides with one already stored, that event is lost. Accepted deliberately (research D-TG-34); it
  needs a week of total silence *and* an unlucky landing. Every reset writes a gap row so you can see
  when the exposure began.
- **Stored payloads are semantically complete, not byte-identical.** JSONB does not preserve key
  order and collapses duplicate keys. Nothing here needs byte fidelity, but "verbatim" in the spec
  means "nothing meaningful lost", not "the same bytes".
- **A group is not measured until you say so.** `is_monitored` defaults to false and TG-M1 has no
  screen; updates for unmeasured groups are still stored, so opting a group in works retroactively
  within the retention window.

**Not built yet, by design:** no message parsing, no senders, no moderators, no attention items, no
incidents, no alerts, no dashboard, no model call. The bot sends nothing and the machine opens no
inbound port.

---

## 6. Reproducing the plan's probes

Every measured claim in `research.md` can be re-run. These need only the running stack.

```bash
# Probe 1 — the idempotency mechanism: RETURNING yields only new rows
make psql
```
```sql
create temp table p (bot_id bigint, update_id bigint, constraint u unique (bot_id, update_id));
insert into p values (1,100) returning update_id;                                  -- 100
insert into p values (1,100) on conflict do nothing returning update_id;           -- 0 rows
insert into p values (1,100),(1,101),(1,102) on conflict do nothing
  returning update_id;                                                             -- 101, 102 only
-- Probe 2b — JSONB is semantically complete, not byte-identical
select '{"b":1,"a":2}'::jsonb, '{"a":1,"a":2}'::jsonb;   -- {"a":2,"b":1} | {"a":2}
```

```bash
# Probe 3 — confirms the fix for the health model's silent-drop bug still holds
cd apps/ai-api && uv run python -c "
from app.application.health_service import ComponentReport, ComponentState
print(ComponentReport(status=ComponentState.OK, required=False, ingestion={'x':1}).model_dump())"
# → the 'ingestion' key IS present now (T067 made it a declared field, D-TG-32).
#   Before that fix, ComponentReport(..., ingestion={...}) raised nothing and the key
#   vanished — accepted and silently dropped, because the model is frozen=True but not
#   extra="forbid". If this ever prints without 'ingestion' again, the fix regressed.
```

```bash
# Probe 4 — the natural probe placement fails the boundary gate
# (the import must be used, or ruff's unused-import check aborts the gate before this
# probe ever reaches the boundary check it's meant to demonstrate)
printf 'from app.infrastructure.models_moderation import telegram_updates\n\nprint(telegram_updates.name)\n' \
  > apps/ai-api/app/application/probes/telegram_ingestion.py
./scripts/check.sh            # fails at "moderation domain boundary", check 2
rm apps/ai-api/app/application/probes/telegram_ingestion.py
```

```bash
# Probes 6 and 7 — the two Bot API facts the design turns on
open "https://core.telegram.org/bots/api#getupdates"
#   limit:  "Values between 1-100 are accepted"
#   offset: "By default, updates starting with the earliest unconfirmed update are returned."
#           "The negative offset ... All previous updates will be forgotten."   ← never use it
open "https://core.telegram.org/bots/api#update"
#   "If there are no new updates for at least a week, then identifier of the next
#    update will be chosen randomly instead of sequentially."
```

---

## 7. Verifying the whole milestone

```bash
make check                                  # must pass offline, Ollama quit
TELEGRAM_BOT_TOKEN= make check              # proves capture is optional
make tg-doctor                              # getMe · webhook NOT set · allowed_updates · admin status
make health | python3 -m json.tool          # telegram_ingestion block, all fields populated
```

Then the migration round-trip, which Principle I requires because it transforms schema:

```bash
make migrate                                # up to 0003
make migrate-down                           # back to 0002, cleanly
make migrate
```

**Two things to confirm by eye in the change set**, because their absence is the guarantee:

1. No method anywhere sends a message, sets a reaction, deletes a message, bans or restricts.
2. The `ai-telegram` service declares **no `ports:` block**.

---

## 8. What to do when it stops working

| Symptom | Likely cause | Check |
|---|---|---|
| `stood_down: true` in the health block | Another consumer holds the same token — a live poller, or a second container | Stop one. `make tg-doctor`. Restart explicitly; stand-down does not clear itself |
| `bot_identity: "unreachable"` | No network, or Telegram is down | Nothing to do — it retries and recovers unattended |
| `bot_identity: "rejected"` | Token revoked or malformed | Re-check `.env` against BotFather |
| Messages posted, nothing stored | Bot not an administrator, or privacy mode never disabled | `make tg-doctor` — `bot_not_admin_in` |
| `pending_updates` climbing | The worker is down; capture is fine | `docker compose ps ai-worker`. Dramatiq redelivers once the worker is back; `ai-telegram` also re-runs `drain_pending_updates` on its own next restart, for anything that was never enqueued at all |
| Nothing for days, everything green | The identifier reset (§5). It self-heals past the stall window | `select * from ingestion_gaps where reason = 'update_id_reset'` |
| `make check` red with no credential | A regression in the optional-credential path | This is a bug — capture must be optional |
