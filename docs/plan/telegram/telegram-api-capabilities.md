# Telegram API Capabilities and Limitations

**Track**: Moderation Intelligence (`docs/plan/telegram/telegram-moderation-intelligence.md` §5)
**Source**: verified against the official Bot API reference and bot-features page, checked
2026-09-08, current version Bot API 10.3 (2026-08-24). Restated here, at TG-M0, per FR-031 — this
is orientation for every later milestone in the track, not something TG-M0 calls.

TG-M0 makes no Telegram call. This document exists so the two limitations below are read *before*
TG-M1 ships an ingester, not discovered mid-pilot.

---

## 1. What the Bot API gives us

| Capability | Detail | Why it matters |
|---|---|---|
| Every group message | Privacy mode is on by default and limits a bot to commands and replies aimed at it — but a bot added as **administrator** always receives all messages. | The bot must be a group administrator. Operational prerequisite, not a code decision. |
| `chat_member` updates | Requires the bot to be an administrator **and** `"chat_member"` explicitly in `allowed_updates` — not sent by default. `from` is documented as the performer of the action. | Bans, kicks and restrictions are attributable to a named moderator with a timestamp — the strongest moderation-action signal Telegram gives. |
| `my_chat_member` updates | Sent without admin rights; fires when the bot is added, promoted, demoted or removed. | Group auto-discovery and coverage-loss detection. |
| `message_reaction` updates | Requires admin and explicit `allowed_updates`. Carries the reacting user. Reactions set by *bots* are not delivered. | A human moderator's ✅ is a clean, timestamped, attributable "handled" signal a bot could never forge. |
| `update_id` semantics | Increases sequentially; lets a consumer ignore repeats or detect out-of-order delivery. | A natural idempotency key and an ordering key. |
| `getUpdates` | Long polling; single-consumer — a second concurrent poller on the same token gets `409 Conflict: terminated by other getUpdates request`. | Outbound-only ingestion with server-enforced single-consumer semantics. One bot token = one ingester. |
| `getUpdates` `limit` | Accepts only values **1–100**; there is no larger page size to request. Re-verified 2026-09-09 (TG-M1 research probe 6), Bot API 10.3. | The batch ceiling every later milestone reads is the API's own maximum, not a policy choice (`specs/004-tg-m1-telegram-ingestion/`, D-TG-40). |

## 2. Limitations inherited from Telegram

**No update is emitted when a message is deleted in a group, and no way exists to learn who
deleted it.** The only deletion update Telegram sends (`deleted_business_messages`) is scoped to
connected business accounts, never groups or supergroups. The admin log that would show a deletion
is an MTProto feature; a bot cannot read it and cannot become an MTProto client.

**There is no history API, and undelivered updates are kept for at most 24 hours.** Nothing before
the bot joins a group can ever be recovered, and an ingester offline longer than a day loses that
window permanently — a gap that looks identical to "nothing happened."

**⚠ After at least a week with no updates at all, the next `update_id` is chosen randomly instead
of sequentially, and it can be *lower* than the last one ever delivered.** Re-verified 2026-09-09
(TG-M1 research probe 7), Bot API 10.3. Unlike the two limitations above, this one is not left
unfixed: a consumer that always sends a strictly increasing `offset` would never receive the
renumbered identifier and would poll forever, succeeding and returning nothing, while every health
signal stayed green. TG-M1 detects the stall and recovers by omitting `offset` entirely rather than
sending a negative one — see `specs/004-tg-m1-telegram-ingestion/contracts/telegram-provider.md`
§5 and D-TG-33.

Every later milestone that measures moderator responsiveness must design around the first two. The
consequence worth stating plainly: **a fast, quiet moderator who deletes a problem message
silently will look worse than a slow, loud one who replies first and deletes later** — the reply is
observable and the silent deletion is not. No metric in this track may imply deletion visibility it
does not have; absences are reported as absences, not folded into a single score.

## 3. What the design does instead

Observable, attributable signals only: replies (`message.from`), reactions
(`message_reaction.user`), bans and restrictions (`chat_member.from`), and the panel's own audit
trail for anything a moderator does inside Filament. Ingestion uptime is a monitored SLO, and a gap
longer than 24 hours is recorded as an explicit marker so a report can say "this window is
incomplete" rather than silently under-count.

## 4. Operational prerequisites this creates

1. One bot, created via BotFather, added as **administrator** to every monitored group.
2. `allowed_updates` must explicitly list `message`, `edited_message`, `my_chat_member`,
   `chat_member`, `message_reaction` — the last two are not delivered by default.
3. Moderators must be members of the groups they moderate, and their Telegram user id must be
   mapped once in Filament.

See `docs/runbooks/tg-operator-prerequisites.md` §B and §F for the operator's steps and the same
two limitations restated for a non-engineering audience.
