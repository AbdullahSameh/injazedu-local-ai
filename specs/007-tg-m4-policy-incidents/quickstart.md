# Quickstart: TG-M4 — Policy Incidents

**Audience**: the operator. The design is in `plan.md`, `data-model.md` and `contracts/`; this is the
walkthrough and the smoke test. Runbook: `docs/runbooks/tg-operator-prerequisites.md` §B.2, §C (TG-M4
row), §F.

---

## 1. What you get

- **Open incident** on any stored message — from **Moderation Intelligence → Incidents**, or from a row
  of the **Live Attention Queue**. You choose a category (spam/advert, abuse, other) and a severity (low,
  medium, high).
- Moderators' **reactions**, **direct replies**, and the platform's **ban / expel / restrict** reports
  become evidence automatically. You never type evidence in; you only confirm what Telegram cannot see.
- On each incident: its status, its evidence trail, the three timings, the outcome, and the standing
  sentence that Telegram does not report deletion.
- Three panel acts: **Acknowledge**, **Resolve** (with a note), **Not a violation** (with a reason).
- Per-group and per-moderator figures beneath the list.

Nothing here posts, bans, deletes or reacts. The bot stays silent.

---

## 2. Before you start

| Need | Where | Why |
|---|---|---|
| A **disposable third account** in the **dev** group, one you are willing to restrict and ban | runbook §B.2, §C TG-M4 row | the smoke test enforces against it |
| **Your own account mapped as a moderator** of the dev group | TG-M2's smoke step — already done (1 moderator in dev) | your ✅ and your restriction must be *a moderator's* |
| The **dev bot an administrator** in the dev group | `make tg-doctor` | membership changes and reactions are only delivered to an administrator — silently otherwise |
| The **dev** poller running — which on one machine means the live pilot's poller is **not** (runbook §B.4) | your call | one token, one consumer; never both tokens on one host |
| Two lines in `.env` | below | research Finding 2 |

```bash
# .env — add both (the first is missing today, which is why the queue's p90 floor currently reads 0)
MODERATION_PERCENTILE_MIN_SAMPLES=10
MODERATION_INCIDENT_MAX_AGE_S=86400
```

---

## 3. Migrate and restart

```bash
make migrate                 # applies 0006_moderation_incidents
make up                      # recreates ai-control / ai-worker with the new settings
make tg-doctor               # bot is administrator in the dev group; chat_member + message_reaction subscribed
```

---

## 4. First, prove the evidence arrives

Nothing like it has ever been captured here (research Finding 4) — confirm it before judging anything
downstream. In the dev group: react to any message **as yourself**, then restrict the disposable account
for one minute and lift it.

```sql
-- make psql
SELECT update_type, count(*) FROM telegram_updates
 WHERE update_type IN ('chat_member','message_reaction') GROUP BY 1;
-- expect ≥ 1 of each

SELECT action_type, action_strength, occurred_at, actor_moderator_id IS NOT NULL AS by_moderator,
       actor_is_anonymous, detail
  FROM moderation_actions ORDER BY id DESC LIMIT 5;
-- expect: reaction/acknowledgement by_moderator=t · restriction/enforcement · reversal/(null)
```

If the counts are zero: the bot is not an administrator, or the subscription is wrong — `make tg-doctor`
says which. Do not continue until both kinds land.

---

## 5. The smoke test — runbook §C, as written

1. As the disposable account, post something in the dev group — e.g. a fake advert.
2. **Incidents → Open incident**: pick that message, category *SPAM_OR_AD*, severity *medium*. Note the
   time. → status **open**, posted and flagged both shown, responsible = the dev group's owner.
3. As yourself, react **✅** to the advert. → within a few seconds, status **acknowledged**, "first
   acknowledgement" = your reaction's time, actor = you. **Not resolved.**
4. Restrict the disposable account. → status **resolved**, resolution = *Restricted*, performed by **your
   name**, and **observed-enforcement time** = restriction time − flag time.
5. Check that number by hand:

```sql
SELECT i.id, i.opened_at, i.detected_at, s.status,
       s.first_acknowledgement_at, s.first_enforcement_at,
       extract(epoch FROM s.first_enforcement_at - i.detected_at) AS enforcement_s,
       s.resolution_kind, s.resolved_by_moderator_id
  FROM moderation_incidents i JOIN moderation_incident_state s ON s.incident_id = i.id
 ORDER BY i.id DESC LIMIT 3;
```

