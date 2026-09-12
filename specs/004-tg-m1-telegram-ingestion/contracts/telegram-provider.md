# Contract: The Telegram Provider

**Status**: **the** durable contract of TG-M1, in the role `contracts/gateway-interface.md` plays for
the model gateway. Named in the source plan's §30 as the artifact worth writing.
**Owner**: `apps/ai-api/app/providers/telegram/`
**Binding on**: TG-M1…TG-M10. A later milestone adds methods here; it does not reach past this
boundary.

---

## 0. The rule this exists to enforce

> **Every Telegram HTTP call in this repository goes through this provider.** Retry, rate-limit and
> error mapping live here and nowhere else. No caller implements its own backoff, parses an HTTP
> status, or reads a Telegram error string.

Mechanically enforced today by `scripts/check.sh`'s check 3 (no Telegram SDK outside
`app/providers/telegram/`) and by the existing `httpx` rule, which already exempts `app/providers/`.
The provider speaks the Bot API over `httpx`; **no SDK dependency is added** — TG-M0's D-TG-19.

The mirror rule, from the source plan's §7.3: this provider **must never contain a business rule or
an SLA threshold**. "Five conflicts then stand down" is a policy the caller applies; "a 409 is a
`TelegramConflictError` and is not retryable" is this module's.

---

## 1. Verified capabilities — the table every later milestone codes against

Verified against the official Bot API reference; `limit`, `offset`, retention, `allowed_updates` and
`update_id` sequencing re-verified 2026-09-09 (research probes 6 and 7). Bot API 10.3.

| Capability | Detail | Consequence here |
|---|---|---|
| Receive every group message | Privacy mode is on by default, but **a bot added as administrator always receives all messages** | Administrator status is an operational prerequisite, not a code path |
| `Message` reply metadata | `message_id`, `date`, `edit_date`, `from`, `sender_chat`, `reply_to_message`, `external_reply`, `quote`, `message_thread_id`, `media_group_id` | Reply correlation is a **Telegram fact**, not an inference (TG-M3) |
| `chat_member` | Needs bot admin **and** explicit `allowed_updates`. `from` is "performer of the action" | Bans and restrictions are attributable to a named moderator with a timestamp (TG-M4) |
| `my_chat_member` | Delivered without admin rights; fires on add, promote, demote, remove | Chat discovery and coverage loss (FR-026, FR-027) |
| `message_reaction` | Needs bot admin **and** explicit `allowed_updates`. Carries the reacting user. **Bot reactions are not delivered** | A human ✅ is attributable and unforgeable (TG-M4) |
| `message_reaction_count` | Anonymous, **delayed by minutes** | **Not requested.** Useless for timing |
| Service messages | `migrate_to_chat_id`, `migrate_from_chat_id`, `new_chat_members`, `left_chat_member`, `pinned_message` | Supergroup migration (FR-029) |
| `update_id` | "start from a certain positive number and increase sequentially" — an idempotency key **and** an ordering key | `UNIQUE (bot_id, update_id)` |
| `getUpdates` `limit` | **"Values between 1-100 are accepted"**, default 100 | The batch ceiling **is** the API maximum (D-TG-40) |
| `getUpdates` `timeout` | Long-poll seconds; default 0 = short polling, "for testing purposes only" | 30 s, with a **35 s** client read timeout (D-TG-39) |
| `getUpdates` `offset` | "An update is considered confirmed as soon as getUpdates is called with an offset higher than its update_id." **Omitted ⇒ "updates starting with the earliest unconfirmed update are returned."** | Confirmation is the consumption protocol; omission is the reset recovery (§5) |
| Single consumer | A webhook and `getUpdates` are mutually exclusive; a second poller gets `409 Conflict: terminated by other getUpdates request` | **One token = one ingester**, server-enforced |
| Admin actions | `sendMessage`, `setMessageReaction`, `deleteMessage`, `banChatMember`, `restrictChatMember` | **Not implemented in TG-M1.** No method on this provider can send, react, delete, ban or restrict (FR-038) |

