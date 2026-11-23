# Research: TG-M6 — Alerts

The sources are `spec.md` (clarified 2026-11-12) and master plan §16, §10.12 and §25 TG-M6. Code was read on
2026-11-12. Findings continue the domain's numbering from 23, and decisions continue from D-TG-210.

## §0 — Findings (code read 2026-11-12)

- **Finding 24: button presses are already captured.**
  - `callback_query` is in `TELEGRAM_ALLOWED_UPDATES` (`.env.example:57`, `config.py:63`).
  - It is stored under the attached message's chat (`ingest.py:601`, `client.py:59`).
  - `process_update` leaves it uninterpreted (`process_update.py:9`).

  Nothing on the capture side changes.
- **Finding 25: the silence guarantee is a test, and it reaches PHP.** `test_no_outbound.py` does three things:
  - it forbids `sendMessage`, `setMessageReaction`, `deleteMessage` and the ban, restrict and unban methods on
    the provider;
  - it scans `app/` for those method names;
  - it forbids `Http::`, `GuzzleHttp` and `curl_` in the panel.

  **The panel can never call Telegram.** So every alert edit, including the one after a panel act, must come
  from Python.
- **Finding 26: the incident views already admit a new act that names its incident.**
  - Evidence branch (d) joins any `moderation_actions` row by `moderation_incident_id` (0006:282).
  - The state view resolves on the earliest confirmation of any kind (0012's header).

  Only three places are kind-specific: `ck_actions_type`, `ck_actions_strength` and `ck_actions_panel_link`,
  plus the state view's false-positive lateral `e.kind = 'panel_false_positive'` (0006:325).
- **Finding 27: attention assignment knows three acts, and "My work" names them.**
  - `attention_item_assignee` has three branches: reply, dismissal and reaction (0011:84).
  - The attention "My work" figure splits into hard-coded `via_reply`/`via_dismissal`/`via_reaction` columns,
    in both Python (`metrics.py:469`) and PHP (`AttentionMetrics.php:173`).
  - The incident "My work" figure groups by `assigned_via` (`metrics.py:549`, `IncidentMetrics.php:217`), so it
    needs labels only.
- **Finding 28: the tick exists, and it lives in the poller.** On each `MODERATION_TICK_INTERVAL_S`, the winner
  of `tick_lease` enqueues `expire_stale_items` and `sweep_unjudged_bursts` (`telegram_main.py:83`). If
  `ai-telegram` stops, nothing is evaluated.
- **Finding 29: the first-posted text can already be read, and so can its removal.**
  - `classification.load_facts` re-extracts the text from the captured event and reads
    `text_purged_at`/`payload_purged_at` (`classification.py:147`).
  - The panel shows `telegram_messages.original_text`, which an edit overwrites (TG-M5 Finding 5).
  - FR-531's "as the panel shows it" therefore conflicts with "a later edit does not change it". D-TG-221
    resolves this.
- **Finding 30: no purge job exists yet.** `MODERATION_TEXT_RETENTION_DAYS` is only validated (`config.py:269`).
  The purge is TG-M10's.
- **Finding 31: the panel shows times in one constant timezone, `Asia/Riyadh`.**
  - PHP: `IncidentInfolist.php:366`, `ListIncidents.php:43`.
  - Python already uses `ZoneInfo("Asia/Riyadh")` (`attention_review.py:43`).
- **Finding 32: `moderator_id_for` deliberately ignores `is_active`** (`identities.py:79`). The press gate must
  check it itself.
- **Finding 33: the provider cannot tell "never sent" from "maybe sent".** `_request` retries a 429 in place,
  sleeping for `retry_after` (`client.py:157`). It maps every `httpx.TransportError` to `Unreachable`
  (`client.py:151`), whether the request left the machine or not.
- **Finding 34: the health facts are already stored.**
  - `telegram_chats.last_event_at` is refreshed from any update that carries a chat.
  - `bot_status`/`bot_status_at` come only from `my_chat_member`.
  - A chat whose standing was never observed stays `'unknown'` (`ingest.py`, `upsert_chats_from_batch`).

## §0b — Platform facts the design relies on (Bot API)

- **T1.** A `callback_query` carries `id`, `from`, `message`, `chat_instance` and `data`. It has **no date**.
- **T2.** `callback_data` is 1–64 bytes. A modified client can send any data for a message, so it is never
  trusted alone.
- **T3.** An `answerCallbackQuery` text is at most 200 characters. A query that is too old can no longer be
  answered, and Telegram returns 400.
- **T4.** A bot may send about 20 messages a minute to one group. Above that, it gets 429 with `retry_after`.
- **T5.** A bot can edit its own messages with `editMessageText`. Sending identical content returns 400 "message
  is not modified".
- **T6.** HTML `parse_mode` supports `<a href="tg://user?id=N">name</a>`, which mentions a member and notifies
  them.
- **T7.** A message link exists in two cases:
  - in a public chat: `t.me/<username>/<id>`;
  - in a supergroup, for its members: `t.me/c/<id without -100>/<id>`.

  A basic group has none.
- **T8.** Sending to a basic group that became a supergroup fails with 400 and `migrate_to_chat_id`.

Probes to run in development before go-live (quickstart §1):
- **P1:** edit a 3-day-old alert.
- **P2:** a URL button pointing at `http://localhost:8080`.
- **P3:** answer a press about 20 minutes late.
- **P4:** a `tg://user` mention notifies a member who has muted the group.
- **P5:** the alert group is created as a supergroup, so it never migrates.

**Results (T551, development, 2026-11-17 to 2026-11-23).** The operator reports every probe passed locally;
outcomes were not itemized one by one. The development database shows:
- **P2:** four alerts were sent with `MODERATION_PANEL_BASE_URL=http://127.0.0.1:8080` and none failed, so
  Telegram accepted the URL button. The panel link stays a button; `alert-messages.md` §5's text-link
  fallback is not needed.
- **P5:** the group was promoted *after* the bot joined. Telegram created a new supergroup row, linked it to
  the old one through `migrated_to/from_chat_id`, and reported the bot there as `restricted` (it could still
  send). Two changes followed:
  - the panel no longer offers a migrated chat as the destination (contract D2 note);
  - the operator made the bot an administrator with no rights (quickstart §1, step 4).
- **The smoke (T552):** four sent alerts (two `incident_flagged`, two `question_waiting`) were all edited to
  their final state. Presses recorded one `alert_handled`, one `alert_false_positive` and three
  `alert_take`.

## §1 — Decisions

- **D-TG-211: the destination is a flag on `telegram_chats`**, `is_alert_destination`.
  - A partial unique index allows one destination.
  - `ck_chat_destination_not_monitored` stops a chat from being both the destination and monitored.

  So FR-501/FR-502 hold in the database, in both directions, for both languages.
  - *Rejected:* an environment key, because TG-M0's environment contract says the destination is data. A
    settings table, because it would be a second home for one chat's role. A per-rule destination (plan
    §10.12), because the operator chose one group.
