# Contract: Environment — TG-M0 additions

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09
**Extends**: `specs/001-m0-foundation/contracts/environment.md` and
`specs/002-m1-model-gateway/contracts/environment.md`. Nothing in either is changed.

Five new variables. All optional, all defaulted, none required for `make up`, `make check` or
`/health`.

---

## 1. The variables

```bash
# --- Moderation Intelligence (TG-M0, all optional, all defaulted) ---
# The bot credential. ABSENT IS A SUPPORTED STATE: without it, ingestion does not run and
# nothing else changes. Never commit a real value — the secret scan fails on its shape.
TELEGRAM_BOT_TOKEN=

TELEGRAM_ALLOWED_UPDATES=message,edited_message,my_chat_member,chat_member,message_reaction,callback_query
MODERATION_BURST_GAP_S=90
MODERATION_ITEM_MAX_AGE_S=86400
MODERATION_TEXT_RETENTION_DAYS=90
```

| Variable | Type | Default | Validation | First read by |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | optional string | *(unset)* | **none in TG-M0** — carried, never validated | TG-M1 |
| `TELEGRAM_ALLOWED_UPDATES` | comma list | the six kinds above | non-empty | TG-M1 |
| `MODERATION_BURST_GAP_S` | int seconds | `90` | must be positive | TG-M3 |
| `MODERATION_ITEM_MAX_AGE_S` | int seconds | `86400` (24 h) | must be positive | TG-M3 |
| `MODERATION_TEXT_RETENTION_DAYS` | int days | `90` | must be positive | TG-M10 |

Every value comes from the source plan (§25 TG-M0, §19.2, D-TG-11). None is a judgement call made
here.

---

## 2. The credential's absence is a supported state, not a degraded one

With `TELEGRAM_BOT_TOKEN` unset **or** set to the empty string:

- the API and worker start normally;
- `/health` and `/health/live` are unchanged — no moderation component exists yet, and TG-M1's will
  be `REQUIRED = false` when it arrives;
- `make check` passes in full, offline, with no model runtime;
- nothing in TG-M0 reads the value at all.

Two operational reasons this matters, both from the runbook:

1. **One credential has exactly one update consumer.** Two pollers on one token get
   `409 Conflict: terminated by other getUpdates request` and *both* drop updates. The runbook
   therefore requires two bots — one dev, one live — and requires that the live credential exist only
   on the machine running the live poller. A machine with no credential must be a first-class,
   fully-working state.
2. **`make check` must never need one.** The gate runs on machines that must not hold a live
   credential.

The field is typed `str | None` with default `None`, not `str` with default `""`, so "not configured"
and "configured empty" are one state.

---

## 3. Validation

Each duration gets a `@model_validator(mode="after")` in the shape M1 already uses, raising a
`ValueError` naming the variable and the value. `load_settings()` prints
`Configuration error: <FIELD>: <msg>` to stderr and exits 1 — no stack trace, unchanged mechanism.

```
$ MODERATION_TEXT_RETENTION_DAYS=0 make check
Configuration error: moderation_text_retention_days: MODERATION_TEXT_RETENTION_DAYS must be positive (got 0)
```

**These are data-safety checks, not config hygiene.** `MODERATION_TEXT_RETENTION_DAYS=0` reaching
TG-M10's `purge_expired_text` actor would null every message text on its first run.
`MODERATION_BURST_GAP_S=0` would make every message its own burst, silently inflating the
attention-item count TG-M3 measures. Both are typos that produce plausible-looking output rather than
an error — the class of failure a startup check exists for.

---

## 4. What TG-M0 does *not* add

- **No `TELEGRAM_ENABLED` flag.** The credential's presence already expresses it; a second setting
  would create a state where the flag is on and the credential is missing.
- **No credential shape validation.** TG-M1's `make tg-doctor` owns that (D-TG-27). Putting the regex
  into application code would create a second place the shape is defined and a candidate for it
  appearing in an error message.
- **No alert, threshold, quiet-hours or destination settings.** TG-M6 — and the source plan is
  explicit that thresholds are *data*, not configuration: they live in `alert_rules` rows so
  management can change them without a deploy.
- **No confidence floor or taxonomy version.** TG-M5.
- **No n8n variables.** TG-M9. The `n8n` service remains the unconfigured stub M0 left.

---

## 5. Operator checklist for this milestone

From `docs/runbooks/tg-operator-prerequisites.md` §C, TG-M0 row:

```
[ ] make doctor is green
[ ] the four Ollama launch variables are set (not needed until TG-M5, but set them now)
[ ] the seven §A.2 decisions are made — none blocks TG-M0, four block TG-M3/TG-M6
[ ] make check passes with NO TELEGRAM_BOT_TOKEN set     ← the milestone's smoke test
```

**No bot is created in TG-M0.** BotFather work is §B of the runbook and belongs to TG-M1; the live
bot joins a real group only at the TG-M3 pilot.
