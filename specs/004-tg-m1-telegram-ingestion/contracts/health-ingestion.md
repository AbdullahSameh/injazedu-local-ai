# Contract: The Ingestion Health Block and `make tg-doctor`

**Status**: the operator-facing surface of TG-M1. Two artifacts, one for "is it working right now",
one for "is it set up correctly".
**Owners**: `apps/ai-api/app/application/moderation/ingestion_probe.py`, `app/main.py` (composition),
`app/api/v1/health.py` (conditional wiring), `app/scripts/tg_doctor.py`.

---

## 0. ⚠ Why this block is composed at the composition root

The obvious placement — a fifth probe next to the other four in `app/application/probes/` — **fails
`make check`.** Measured (research probe 4), with the files planted exactly where the source plan's
§25 TG-M1 row puts them:

```
apps/ai-api/app/application/probes/telegram_ingestion.py:2:
    from app.infrastructure.models_moderation import telegram_updates
>>> CHECK 2 FAILS (reverse rule) <<<
```

That is TG-M0's boundary working correctly: `app/application/probes/` is assessment-side and may not
read moderation tables. Two escapes were rejected — an allowlist entry weakens the rule the previous
milestone exists to establish (and the spec's own edge case forbids widening it), and renaming
`models_moderation.py` passes the gate by defeating it.

**The wiring, therefore:**

| Component | Location | Boundary status |
|---|---|---|
| The probe itself | `app/application/moderation/ingestion_probe.py` | inside the moderation boundary — may read moderation tables and `app.infrastructure` |
| Construction | `app/main.py` | composition root — **exempt by directory** from the reverse check, like `app/workers/` and `app/scripts/` |
| Wiring into the report | `app/api/v1/health.py` | reads `app.state`; **imports nothing from moderation** |

`health.py` adds the `ProbeSpec` **only when the state attribute is present**. That falls out better
than the rejected options: the block's presence becomes conditional on composition, which is exactly
G6 — an absent credential means the component is simply not wired.

---

## 1. The block

`GET /health` gains one component. `required = false`, so a deliberately stopped bot never makes the
system look unready — the same treatment `model_runtime` already gets (FR-035).

```json
"telegram_ingestion": {
  "status": "ok",
  "required": false,
  "latency_ms": 4,
  "detail": "last update 12s ago",
  "ingestion": {
    "credential": "configured",
    "bot_identity": "resolved",
    "last_update_at": "2026-09-09T13:04:11Z",
    "seconds_since_last_poll": 12,
    "pending_updates": 0,
    "consecutive_failures": 0,
    "stood_down": false,
    "monitored_chats": 7,
    "chats_silent_over_6h": 1,
    "open_gaps": 0,
    "bot_not_admin_in": ["الرخصة المهنية — مسائي"]
  }
}
```

**The eight fields FR-034 requires** are `last_update_at`, `seconds_since_last_poll`,
`pending_updates`, `consecutive_failures`, `monitored_chats`, `chats_silent_over_6h`, `open_gaps` and
`bot_not_admin_in`. `credential`, `bot_identity` and `stood_down` are additions this contract makes
because G6 and FR-004a require the three-way state distinction below to be visible.

### ⚠ `ingestion` MUST be a declared field on `ComponentReport`

Measured (research probe 3), against the real class:

```
P3 unknown field ACCEPTED, dumped as:
  {'status':'ok','required':False,'latency_ms':0,'detail':'','gateway':None}
P3 model_config: {'frozen': True}
```

`ComponentReport` is `frozen=True` but not `extra="forbid"`, so pydantic v2 **accepts an unknown
keyword without error and then drops it**. A probe written as `ComponentReport(…, ingestion={…})`
raises nothing and produces a health payload with no ingestion data at all — while every assertion of
the form `report["status"] == "ok"` passes.

So: add `ingestion: dict[str, Any] | None = None` beside the existing `gateway`, and **assert the
block's contents** in tests, never merely the component's status. A test that checks only the status
cannot distinguish a working block from a silently empty one.

### The three credential states, which must never be collapsed

| `credential` | `bot_identity` | `status` | Meaning |
|---|---|---|---|
| `absent` | `not_attempted` | `ok` | No credential configured. Supported, healthy, deliberate (G6) |
| `configured` | `unreachable` | `degraded` | Platform not answering. Transient; retrying; recovers unattended |
| `configured` | `rejected` | `down` | Credential revoked or malformed. Operator action needed |
| `configured` | `resolved` | `ok` | Capturing |

Readiness is **unaffected in every row** — `required` is false throughout. The status field is
information for a human, not a gate.

### Field semantics worth pinning down

| Field | Definition |
|---|---|
| `last_update_at` | `ingestion_state.last_event_at` — the last poll that actually **returned** something. Not `last_success_at`; an empty poll is a success and a week of them is the reset condition |
| `seconds_since_last_poll` | from `last_poll_at`, success or failure |
| `pending_updates` | `COUNT(*) WHERE processed_at IS NULL` — served by the partial index (probe 8) |
| `stood_down` | `stood_down_at IS NOT NULL` — polling has stopped after the conflict threshold and needs an explicit restart (FR-004a) |
| `chats_silent_over_6h` | monitored chats whose `last_event_at` is older than 6 h. **The most likely silent failure** — a bot demoted without being removed stops receiving several kinds with no error anywhere |
| `open_gaps` | `COUNT(*) WHERE gap_end_at IS NULL` |
| `bot_not_admin_in` | monitored chats whose `bot_status <> 'administrator'`. Titles, not identifiers — the operator reads this |

**On a system that has never captured anything** the block renders with nulls and zeros, not an
error. That is a required test case (SC-013).

**No message text may appear in this block, ever.** `bot_not_admin_in` carries chat titles, which are
operator-supplied group names, not student content.

---

## 2. `make tg-doctor`

One command answering "is this set up correctly", before anything is running. Modelled on
`make doctor`: prose, exit non-zero on a real problem, and useful with no credential present.

```
$ make tg-doctor

Telegram ingestion diagnostics
  credential            present (dev)
  getMe                 ok — @InjazModerationDevBot (id 8123456789)
  webhook               NOT set                              ← required
  allowed_updates       matches configuration (6 kinds)
  chats
    الرخصة المهنية — مسائي        administrator   can_delete=yes   monitored
    تجريبي — dev                  administrator   can_delete=no    monitored
    اختبار قديم                   member          can_delete=no    not monitored   ⚠ not admin
  ingestion             last event 12s ago · 0 pending · 0 open gaps · not stood down

⚠ 1 monitored chat where the bot is not an administrator.
  chat_member and message_reaction updates are NOT being delivered for it, silently.
```

**The five setup states it must distinguish** (FR-036, SC-014), each with its own message and exit
code:

| State | Behaviour |
|---|---|
| No credential | says so plainly, **exits 0** — not a failure, it is the supported offline state |
| Credential rejected | names it, exits non-zero |
| Inbound delivery configured | **exits non-zero.** A webhook and long polling are mutually exclusive; this silently disables capture |
| Subscription set mismatched | names the missing kinds, exits non-zero. `chat_member` and `message_reaction` are the ones that matter — not delivered by default |
| Bot not an administrator in a monitored chat | names the chats, exits non-zero |

**Never prints the credential**, not even truncated. Reports its *presence*, and which environment it
appears to be, from configuration alone.

`tg-doctor` lives in `app/scripts/` — a composition root, exempt from the reverse boundary check by
directory, so it may read moderation tables and call the provider directly.

---

## 3. Log lines

Every capture log line carries at least one of TG-M0's six correlation identifiers — here, `update_id`
and `chat_id` — and **no message text** (FR-037, enforced by the gate's check 4).

```json
{"ts":"2026-09-09T13:04:11Z","level":"INFO","logger":"moderation.ingest",
 "message":"stored batch","update_id":870127,"chat_id":-1001234567890}
```

⚠ The correlation key for a Telegram message is **`message_id`**, never `message` — stdlib `logging`
rejects `extra={"message": …}` inside `makeRecord`, and the `KeyError` fires only at or above the
logger's level, so a test without `setLevel` passes vacuously. TG-M0's D-TG-24; restated here because
TG-M1 is the first milestone that actually emits these.

---

## 4. Test obligations

| Test | Why it earns one (Principle I) |
|---|---|
| Block contains all eight required fields, populated | FR-034. Probe 3 proved a status-only assertion cannot detect an empty block |
| Block renders on a never-captured system | SC-013's empty case — nulls and zeros, not an exception |
| The four credential/identity states are distinct | G6; collapsing two of them misleads an operator debugging a real outage |
| Readiness identical with and without a credential | FR-035, and the offline gate depends on it |
| `health.py` adds no ProbeSpec when the state attribute is absent | the conditional wiring in §0 |
| `tg-doctor` distinguishes five setup states | SC-014 |
| `tg-doctor` exits 0 with no credential | it must be runnable on a machine that holds no credential |
| No log line contains message text | FR-037; the gate's check 4 is the backstop, this is the direct test |

**Exempt** under Principle I: the block's JSON serialisation, the exact prose of `tg-doctor`'s output,
and the poller's sleep loop.
