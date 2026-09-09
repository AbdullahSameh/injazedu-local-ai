# Data Model: TG-M0 — Moderation Intelligence Domain Foundation

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09

## There is no schema change in this milestone

TG-M0 creates **zero tables, zero columns, zero indexes, zero Alembic revisions and zero Redis
keys**. Alembic revisions `0003`–`0009` are reserved for this domain by the source plan's §27 risk
row and remain **unconsumed** — the first is written by TG-M1.

This document therefore describes the three **value shapes** the milestone does introduce: the
settings object's new fields, the three forms of a message's text, and the closed set of log
correlation keys. They are the shapes later milestones will persist; writing them down now is what
lets TG-M1's `telegram_messages` columns be obvious rather than negotiated.

---

## 1. Settings — five new fields on the existing `Settings`

Added to `app/infrastructure/config.py`. All optional, all defaulted, all read from the environment
through the existing `pydantic-settings` mechanism. No new settings class (D-TG-26).

| Field | Env variable | Type | Default | Validation | First consumed by |
|---|---|---|---|---|---|
| `telegram_bot_token` | `TELEGRAM_BOT_TOKEN` | `str \| None` | `None` | **none** — carried, never validated here (D-TG-27) | TG-M1 |
| `telegram_allowed_updates` | `TELEGRAM_ALLOWED_UPDATES` | `str` | `message,edited_message,my_chat_member,chat_member,message_reaction,callback_query` | must be non-empty | TG-M1 |
| `moderation_burst_gap_s` | `MODERATION_BURST_GAP_S` | `int` | `90` | must be positive | TG-M3 |
| `moderation_item_max_age_s` | `MODERATION_ITEM_MAX_AGE_S` | `int` | `86400` | must be positive | TG-M3 |
| `moderation_text_retention_days` | `MODERATION_TEXT_RETENTION_DAYS` | `int` | `90` | must be positive | TG-M10 |

**`str | None`, not `str` with a `""` default.** This makes "not configured" and "configured empty"
the same state, so every later `if settings.telegram_bot_token:` reads correctly and the runbook's
requirement — that the live and development credentials never coexist on one machine — has one
unambiguous representation.

**Why the positivity checks are data-safety checks, not config hygiene.**
`MODERATION_TEXT_RETENTION_DAYS=0` reaching TG-M10's `purge_expired_text` actor would null every
message text on the first run. `MODERATION_BURST_GAP_S=0` would make every message its own burst,
silently inflating the attention-item count TG-M3 measures. Both are typos that produce plausible-
looking output rather than an error, which is exactly the class of failure a startup check exists for.

Validation follows the shape M1 already established — a `@model_validator(mode="after")` raising a
`ValueError` that names the variable and the offending value, so `load_settings()` prints
`Configuration error: <FIELD>: <msg>` and exits 1 with no stack trace. No new failure path.

**Absent-credential semantics** (FR-008): with `TELEGRAM_BOT_TOKEN` unset or empty the process starts
normally, `/health` is unchanged, and `make check` passes. Nothing in TG-M0 reads the value at all.

---

## 2. The three forms of a message's text

Not tables yet — TG-M1 and TG-M2 give the first two their columns. The **shapes** and the rules that
relate them are fixed here, because TG-M0 owns the transformations.

```
original_text ──normalize()──▶ normalized_text ──redact()──▶ redacted_text
   stored,                        stored,                      NEVER stored
   never modified                 matched against              transient, model-bound only
```

| Form | What it is | Lifetime | Who reads it |
|---|---|---|---|
| **`original_text`** | Exactly what the sender typed, byte for byte | Stored from TG-M1; nulled at the retention horizon (90 days) | Operators, in the panel, as evidence. Displayed, never matched |
| **`normalized_text`** | The matching form: NFKC-folded, bidi marks and tatweel and tashkeel removed, letter variants and digits folded, repeated **letters** and whitespace collapsed | Stored from TG-M1; nulled at the same horizon, alongside `original_text` | TG-M3's rule set; TG-M5's classifier, but only via `redacted_text` |
| **`redacted_text`** | `normalized_text` with URLs, emails, handles and long digit runs replaced by fixed Arabic placeholders | **Never persisted.** Computed at call time and discarded | TG-M5's classifier — and nothing else |