- **D-TG-212: `alert_rules` is the plan's table, slimmed down.**
  - No `name`, `destination` or `destination_chat_id`. Scope is `telegram_chat_id` NULL (all groups) or set.
  - `enabled_at` is stamped on every enable (FR-515).
  - Nothing is seeded (FR-510).
  - The `alerts` foreign key is `RESTRICT`, so a rule that has fired cannot be deleted (FR-514).
- **D-TG-213: one evaluator per tick, running set-based SQL over the existing views.**
  - `evaluate_alert_rules` runs one statement per trigger. Each reads `attention_items`,
    `moderation_incident_state` or `telegram_chats` and resolves the rule group-first (`COALESCE` over the two
    unique scopes).
  - Inserts use `ON CONFLICT (dedupe_key) DO NOTHING RETURNING id`, and only the returned ids are delivered.
  - Two evaluators overlapping is harmless. The tick lease is the only lease.
  - A repeat's index is `least(floor((now − first_fired) / interval), max)`. It is inserted only when that
    index is absent, so an outage never back-fills (FR-523).
- **D-TG-214: a health subject is an episode.**
  - **Silence:** the chat plus its `last_event_at`.
  - **Standing:** the chat plus its `bot_status_at`.

  A new episode can alert again, and the old one ends when the episode moves. `'unknown'` never alerts: the
  standing was never observed, and that is `tg-doctor`'s finding to report, not an alert's (Finding 34).
- **D-TG-215: delivery is at most once per alert.**
  - Claim: `pending/failed → sending`, with a guarded `UPDATE … RETURNING`.
  - Three failures are retried with backoff, up to 5 attempts: a connect-phase failure (the request never
    left), a 5xx, and a 429 after its wait.
  - A timeout or broken connection **after** the request was written is `failed` with category
    `telegram_outcome_unknown`, and is never retried. The provider gains `TelegramOutcomeUnknownError` to tell
    the two apart (Finding 33).
  - *Why:* a duplicate message carries buttons no alert row maps, while a lost alert is covered by the next
    repeat and shown in the history.
- **D-TG-216: alert edits are driven by the tick, reading the views.**
  - An item or incident ends by seven routes across two languages: reply, expiry, dismissal, ban/expulsion/
    restriction, 👀, panel and button. The panel cannot call Telegram (Finding 25).
  - Reading the derived state once per tick covers every route with one code path.
  - Each alert stores `rendered_state`: the inputs that change its text (status, actors, assignee, whether
    the excerpt shows). It never stores the text. An alert is edited only when `rendered_state` changes.
  - Ages are frozen at firing, so a waiting alert is not edited on every tick.
  - The press's own actor also refreshes the pressed alert at once (FR-561).