## 2. Verified limitations — inherited, not fixable

| Wanted | Reality | What the design does instead |
|---|---|---|
| "A message was deleted" in a group | **No such update exists.** `deleted_business_messages` is scoped to business accounts only | Never claim deletion detection |
| "Who deleted it" | Not exposed. The admin log is MTProto; a bot cannot read it | Attribute only what Telegram attributes |
| History / backfill | **No history API.** Undelivered updates kept **at most 24 hours** | A gap beyond 24 h is permanently unrecoverable and is recorded as such |
| Two consumers of one token | Impossible | One ingester; the loser stands down (§4) |
| ⚠ Stable identifier sequence | **"If there are no new updates for at least a week, then identifier of the next update will be chosen randomly instead of sequentially."** | §5 — the reset protocol. Without it a strictly-forward offset stalls capture permanently |

---

## 3. The Protocol

```python
class TelegramProvider(Protocol):
    async def get_me(self) -> BotIdentity: ...
    async def get_updates(
        self,
        *,
        offset: int | None,          # None ⇒ omit the parameter entirely (§5). NEVER negative.
        limit: int,                  # 1..100
        timeout_s: int,              # server-side long poll
        allowed_updates: list[str],
    ) -> list[TelegramUpdate]: ...
    async def get_webhook_info(self) -> WebhookInfo: ...   # tg-doctor: must report NOT set
    async def get_chat_member(self, *, chat_id: int, user_id: int) -> ChatMemberStatus: ...
```

**`offset=None` means "omit the parameter"**, not "send zero". The distinction is load-bearing: it is
how §5 recovers from a reset, and an implementation that coerces `None` to `0` happens to behave the
same today but records an intent the caller did not express.

**`TelegramUpdate` models only what routing needs** — `update_id`, the kind, the chat id — plus
`raw: dict` carrying the whole update for storage. The provider deliberately does **not** model the
Bot API's object graph: TG-M2 reads what it needs out of the stored payload, so a Bot API addition
never breaks ingestion. An unrecognised kind maps to `unknown` and is stored regardless (FR-012).

---

## 4. The error taxonomy

Closed, with a `retryable` class-var, in the exact shape of
`app/application/gateway/errors.py` — **retry logic branches on the flag, never on message text.**

| Class | Raised for | `retryable` | Caller's obligation |
|---|---|---|---|
| `TelegramUnreachableError` | connect failure, DNS, refused | **yes** | back off; count toward `consecutive_failures` |
| `TelegramTimeoutError` | client read timeout exceeded | **yes** | back off. Should be rare — the read timeout exceeds the long poll by design |
| `TelegramRateLimitedError` | HTTP 429; carries `retry_after` from `parameters.retry_after` | **yes** | **wait exactly `retry_after`.** Not this caller's own backoff |
| `TelegramConflictError` | HTTP 409, another consumer | **no** | back off, increment `consecutive_conflicts`, **stand down at the threshold** (§6) |
| `TelegramAuthError` | HTTP 401 / 404 on the token path — revoked or malformed credential | **no** | stay up, keep retrying identity resolution, report distinctly (FR-007c) |
| `TelegramRejectedError` | HTTP 400 — a bad request shape | **no** | a bug; log with correlation ids, do not retry |

`retry_after` honouring belongs to the provider alone (FR-005). A caller that sleeps on its own has
broken this contract even if the sleep is correct.

**Mapping source is structural, not textual** (probe 5): `httpx.ReadTimeout` → `TimeoutException` →
`TransportError` gives connect/read/pool separation without matching on strings.

---

## 5. ⚠ The identifier-reset protocol

The single most important paragraph in this contract, because getting it wrong produces an ingester
that is dead and reports itself healthy.

**The hazard.** After **≥ 1 week with no updates at all**, Telegram chooses the next `update_id`
**randomly**. It may be *lower* than the last one stored. `getUpdates` returns only identifiers at or
above `offset`, so a poller that always sends `offset = last_update_id + 1` will never receive it. The
poll succeeds, returns `[]`, raises nothing — forever.