**`redacted_text` has no column, deliberately.** Persisting it would create a third copy of student
text on the same 90-day clock for no reader: it is derivable from `normalized_text` in microseconds,
and the one consumer needs it only for the duration of a model call. The gateway's `model_runs` row
stores a digest, not the payload, unless `GATEWAY_CAPTURE_PAYLOADS` is on — and because redaction
happens *before* the gateway, even then only redacted text can land there (D-TG-23).

### Invariants the implementation must hold

| # | Invariant | Verified by |
|---|---|---|
| N1 | `normalize(normalize(s)) == normalize(s)` for all `s` | SC-008 |
| N2 | `original_text` is unmodified by any call to `normalize` | SC-008 |
| N3 | Texts differing only by letter variant, diacritics, tatweel, elongation or digit script normalise identically | SC-007 |
| N4 | Emoji and Latin-script runs survive `normalize` intact | SC-009 |
| N5 | ⚠ Digit runs survive `normalize` unaltered — the collapse never touches them | SC-007, D-TG-21 |
| R1 | `redact(redact(s)) == redact(s)` for all `s` | SC-010 |
| R2 | `redact` is applied to normalised text, never to `original_text` | contract §3 |
| R3 | Text containing none of the four patterns is returned unchanged | SC-010 |
| R4 | No placeholder matches any of the four patterns, so no substitution nests | SC-010, D-TG-22 |

### Retention, for the record

Fixed here as configuration; enforced by TG-M10's purge. `original_text` and `normalized_text` are
nulled after `MODERATION_TEXT_RETENTION_DAYS`; the derived metrics, incidents and classifications
they produced are kept forever. The stated consequence, from the source plan's §19.2: **messages
older than the retention window can never be reclassified.** That is the accepted cost of not
keeping a permanent archive of students' payment problems.

---

## 3. Log correlation keys — a closed set of six

Added to `JsonFormatter` in `app/infrastructure/logging.py`. Emitted only when present and non-null;
every other `extra` key is dropped (D-TG-24).

| Key | Carries | Emitted from |
|---|---|---|
| `update_id` | The Telegram update's own identifier — the append-only spine's primary key | TG-M1 |
| `chat_id` | The numeric group id (negative for groups) | TG-M1 |
| `message_id` | The message within the chat | TG-M2 |
| `incident_id` | The moderation incident | TG-M4 |
| `alert_id` | The delivered alert | TG-M6 |
| `actor` | Who acted — a moderator reference, or the system | TG-M4, TG-M6 |

**`message_id`, not `message`.** Measured (research probe 8): stdlib `logging` raises
`KeyError: Attempt to overwrite 'message' in LogRecord` for `extra={"message": …}`, as it does for
`asctime`, `args`, `name` and `levelname`. All six keys above are accepted. The natural name was
never available, and the suffix is not a style choice.

**The set is closed, and that is the privacy mechanism.** Because the formatter reads only these six
names off the record, no future call site can attach message text through `extra=` — it has no path
to the output. The gate's grep (D-TG-28) covers the one remaining route, interpolation into the
message string itself.

**Existing output is unchanged**: the four keys `timestamp`, `level`, `logger`, `message` are emitted
exactly as before, `exc_info` behaviour is untouched, and every existing call site produces
byte-identical lines (FR-029).

---

## 4. What later milestones will add — for orientation only

Not built here. Listed so the reserved revision block reads as a plan rather than a gap.

| Revision | Milestone | Tables |
|---|---|---|
| `0003` | TG-M1 | `telegram_updates`, `ingestion_state`, `ingestion_gaps`, `telegram_chats` |
| `0004` | TG-M2 | `telegram_users`, `moderators`, `moderator_group_assignments`, `telegram_messages` |
| `0005` | TG-M3 | `attention_items` |
| `0006` | TG-M4 | `moderation_incidents`, `moderation_actions` |
| `0007` | TG-M5 | `message_classifications` (+ the `role='moderation'` CHECK widening on `model_profiles`) |
| `0008` | TG-M8 | `classification_reviews` |
| `0009` | TG-M6 | `alert_rules`, `alerts` |

TG-M0 consumes none of them.
