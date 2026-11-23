# Contract: Alerting (TG-M6)

**Status**: the durable contract of TG-M6. It amends four contracts, each carrying a dated "Amended by TG-M6"
note:
- `specs/004…/contracts/telegram-provider.md` §8;
- `specs/005…/contracts/message-derivation.md` §1 (`callback_query`);
- `specs/007…/contracts/incident-lifecycle.md` §2 and §5;
- `specs/012…/contracts/group-teams.md` G1/G2.

**Wording**: `alert-messages.md`. **Schema**: `data-model.md`.

---

## §0 — The promise

The system speaks in one place only, the alert group. There it says something exactly once per rule, subject
and repeat. A button press there is an act with the same guarantees as the same act in the panel. Nothing
the system says or fails to say changes an item, an incident or a figure.

## §1 — The destination

- **D1.** At most one chat is the destination (`uq_chat_one_alert_destination`). The operator designates it
  in the panel.
- **D2.** The destination is never monitored, and a monitored chat is never the destination
  (`ck_chat_destination_not_monitored`). The database refuses both. *(Added 2026-11-17, T551 finding.)*
  The panel never offers a chat that has become a supergroup (`migrated_to_chat_id` set): nothing can be
  posted there any more (V5's `destination_migrated`).
- **D3.** Nothing in the destination is measured. Derivation is already gated on `is_monitored`, so no
  message, item, incident, classification or figure ever comes from it.
- **D4.** With no destination, an alert that reaches delivery becomes `not_sent / no_destination`. Firing
  still records it.
- **D5.** `make tg-doctor` reports three things about the destination:
  - whether one is designated;
  - the bot's standing there, through `getChatMember`; it must be `member` or `administrator` and able to
    send;
  - that the chat is not monitored.

## §2 — Rules

- **R1.** Rules are rows that the operator creates. Nothing is seeded, and no threshold value exists in code,
  configuration defaults or fixtures outside tests.
- **R2.** There are five triggers: `question_waiting`, `incident_flagged`, `incident_unhandled`,
  `group_silent`, `bot_not_admin`.
- **R3.** A threshold is required for `question_waiting`, `incident_unhandled` and `group_silent`, and
  forbidden for the others.
- **R4.** Filters are allowed only on the two incident triggers. There are three:
  - `min_severity`, compared in the order `low < medium < high`;
  - `categories`;
  - `openers`.

  A NULL filter matches everything.
- **R5.** The rule in force for (chat, trigger) is the chat's row if it exists, enabled or not; otherwise the
  global row. A disabled chat row mutes the trigger for that chat.
- **R6.** Repeats are given by `repeat_every_s` and `max_repeats`, both or neither.
- **R7.** Quiet hours are a list of `[from, to)` windows in `Asia/Riyadh`. Each window is `HH:MM` to `HH:MM`,
  and `to < from` crosses midnight. `from = to` is refused.
- **R8.** `enabled_at` is stamped on each change from disabled to enabled. A rule that has fired is never
  deleted (`RESTRICT`).

## §3 — Firing

The evaluator `evaluate_alert_rules` is enqueued by the tick's lease winner, once per
`MODERATION_TICK_INTERVAL_S`.

- **F1.** For each trigger, one set-based statement selects the qualifying subjects under the rule in force.
  - Each subject's **qualifying moment** must be at or after `rule.enabled_at` (FR-515).
  - "Now" is the statement's `now()`.
  - Each subject qualifies as follows:

| Trigger | Subject | Qualifies while | Qualifying moment |
|---|---|---|---|
| `question_waiting` | `attention_item` | `status = 'open'` and `now() − opened_at ≥ threshold` | `opened_at + threshold` |
| `incident_flagged` | `incident` | state `open` or `acknowledged`, and the filters match | `detected_at` |
| `incident_unhandled` | `incident` | state `open` or `acknowledged`, `now() − detected_at ≥ threshold`, and the filters match | `detected_at + threshold` |
| `group_silent` | `chat` @ `last_event_at` | monitored and `now() − last_event_at ≥ threshold` | `last_event_at + threshold` |
| `bot_not_admin` | `chat` @ `bot_status_at` | monitored and `bot_status NOT IN ('administrator', 'unknown')` | `bot_status_at` |

  Incident state is `moderation_incident_state.status`, and an item's state is `attention_items.status`. No
  state is recomputed (FR-521).
- **F2.** The first alert has `repeat_index = 0`, inserted with `ON CONFLICT (dedupe_key) DO NOTHING RETURNING
  id`. Only the ids returned are passed to delivery.
- **F3.** Repeat k is due when three things hold:
  - the subject still qualifies;
  - the rule has repeats;
  - `k = least(floor((now() − first.fired_at) / repeat_every_s), max_repeats) ≥ 1`.

  It is inserted only if no alert for that rule, subject and episode has an index ≥ k. Missed indexes are
  never back-filled.
- **F4.** Each alert records `rule_values` (the values in force) and `qualified_at`.
- **F5.** An alert whose `fired_at` falls inside one of its rule's quiet-hours windows is inserted as
  `suppressed` and is never claimed (FR-543). It keeps its index, so the repeat schedule runs on.
- **F6.** At most one alert per subject is inserted per evaluation.
- **F7.** Firing writes only `alerts`. It never writes an item, an incident, an act or a figure.
- **F8.** Overlapping evaluators are harmless: F2 and F3 are idempotent by `dedupe_key`.

## §4 — Delivery

`deliver_alert(alert_id)` runs on the `default` queue.

- **V1. Claim.** `UPDATE alerts SET delivery_status = 'sending', attempts = attempts + 1 WHERE id = :id AND
  delivery_status IN ('pending', 'failed') AND attempts < 5 AND last_error_category IS DISTINCT FROM
  'telegram_outcome_unknown' RETURNING …`. With no row returned, it does nothing.
- **V2. Re-check, in the claiming transaction.** Delivery stops in two cases:
  - there is no destination: the alert becomes `not_sent / no_destination`;
  - the subject no longer qualifies under F1's "qualifies while": the alert becomes `not_sent /
    subject_ended`.
- **V3. The guard (D-TG-227).** The send's `chat_id` is read from the destination row in the same transaction.
  That row must still satisfy D2. `alert_delivery.py` is the only caller of `send_message`.
- **V4. Send.** The message is rendered per `alert-messages.md`: HTML, mentions, links and an inline keyboard.
  On 200 the alert becomes `sent`, with `sent_chat_id`, `sent_message_id`, `delivered_at`, `rendered_state`,
  `excerpt_shown` and `final_at = NULL`.
- **V5. Failures.** The provider's error category goes in `last_error_category`.
  - A connect-phase failure, a 5xx or an exhausted 429 wait: the alert becomes `failed`, retried with
    exponential backoff up to 5 attempts.
  - `TelegramOutcomeUnknownError`: the alert becomes `failed` and is final. It is never retried (D-TG-215).
  - A 400 whose parameters carry `migrate_to_chat_id`: the alert becomes `failed` with category
    `destination_migrated`, final. The operator re-designates the destination.
- **V6.** No failure changes any state or figure (FR-541).
- **V7.** No log line carries the excerpt or the rendered text. The keys are `alert_id`, `chat_id` and
  `incident_id`.

## §5 — Presses

`process_update`, on `callback_query`, calls `derive_alert_press(update_row_id)`. Then, in the same actor
run, it enqueues `answer_alert_press(update_row_id, outcome)`.

- **B1. The gate (D-TG-219).**
  - The callback's `message.chat.id` and `message.message_id` must match an alert's `(sent_chat_id,
    sent_message_id)`.
  - `data` must be `a:<that alert's id>:<h|f|t>`.
  - `h` and `f` are valid only on incident subjects, and `t` only on attention-item subjects.

  Otherwise the outcome is `invalid` and nothing is recorded.
- **B2. The presser.** `from.id` must map, through `telegram_users`, to a `moderators` row that is
  `is_active`, with `created_at` ≤ the press's instant. Otherwise the outcome is `not_a_moderator` and nothing
  is recorded.
- **B3. The instant.** `occurred_at` is the callback update's `received_at` (T1).
- **B4. Incident acts.** Under `incident_lock`, read `moderation_incident_state`.
  - If the status is `resolved` or `closed_false_positive`, the outcome is `already_ended` and nothing is
    recorded.
  - Otherwise insert `alert_handled` (confirmation) or `alert_false_positive` with `moderation_incident_id`,
    `alert_id`, `source_update_id`, the actor's moderator and identity, and `telegram_chat_id` = the
    incident's chat. The insert is `ON CONFLICT (source_update_id) DO NOTHING`. The outcome is `recorded`.
- **B5. Takes.** Under the source chat's `chat_lock`, read the item.
  - If its `status <> 'open'`, the outcome is `already_ended`.
  - Otherwise insert `alert_take` the same way. The outcome is `recorded`, or `recorded_not_team` when the
    presser is not on the team at the instant, or `already_taken` when `attention_item_assignee` already names
    someone else. All three record the act. Assignment is the view's decision (FR-557).
- **B6. Idempotence.** One act per update (`uq_moderation_actions_source_update`). Re-running yields the same
  row and the same outcome.
- **B7. Answers.** `answer_alert_press` answers every press with its outcome's text (`alert-messages.md` §5),
  then refreshes the alert (§6). A "query is too old" answer failure is logged by category and ignored.
- **B8. No re-derivation side effects.** `rederive_chat` refuses unmonitored chats, so it never reaches a
  callback. The derivation itself sends nothing.

## §6 — Updating alerts

`refresh_alert(alert_id)` runs on the `default` queue. It is enqueued from two places:
- by the evaluator, for each `sent` alert with `final_at IS NULL` or `excerpt_shown`, whose computed render
  state differs from `rendered_state`;
- by `answer_alert_press`.

- **U1.** The render state is the set of inputs that change the text:
  - the subject's status and its end (who, how, when);
  - the current assignee and how they took it;
  - whether the excerpt shows (`alert-messages.md` §2).

  Ages are frozen at firing.
- **U2.** When the render state differs from `rendered_state`, the alert is edited with `editMessageText`. The
  edit target is the alert's own `(sent_chat_id, sent_message_id)`, and that chat must not be monitored
  (D-TG-227). An ended subject's keyboard is removed and `final_at` is set.
- **U3.** "Message is not modified" counts as success. Other failures are recorded in `last_edit_*` and
  retried by the next evaluation, up to 5 consecutive attempts. An alert deleted in Telegram ("message to edit
  not found") is marked final, and its excerpt is treated as gone (`excerpt_shown = false`).
- **U4.** The excerpt shows only while the text is held and the message is younger than
  `MODERATION_TEXT_RETENTION_DAYS`. Crossing that age is therefore one more render-state change (FR-535).
- **U5.** A health alert ends when its episode moves: a newer `last_event_at` (silence), or a newer
  `bot_status_at` (standing).
- **U6.** No edit changes any state or figure.

## §7 — Panel

- **S1. Alert Rules** (a resource): list, create and edit; no delete action.
  - Its validation mirrors §2.
  - It offers only monitored groups for a group rule.
  - The enable toggle stamps `enabled_at`.
  - It shows one line explaining FR-515: "A rule alerts on what crosses its threshold after it is switched
    on."
- **S2. The destination**, on Telegram Groups: "Use as alert destination" on an unmonitored chat; "Stop using"
  on the destination. The monitoring toggle refuses the destination with a message, and D2 backs it.
- **S3. Alerts** (a page, paged at 10): rule, trigger, group, subject link, repeat, status (with its reason or
  error category), fired, delivered and presses. It can be filtered by rule, trigger, group, status and
  period. It is read-only.
- **S4. Incident page:**
  - an "Alerts" section lists the incident's alerts and their status;
  - the timeline shows `alert_handled` as "Resolved from the alert" and `alert_false_positive` as "Not a
    violation (alert)", each with the moderator.
  - A false-positive closure shows its moderator when `closed_by_user_id` is NULL.
  - Implementation note, 2026-11-15 (T532): the timeline labels follow the panel's existing
    "(panel)" pattern, `Resolved (alert)` and `Not a violation (alert)`; an alert closure, having
    no note, reads its kind in place of the reason.
- **S5. Labels.** `assigned_via` `alert` (items), `alert_handled` and `alert_false_positive` (incidents) read
  "via alert".
- **S6.** `App\Models\Alert` is read-only. It throws on create, update and delete (D-TG-228).
- **S7.** Every new string goes through `__()` with an Arabic entry. No deletion word appears on incident
  screens.

## §8 — Figures (amends `attention-metrics.md` F3)

- **M1.** The attention "My work" split gains `via_alert`, quoted identically in Python (`metrics.py`) and PHP
  (`AttentionMetrics.php`). `via_reply + via_dismissal + via_reaction + via_alert = assigned`.
- **M2.** Incident figures need no SQL change:
  - `alert_handled` is a confirmation, counted by handling-confirmation time like `panel_resolve`;
  - `alert_false_positive` is a false positive through the state view;
  - "My work"'s `assigned_via` gains two labels.
- **M3.** No figure reads `alerts`. No average and no composite score.

## §9 — Never

- **N1.** Send, edit or answer anything addressed to a monitored chat.
- **N2.** Ban, restrict, delete, react or pin, anywhere. The methods do not exist.
- **N3.** Post the same alert twice. At most one delivery per alert (D-TG-215).
- **N4.** Change an item, incident, act or figure by firing, delivering, failing or editing.
- **N5.** Store or log an excerpt or a rendered text.
- **N6.** Trust `callback_data` without its message (B1).
- **N7.** Record an act for a press by anyone but a declared, active moderator.
- **N8.** Back-fill missed repeats, or alert a backlog that predates a rule's enabling.
- **N9.** Read a threshold from code.
- **N10.** Let the panel call Telegram.

## §10 — Limitations

- **L1.** With `ai-telegram` stopped there is no tick, so nothing fires and no presses arrive.
- **L2.** After a poller outage, `group_silent` may fire for groups that were simply unobserved. The
  observation is honest: the system did not see them.
- **L3.** Redaction misses scheme-less links (`t.me/…`) and numbers written in words.
- **L4.** An excerpt that someone copies or forwards outlives the retention edit.
- **L5.** A press's instant is its arrival. A press processed after another route ended its subject records
  nothing, even if it was pressed first.
- **L6.** A mistaken press cannot be undone.
- **L7.** A basic-group source has no message link. A basic-group destination breaks when it becomes a
  supergroup (V5), so create the alert group as a supergroup (quickstart).

## §11 — Verified by

**Python (`tests/moderation/alerts/`):**
- `test_rules_constraints.py`: every CHECK and unique index, planted.
- `test_destination.py`: D1 and D2, both orders.
- `test_evaluate_triggers.py`: F1, per trigger, at the boundaries, with the group-first rule and a muting
  disabled rule.
- `test_evaluate_dedupe.py`: F2, F3, F6 and F8, across two evaluators, a restart and a simulated outage
  (no back-fill).
- `test_enabled_at.py`: FR-515, so a backlog is not alerted.
- `test_quiet_hours.py`: windows across midnight; a suppressed repeat keeps its index; later repeats are sent.
- `test_deliver.py`: V1–V6, including unknown outcome never retried, a migrated destination and a not-sent
  subject.
- `test_press.py`: B1–B6, covering every outcome, two concurrent presses, the team and non-team take, a
  deactivated moderator and forged data.
- `test_refresh.py`: U1–U5, covering an end by each route, the retention crossing and deleted-alert handling.
- `test_alert_views.py`: §5 of `data-model.md`, covering the state view's alert false positive and the take
  branch with its ties.
- `test_alert_glossary.py`: D-TG-222 against `lang/ar.json`.
- `test_alert_render.py`: `alert-messages.md`, covering escaping, durations, links, no deletion word and no
  confidence.
- `test_no_outbound.py`, rewritten: N1, N2 and the one-caller rule.
- `test_metrics.py`, extended: M1.

**PHP:**
- `AlertRuleResourceTest`
- `AlertDestinationTest`
- `AlertsPageTest`
- `IncidentAlertTimelineTest`
- `AlertModelReadOnlyTest`
- the extended `PanelTranslationCoverageTest`
- the extended `IncidentWordingArabicTest`