**The protocol.**

1. **Detect.** Polls are succeeding, returning empty, and `ingestion_state.last_event_at` is older
   than the stall window (default **8 days**, just past Telegram's own "at least a week").
2. **Re-sync.** Call `get_updates(offset=None, …)` — the parameter omitted. Documented to return
   "updates starting with the earliest unconfirmed update", so the low-numbered update arrives.
3. **Adopt.** Take whatever identifier comes back, **even a lower one**, and write an
   `ingestion_gaps` row with `reason='update_id_reset'`, `unrecoverable=false`.

**Never send a negative offset.** The documentation is explicit that it means "All previous updates
will be forgotten" — it discards the unconsumed backlog. It is a data-loss operation, not a recovery,
and no method on this provider may issue one.

**`update_id_reset` is not a loss.** A report whose window overlaps it must **not** be marked
incomplete. Marking it would be dishonest in the opposite direction from the one this domain guards
against: claiming missing data where none is missing.

---

## 6. Policy that belongs to the **caller**, not here

Stated so the boundary stays clean. This provider knows none of these numbers:

| Policy | Value | Lives in |
|---|---|---|
| Stand down after N conflicts | 5 (configurable) | `app/application/moderation/ingest.py` (FR-004a) |
| Minimum silence recording a gap | 5 minutes | same (FR-025) |
| Stall window before a reset re-sync | 8 days | same (§5 step 1) |
| Batch ceiling | 100 | passed in as `limit` |
| Long-poll seconds | 30 | passed in as `timeout_s` |
| Which chats are monitored | `telegram_chats.is_monitored` | the database |

---

## 7. Testing this contract without Telegram

`FakeTelegramTransport` — an `httpx.MockTransport` scripting `getUpdates` responses, mirroring how the
gateway's tests already inject a transport. Probe 5 confirmed the round trip works against the real
`httpx` 0.28.1.

The scripted shapes every implementation must satisfy:

| Scenario | Script | Expected |
|---|---|---|
| Normal batch | `{"ok": true, "result": [ …3 updates… ]}` | 3 stored, 3 scheduled |
| Redelivery | the same batch twice | 3 stored, 3 scheduled, **once** |
| Partial store failure | batch of 3, store fails on the 3rd | position at the 2nd, not the 3rd |
| Rate limit | `429` + `{"parameters": {"retry_after": 7}}` | waits 7 s; no caller-side backoff |
| Conflict | `409 Conflict: terminated by other getUpdates request` × 5 | stands down, gap row, health reports it |
| Conflict then success | `409`, then `200` | counter resets, still running |
| Auth failure | `401` on `getMe` | stays up, retries, distinct from "no credential" |
| Identifier jump | ids 100, then 140, `last_event_at` recent | `update_id_jump` gap, `unrecoverable=true`, capture continues at 140 |
| **Identifier reset** | empty polls, `last_event_at` 9 days old, then `offset` omitted returns id 7 | position moves **backwards** to 7; `update_id_reset` gap; `unrecoverable=false` |
| Unknown kind | an update with a field no version models | stored as `unknown`, not discarded |
| No chat | an update carrying no chat | stored with `chat_id` NULL |

**`make check` must pass with no credential set and no network access.** Every row above runs against
the fake.

---

## 8. What this provider may never do

1. **Send anything.** No `sendMessage`, `setMessageReaction`, `deleteMessage`, `banChatMember` or
   `restrictChatMember` method exists in TG-M1 (FR-038). TG-M6 adds sending, to the private
   moderators' group only.
2. **Set a webhook.** `setWebhook` is not implemented. `getWebhookInfo` exists solely so `tg-doctor`
   can assert one is **not** configured.
3. **Send a negative offset** (§5).
4. **Hold business state.** It is stateless; the position lives in Postgres.
5. **Log message text.** Enforced by the gate's check 4.
6. **Contain a threshold** (§6).