- **D-TG-217: a button act is a `moderation_actions` row.** There are three kinds:
  - `alert_handled`, with strength `confirmation`;
  - `alert_false_positive`, with no strength and no note;
  - `alert_take`, with no strength.

  Each row carries:
  - `alert_id`;
  - `source_update_id` = the callback's stored update;
  - the presser's `actor_moderator_id` and `actor_telegram_user_id`;
  - `occurred_at` = the update's `received_at` (T1).

  Incident kinds also carry `moderation_incident_id`, so evidence branch (d) and the assignee view take them
  unchanged (Finding 26).
  - *Rejected:* a new acts table, which would be a third act store needing view branches for incidents.
    Reusing `panel_*` kinds, which `ck_actions_provenance` gives no update and which would claim a panel user.
- **D-TG-218: the two views are replaced in place.** `CREATE OR REPLACE VIEW` keeps every existing column in
  order, so dependants are untouched.
  - **The state view:**
    - its false-positive lateral reads `panel_false_positive` and `alert_false_positive`;
    - two columns are appended, `close_kind` and `closed_by_moderator_id`.
  - **The attention assignee view** gains a fourth branch, `alert_take` with rank 4 and via `'alert'`. It
    finds the item through `alerts.subject_id`.
- **D-TG-219: the press gate trusts the message, not the data.** A press is judged only when all of these hold:
  - its `(chat, message_id)` is an alert's `(sent_chat_id, sent_message_id)`;
  - `data = "a:<alert_id>:<h|f|t>"` names **that** alert;
  - the action fits the alert's subject (h and f for incidents, t for items);
  - the presser maps to a `moderators` row that is `is_active`, with `created_at` ≤ the press's instant
    (Finding 32).

  The gate runs under `incident_lock` for incident acts, and under the source chat's `chat_lock` for takes. It
  reads the **current** derived state. A press processed after another route ended its subject records
  nothing, even if it was received first. That keeps "who resolved it" from moving after the fact.
- **D-TG-220: a press's side effects run in their own actor.**
  - `process_update` derives the act. In the same run it enqueues `answer_alert_press(update_row_id,
    outcome)`, which answers the press and refreshes the alert.
  - `rederive_chat` never reaches a callback update: the alert group is not monitored, and it refuses such
    chats.
  - The derivation is `ON CONFLICT (source_update_id) DO NOTHING`.

  Re-derivation therefore sends nothing (FR-556).
- **D-TG-221: the excerpt is the first-posted text from the captured event (Finding 29).**
  - It is redacted with `text.redact`, then cut to 100 characters at a word boundary, with "…" when cut.
  - It shows only while the text is held **and** the message is younger than `MODERATION_TEXT_RETENTION_DAYS`
    (Finding 30), so the retention edit is simply one more `rendered_state` change.
  - It is built at render time, never stored and never logged.
  - The spec amends FR-531's "as the panel shows it" to match.
- **D-TG-222: alert wording is one Python module keyed by the panel's English strings.** A test asserts that
  each Arabic value equals `apps/ai-control/lang/ar.json`'s entry, so an alert and the panel cannot drift.
  Durations follow Arabic number agreement (`alert-messages.md` §3), and digits are Western.
- **D-TG-223: quiet hours are judged in `Asia/Riyadh`**, the panel's constant (Finding 31).
  - Windows are `[from, to)` and may cross midnight.
  - The firing moment decides.
  - A suppressed alert takes its repeat number.
- **D-TG-224: links.**
  - The message link follows T7.
  - The panel link comes from a new non-secret key, `MODERATION_PANEL_BASE_URL`. Blank means no panel link.
    That key is deployment configuration, not a threshold or destination, which are what TG-M0's contract
    bars.
  - If P2 shows Telegram refuses the URL in a button, the link goes in the text instead.
- **D-TG-225: mentions use T6's `tg://user` HTML link** with each named moderator's Telegram id. Names and the
  excerpt are HTML-escaped.
- **D-TG-226: delivery runs on the existing `default` queue (`ai-worker`).** The volume is far below T4, and the
  provider already waits on 429. *Rejected:* a new queue and service, more operations for no measured need.
- **D-TG-227: the silence test is rewritten, not deleted.**
  - `setMessageReaction`, `deleteMessage`, `pinChatMessage` and the ban, restrict and unban methods stay
    forbidden everywhere.
  - `send_message`, `edit_message_text` and `answer_callback_query` exist on the provider. They may be called
    only from `app/application/moderation/alert_delivery.py`.
  - A runtime guard checks, inside the same transaction, before every send or edit, that:
    - the target of a send is the designated destination;
    - the target of an edit is an alert's posted chat;
    - the target is not monitored.
- **D-TG-228: the panel writes rules and the destination flag, and only reads alerts.** `App\Models\Alert`
  throws from `creating`, `updating` and `deleting`, as `ModerationAction` does.

## §2 — Not measured here

- Evaluator cost. At production volume (a few groups, tens of items a day), five set-based statements per 30 s
  are negligible. An index waits for a measured query over ~300 ms (master plan TG-M7).
- Telegram's real per-group limit for edits. The edit volume is bounded by subject ends, at most one edit per
  alert per state change.