The screen's enforcement time must equal `enforcement_s` exactly.

### Worth trying while you are there

| Do | Expect |
|---|---|
| Ten more ✅ and a direct reply on an acknowledged incident | Still **acknowledged**. Seeing is not acting |
| A moderator's plain message that replies to nothing | Nothing changes |
| The disposable account reacts to its own advert | Nothing changes |
| Ban the account **before** you flag its next message, then open the incident | Opens **resolved**; enforcement shows **"acted before flagging"**, never a negative time |
| Ban once when it has two open incidents | **Both** resolve |
| Unban it afterwards | Listed as *Unban / restriction lifted — no effect*; still resolved |
| **Resolve** an incident with a note ("moderator says she deleted it") | Resolved **by confirmation**, shown as your statement — nothing claims Telegram saw it |
| **Not a violation** on an acknowledged incident | Closed as a false positive; leaves every handled/missed figure |
| Try any action on a resolved or closed incident | None is offered |
| Leave one open past the ceiling (set `MODERATION_INCIDENT_MAX_AGE_S=120` for the test) | Counted **missed**; resolve it afterwards → state *resolved*, outcome **still missed** |

**Then read the dev group: the bot posted nothing, and did nothing.**

---

## 6. Re-deriving evidence

Ordinary derivation starts from this milestone. To backfill a group from events already captured:

```bash
docker compose -f infra/docker-compose.yml exec ai-worker \
  python -m app.scripts.rederive_chat --chat <chat_id> --with-evidence [--since 2026-09-01] [--until …]
# examined=… derived=… skipped=…
# evidence: recorded=<n> incidents_changed=<n>
```

Running it twice records nothing the second time. It never opens, edits or closes an incident. In dev
today it will find nothing — no such event had been captured before this milestone.

---

## 7. Verify

```bash
make check      # ruff, mypy, pytest, the PHP feature suite, the secret scan
```

Passes offline, with Ollama quit and **no Telegram token set**.

---

## 8. Known limitations

1. **A silent deletion is invisible.** Telegram reports none, and never who did it. A moderator who
   deletes spam instantly and says nothing leaves the incident open until you **Resolve** it on their
   word — or it is counted missed. This is the certain attribution gap of source plan §27, stated rather
   than hidden.
2. **No evidence arrives from a group where the bot is not an administrator** — silently. The incident
   page says so when it is true *now*; it cannot say whether it was true at the time.
3. **Anonymous administrators are recognised by the platform's anonymous-administrator account.** The
   Bot API reference does not document the performer of a membership change made anonymously; this is
   unverified live. An anonymous ban still resolves the incident and credits nobody.
4. **Messages sent as a channel or as the group** can only be resolved by confirmation — the platform
   reports no membership change for a banned sender chat. (They are also only *stored* from this
   milestone on: see `plan.md` ⚠ Item 2.)
5. **Only a direct reply acknowledges.** A moderator who answers the spammer in a plain message is not
   recorded as having seen it.
6. **Any moderator reaction acknowledges**, not only ✅. The emoji is kept, so this can be narrowed
   later without re-deriving.
7. **Enforcement resolves the incident whoever performed it**, including an anti-spam bot. The bot is
   shown as the performer and no moderator is credited.
8. **Responsible = the owner when the incident was flagged**, not when the message was posted — the
   counterpart of measuring the timings from the flag. A handover between posting and flagging moves the
   attribution to the new owner.
9. **A late resolution stays missed.** Handled means handled by the ceiling. The only thing that can
   change a settled outcome is evidence *dated* inside the window but *captured* late.
10. **A closure is judged against what was visible when you made it.** If a ban dated earlier is captured
    after you closed an incident as a false positive, the closure stands and the ban is listed.
11. **Labels cannot be edited.** A wrong flag is closed as a false positive; a mislabelled right flag
    waits for TG-M8's review.
12. **An unobserved window looks like inaction.** Evidence during a capture gap is never seen; the
    incident stays open. Rendering figures incomplete over a gap is TG-M7.
13. **No alert, no model, no outbound message.** TG-M5, TG-M6.

---

## 9. Next

TG-M5 — AI classification: incidents opened automatically with `source = 'ai'`, confidence routing, and
the model measured against this milestone's and TG-M3's human labels.
