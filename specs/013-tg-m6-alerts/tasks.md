# Tasks: TG-M6 — Alerts

**Input**: `specs/013-tg-m6-alerts/`:
- `plan.md`, `spec.md`, `research.md`, `data-model.md`, `quickstart.md`;
- `contracts/alerting.md`, `contracts/alert-messages.md`.

**Tests**: included. The Constitution Check (plan, question 1) and `alerting.md` §11 name them.
- Every Python test runs on `injaz_ai_test`, with Telegram scripted by an `httpx.MockTransport` and no network.
- Every PHP test uses `DatabaseTransactions`.
- Tests move subject timestamps into the past rather than mocking the clock, because the evaluator reads
  `now()`.

**Git**: every branch, commit, push and deploy step belongs to the operator (constitution IV).

**Paths**: Python is under `apps/ai-api/`, PHP under `apps/ai-control/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel: a different file, and no dependency on an unfinished task.
- **[Story]**: US1–US5, from `spec.md`.

---

## Phase 1: Setup

- [X] T501 Add the optional `MODERATION_PANEL_BASE_URL` (data-model §7, D-TG-224).
  - `apps/ai-api/app/infrastructure/config.py`: blank means none; when set, it must be an `http(s)` URL, with
    no trailing slash kept.
  - `.env.example`: blank, with a one-line comment.
  - `infra/docker-compose.yml`: pass it to `ai-worker` and `ai-telegram`.
  - Test, in `apps/ai-api/tests/moderation/test_config_moderation.py`: blank is accepted and a malformed value is
    refused.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the schema, provider methods, pure helpers, rendering, delivery, and the evaluator and refresh
machinery that every story's triggers and presses plug into.

- [X] T502 Write `apps/ai-api/alembic/versions/0013_moderation_alerts.py` (`down_revision = "0012"`) exactly
  per `data-model.md`:
  - **§1:** `telegram_chats.is_alert_destination`, `uq_chat_one_alert_destination` and
    `ck_chat_destination_not_monitored`.
  - **§2:** `alert_rules`, with every CHECK and both partial unique indexes.
  - **§3:** `alerts`, with every CHECK, `uq_alerts_dedupe`, `uq_alerts_posted` and the four indexes.
  - **§4:** `moderation_actions.alert_id` and `ix_actions_alert`. Re-create `ck_actions_type`,
    `ck_actions_strength` and `ck_actions_panel_link`, and add `ck_actions_alert_link` and
    `ck_actions_alert_actor`.
  - **§5.1:** `CREATE OR REPLACE VIEW moderation_incident_state`: the false-positive lateral reads both kinds,
    and `close_kind` and `closed_by_moderator_id` are appended last.
  - **§5.2:** `CREATE OR REPLACE VIEW attention_item_assignee`: the `alert_take` branch, rank 4, via `'alert'`.
  - **§6:** the downgrade restores 0012's constraints and views, drops the rest, and raises while any
    `alert_*` action exists.
- [X] T503 Bring ORM parity to `apps/ai-api/app/infrastructure/models_moderation.py`:
  - new `alert_rules` and `alerts` tables;
  - `telegram_chats.is_alert_destination`;
  - `moderation_actions.alert_id`;
  - the re-created CHECK texts, byte-identical to T502's.
- [X] T504 Create `apps/ai-api/tests/moderation/alerts/__init__.py` and `conftest.py` with:
  - fixtures for a monitored source chat and an unmonitored destination chat (flag set);
  - a declared, active moderator with a `telegram_users` identity and a current team membership;
  - `make_rule(**fields)`, which inserts `alert_rules`;
  - `scripted_telegram`, an `httpx.MockTransport` that records `(method, params)` and returns scripted
    results, wired into a `TelegramClient`;
  - helpers that insert an attention item or incident with past timestamps.
- [X] T505 [P] Write `apps/ai-api/tests/moderation/alerts/test_destination.py`:
  - D1: a second destination is refused;
  - D2: designating a monitored chat is refused, and so is monitoring the destination;
  - clearing the flag, then designating another chat, works.
- [X] T506 [P] Write `apps/ai-api/tests/moderation/alerts/test_rules_constraints.py`. Plant each violation of
  data-model §2–§4 and assert its constraint name:
  - a threshold on `incident_flagged`, or none on `question_waiting`;
  - filters on a health trigger;
  - a repeat interval without a maximum;
  - an enabled rule with no `enabled_at`;
  - a second global rule, or a second rule per chat and trigger;
  - deleting a rule that has alerts (`RESTRICT`);
  - `alerts` with a status/reason or status/message mismatch;
  - a duplicate `dedupe_key`;
  - `alert_handled` without an incident, any `alert_*` act without `alert_id` or without its actor, and a
    `panel_*` act with an `alert_id`.
- [X] T507 [P] Write `apps/ai-api/tests/moderation/alerts/test_alert_views.py`:
  - an `alert_false_positive` row closes an incident: status `closed_false_positive`, `close_kind`,
    `closed_by_moderator_id`, `close_reason` NULL;
  - an `alert_handled` row resolves it as a `confirmation`, so it counts in `first_confirmation_at`;
  - the state view's first 19 columns keep 0012's names and order (`information_schema.columns`);
  - the take branch:
    - a team member's `alert_take` assigns via `'alert'`;
    - a non-team presser assigns nobody;
    - a take after `first_response_at` is ignored;
    - on a tied instant a reaction wins;
  - the downgrade raises with an alert act present, and round-trips cleanly without one.
- [X] T508 Add the outbound methods to `apps/ai-api/app/providers/telegram/client.py` and `errors.py` (D-TG-215).
  - **`send_message(chat_id, text, reply_markup)`** sends HTML with link previews off, and returns
    `message_id`.
  - **`edit_message_text(chat_id, message_id, text, reply_markup | None)`** treats a 400 "message is not
    modified" as success. A 400 "message to edit not found" raises `TelegramMessageGoneError`.
  - **`answer_callback_query(callback_query_id, text)`**.
  - Add them to the `TelegramProvider` Protocol.
  - **`TelegramOutcomeUnknownError`** (category `telegram_outcome_unknown`): `_request` gains an
    `outbound: bool` flag. Only when it is set do these map to the new error: `httpx.ReadTimeout`,
    `WriteTimeout`, `ReadError` and `RemoteProtocolError`. `ConnectError`/`ConnectTimeout` stay
    `TelegramUnreachableError`, and `get_updates` is unchanged.
  - **`TelegramRejectedError`** carries `description` and `parameters`, including `migrate_to_chat_id`.
  - Tests, in `apps/ai-api/tests/moderation/ingest/test_provider_send.py`: each method's request shape;
    not-modified as success; gone; unknown vs connect failure; a 429 waits and retries; migration parameters
    parsed. Existing provider tests still pass.
- [X] T509 Rewrite `apps/ai-api/tests/moderation/ingest/test_no_outbound.py` per D-TG-227.
  - These stay forbidden: `setMessageReaction`, `deleteMessage`, `pinChatMessage`, `banChatMember`,
    `restrictChatMember`, `unbanChatMember`, `banChatSenderChat`, `unbanChatSenderChat`. They are absent from
    the Protocol and the client, and their names are absent from `app/`.
  - `sendMessage`, `editMessageText` and `answerCallbackQuery` appear only in `app/providers/telegram/client.py`.
  - `send_message(`, `edit_message_text(` and `answer_callback_query(` are called only from
    `app/application/moderation/alert_delivery.py`.
  - The PHP `Http::`/`GuzzleHttp`/`curl_` scan and the `setWebhook` checks are kept unchanged.
- [X] T510 [P] Create `apps/ai-api/app/domain/moderation/alerting.py`. It is pure: standard library only,
  `zoneinfo` included, with no I/O and no clock. It holds:
  - the `Trigger` (5), `SubjectType`, `PressAction` (`h`/`f`/`t`) and `PressOutcome` enums (the six
    outcomes of `alerting.md` §5);
  - `parse_quiet_hours(raw)`, which skips a malformed or `from == to` window;
  - `in_quiet_hours(windows, instant)`: `Asia/Riyadh`, `[from, to)`, crossing midnight;
  - `due_repeat_index(first_fired_at, now, every_s, max_repeats)`;
  - `dedupe_key(rule_id, subject_type, subject_id, episode_at, k)`, at most 160 characters;
  - `encode_callback` and `decode_callback`, which reject anything else;
  - `severity_at_least`.

  Add the module to the domain-purity assertion in `apps/ai-api/tests/moderation/test_boundary_checks.py`.
  Tests go in `apps/ai-api/tests/moderation/alerts/test_domain_alerting.py` and `test_quiet_hours.py` (pure
  cases).
- [X] T511 Create `apps/ai-api/app/application/moderation/alert_render.py` per `alert-messages.md` §1–§7.
  - **Inputs:** a frozen `RenderInput` dataclass with no session and no clock.
  - **Functions:**
    - `render_alert(input)` returns `(html, reply_markup)`;
    - `render_state(input)` returns a JSON-able dict of the inputs, never text (D-TG-216);
    - `answer_text(outcome, …)`;
    - `excerpt(first_posted_text, removed, aged_out)`, which uses `app.application.moderation.text.redact`.
  - **Content:** every header, body, status line, duration bucket, mention, link form, keyboard and answer.
  - **Glossary:** a dict keyed by the panel's English keys.
  - **Panel paths:** pin the incident, queue and group URL paths from `php artisan route:list`, and record
    them in `alert-messages.md` §5.
- [X] T512 [P] Write `apps/ai-api/tests/moderation/alerts/test_alert_render.py`:
  - HTML escaping of titles, names and the excerpt;
  - every duration bucket (1, 2, 3, 10, 11, 59 min; 1 h; 2 h 5 min; 1 d; 2 d 3 h);
  - the excerpt cut at a word boundary with `…`, redaction placeholders, "text removed", and no line for
    media without text;
  - the three link forms: public, supergroup, basic group;
  - the panel link, or none;
  - at most 1,000 characters;
  - W1 (no deletion or removal word) over every template and outcome;
  - W2 (no confidence, `%` or probability word);
  - W4 (only moderator mentions).
- [X] T513 [P] Write `apps/ai-api/tests/moderation/alerts/test_alert_glossary.py`: every glossary value equals
  `apps/ai-control/lang/ar.json[key]`. Add the bot-status keys (`member`, `left`, `kicked`, `restricted`,
  `administrator`) to `apps/ai-control/lang/ar.json` if absent.
- [X] T514 Create `apps/ai-api/app/application/moderation/alert_delivery.py`. It is the only provider caller
  (D-TG-227).
  - **`deliver(session_factory, client, alert_id)`** follows V1–V6:
    - the claim is a guarded `UPDATE … RETURNING`;
    - it re-checks through `alerting.subject_live`, and reads the destination row with D2 in the same
      transaction;
    - it sends, then records the posted fields, `rendered_state`, `excerpt_shown` and `final_at` NULL;
    - on failure it records `last_error_category` and a backoff (5 attempts). Unknown outcome is final, and so
      is `destination_migrated`.
  - **`edit(…)`** follows U2/U3. Its guard requires the target to be the alert's own posted chat, not
    monitored.
  - **`answer(…)`**.
  - Log keys are only `alert_id`, `chat_id` and `incident_id`.
- [X] T515 Add `subject_live(session, alert)` and the `RenderInput` builders to
  `apps/ai-api/app/application/moderation/alerting.py`, reading only the derived state:
  - **items:** `attention_items` status and first response, and `attention_item_assignee`;
  - **incidents:** `moderation_incident_state` and `moderation_incident_assignee`;
  - **chats:** the episode, still current and monitored;
  - **team names:** `moderation_team_intervals` at now;
  - **text:** first-posted text via `messages.extract_text` over the anchor's captured event, plus the
    purge markers and the age against `MODERATION_TEXT_RETENTION_DAYS`.
- [X] T516 Write `apps/ai-api/tests/moderation/alerts/test_deliver.py`:
  - success records the fields;
  - a connect failure retries up to 5 times, then stays final;
  - a 5xx retries;
  - unknown outcome is never retried;
  - `migrate_to_chat_id` → `destination_migrated`;
  - no destination → `not_sent / no_destination`;
  - an ended subject → `not_sent / subject_ended`;
  - a suppressed alert is never claimed;
  - the guard refuses a send to anything but the destination and an edit to a monitored chat;
  - every `attention_items`, `moderation_incidents`, `moderation_actions` and view row is identical before and
    after a failed delivery (FR-541).
- [X] T517 Build the evaluator framework in `apps/ai-api/app/application/moderation/alerting.py` (F1–F8):
  - **The rule in force:** a CTE, chat row first; a disabled chat row mutes.
  - **The statement registry:** each trigger's statement (added by the stories) returns `(rule_id, chat_pk,
    subject_type, subject_id, episode_at, qualified_at)`, bounded by `qualified_at >= enabled_at`.
  - **Inserts:** the shared insert builds the dedupe key, the `rule_values` snapshot and the repeat index
    (F3: inserted only if no index ≥ k). It marks quiet-hours firings `suppressed` (F5), and allows one insert
    per subject per run (F6), with `ON CONFLICT DO NOTHING RETURNING id`.
  - **The refresh scan:** for sent alerts with `final_at IS NULL` or `excerpt_shown`, compare the computed
    `render_state` with the stored one.
- [X] T518 Add the actors in `apps/ai-api/app/workers/tasks/moderation/` and enqueue them from the tick.
  - `apps/ai-api/app/workers/tasks/moderation/evaluate_alert_rules.py`: evaluate, `deliver_alert.send` for
    each returned non-suppressed id, `refresh_alert.send` for each changed render state.
  - `deliver_alert.py`.
  - `refresh_alert.py`: renders, edits, sets `final_at` when ended and `excerpt_shown`, and resets or records
    the edit fields.
  - Register them in `apps/ai-api/app/workers/main.py`.
  - In `apps/ai-api/app/telegram_main.py`, the tick's lease winner also enqueues `evaluate_alert_rules`.
  - Extend `apps/ai-api/tests/moderation/attention/test_tick.py`: only the winner enqueues it.

**Checkpoint**: the schema, provider, rendering, delivery and evaluator machinery are in place, and no trigger is
registered yet.

---

## Phase 3: User Story 1 — a question that waits too long reaches the team (P1) 🎯 MVP

**Goal**: one alert for a question waiting past a rule's threshold, delivered only to the alert group, repeated
within bounds, and edited when the question ends.

**Independent test**: one rule and one unanswered item. One alert reaches the scripted destination, a second
cycle, a restart or a replay adds none, nothing reaches any other chat, and the alert is edited on answer.

- [X] T519 [US1] Register the `question_waiting` statement in `apps/ai-api/app/application/moderation/alerting.py`.
  It qualifies on `status = 'open' AND now() - opened_at >= threshold`, and its `qualified_at` is
  `opened_at + threshold` (F1).
- [X] T520 [P] [US1] Write the `question_waiting` cases of `apps/ai-api/tests/moderation/alerts/test_evaluate_triggers.py`:
  - one second short of the threshold → none; at the threshold → one;
  - answered, dismissed or expired → none;
  - a chat rule beats the global one;
  - a disabled chat rule mutes;
  - a disabled global rule → none.
- [X] T521 [P] [US1] Write `apps/ai-api/tests/moderation/alerts/test_evaluate_dedupe.py`:
  - two evaluators via `asyncio.gather` on separate sessions → one alert;
  - a second run → none;
  - repeats every R up to N, at least R apart;
  - a simulated outage (timestamps moved back 3·R) inserts only index 3, never 1 or 2;
  - at most one insert per subject per run;
  - nothing after the item ends.
- [X] T522 [P] [US1] Write `apps/ai-api/tests/moderation/alerts/test_enabled_at.py` (FR-515):
  - an item that crossed the threshold before `enabled_at` → never alerted;
  - one crossing after → alerted;
  - re-enabling stamps a new `enabled_at`;
  - a new chat rule replacing the global one does not re-alert subjects the global rule already alerted.
- [X] T523 [P] [US1] Add integration cases to `apps/ai-api/tests/moderation/alerts/test_quiet_hours.py` (FR-543):
  - a firing inside a window crossing midnight is `suppressed`, never claimed and never sent;
  - a repeat due after the window is sent;
  - no `attention_items` field changes.
- [X] T524 [P] [US1] Write the question cases of `apps/ai-api/tests/moderation/alerts/test_refresh.py`:
  - answered by a moderator, answered by a member, dismissed and expired each edit to `alert-messages.md`
    §6's line, remove the keyboard and set `final_at`;
  - "not modified" counts as success;
  - `TelegramMessageGoneError` → final with `excerpt_shown = false`;
  - an age crossing `MODERATION_TEXT_RETENTION_DAYS` edits the excerpt to "text removed" (FR-535);
  - an unchanged state → no edit;
  - no state changes.
- [X] T525 [US1] Write `apps/ai-api/tests/moderation/alerts/test_silence_end_to_end.py` (SC-501). It drives
  evaluate → deliver → answer the item → refresh, and asserts that every recorded `chat_id` in
  `scripted_telegram` is the destination's.

**Checkpoint**: US1 works alone and is the MVP. It can be demonstrated by a rule inserted by hand in
`alert_rules` and a destination flag set by hand.

---

## Phase 4: User Story 2 — an incident alert is resolved from Telegram (P1)

**Goal**: incident alerts with ✅ and 🚫 that resolve or close the incident like a panel act, and edits when an
incident ends by any route.

**Independent test**: one flagged incident and one scripted press per case. Each case records exactly the
expected act, or none, and the derived state matches.

- [X] T526 [US2] Register the `incident_flagged` and `incident_unhandled` statements in
  `apps/ai-api/app/application/moderation/alerting.py`:
  - state `open` or `acknowledged` from `moderation_incident_state`;
  - filters: `min_severity` through the order, `categories` and `openers` against `moderation_incidents.source`;
  - `qualified_at` is `detected_at`, or `detected_at + threshold`.
- [X] T527 [P] [US2] Write the incident cases of `apps/ai-api/tests/moderation/alerts/test_evaluate_triggers.py`:
  - each filter in and out;
  - resolved or closed → none;
  - the unhandled threshold measured from `detected_at`, not `opened_at`;
  - an acknowledged incident still qualifies;
  - a model-opened incident excluded by `openers`.
- [X] T528 [US2] Create `apps/ai-api/app/application/moderation/alert_press.py` with
  `derive_alert_press(session_factory, update_row_id) -> PressOutcome`, covering `alerting.md` B1–B4 and B6
  for `h`/`f`:
  - the gate on `(message.chat.id, message.message_id)` against `uq_alerts_posted`, plus `decode_callback`
    matching that alert and subject type;
  - the presser via `telegram_users` → `moderators`: `is_active`, `created_at ≤ received_at`;
  - under `incident_lock`, read the state, then insert `alert_handled`/`alert_false_positive` with
    `moderation_incident_id`, `alert_id`, `source_update_id`, the actor and `occurred_at = received_at`, using
    `ON CONFLICT (source_update_id) DO NOTHING`;
  - a re-run returns the same outcome.
- [X] T529 [US2] Wire the press into the pipeline (`process_update.py`, new `answer_alert_press.py`).
  - In `apps/ai-api/app/workers/tasks/moderation/process_update.py`, the `callback_query` branch calls
    `derive_alert_press`, then enqueues `answer_alert_press(update_row_id, outcome)`. Update the module
    docstring.
  - Create `apps/ai-api/app/workers/tasks/moderation/answer_alert_press.py`: it answers through
    `alert_delivery.answer` with `alert_render.answer_text`, ignores and logs "query is too old" by category,
    then runs `refresh_alert` for the pressed alert (B7).
  - Register it in `apps/ai-api/app/workers/main.py`.
- [X] T530 [P] [US2] Write the incident cases of `apps/ai-api/tests/moderation/alerts/test_press.py`:
  - **✅ recorded:** resolved, `resolution_kind = 'alert_handled'`, assigned to the team member;
  - **🚫 recorded:** `closed_false_positive` with its `close_kind`;
  - **outsider:** a non-team active moderator resolves without being assigned;
  - **`not_a_moderator`:** an unknown user, an inactive moderator, and a moderator declared after the press;
  - **`invalid`:** another alert's id in the data, `t` on an incident, a message that is no alert;
  - **`already_ended`;**
  - **races:** two concurrent presses → one act; re-running one update → one act and the same outcome;
  - **no side effects:** `derive_alert_press` makes no Telegram request; the answer actor sends the answer
    for each outcome.
- [X] T531 [P] [US2] Write the incident cases of `apps/ai-api/tests/moderation/alerts/test_refresh.py`. An end by
  each route edits to the right `{actor}` and `{how}` (`alert-messages.md` §6), with the keyboard removed. The
  routes are:
  - ban, expulsion and restriction evidence;
  - a 👀 confirmation;
  - `panel_resolve` and `panel_false_positive`, by a linked and an unlinked user;
  - `alert_handled`;
  - an anonymous administrator.
- [X] T532 [P] [US2] Add the panel labels for the incident kinds (`apps/ai-control/app/Filament/`):
  - `apps/ai-control/app/Filament/Resources/Incidents/Support/IncidentDisplay.php`: `alert_handled` →
    "Resolved (alert)", `alert_false_positive` → "Not a violation (alert)";
  - `apps/ai-control/app/Filament/Support/TeamAssignment.php`: both → "via alert";
  - `apps/ai-control/app/Filament/Resources/Incidents/Schemas/IncidentInfolist.php`: a false-positive closer
    reads `closed_by_moderator_id` when `closed_by_user_id` is NULL, and the timeline names the moderator;
  - `apps/ai-control/lang/ar.json` entries;
  - test: `apps/ai-control/tests/Feature/IncidentAlertTimelineTest.php`, seeding alert act rows directly.

**Checkpoint**: US1 and US2 both work, and an incident can be resolved from Telegram.

---

## Phase 5: User Story 3 — "I'm on it" takes a question from its alert (P2)

**Goal**: a press takes an open question without closing it. The assignment follows TG-M2.1, and the alert and
its repeats name the taker.

**Independent test**: one open item and scripted presses. Check the assignment, that the item stays open, the
edited alert and the next repeat's wording.

- [X] T533 [US3] Add the `t` branch to `apps/ai-api/app/application/moderation/alert_press.py` (B5):
  - under the source chat's `chat_lock`, an item with `status <> 'open'` → `already_ended`;
  - otherwise insert `alert_take`, then report `recorded`, `recorded_not_team` (not on the team at the
    instant, via `moderation_team_intervals`) or `already_taken` (`attention_item_assignee` names someone
    else).
- [X] T534 [P] [US3] Write the take cases of `apps/ai-api/tests/moderation/alerts/test_press.py`:
  - a team member takes it: assigned via `'alert'`, and `status`, `first_response_at` and `opened_at` are
    unchanged;
  - a non-team take is recorded and assigns nobody;
  - a second presser's take is recorded, the assignee stays the first, and the answer names them;
  - after an answer → `already_ended`;
  - an inactive moderator → nothing;
  - the refreshed alert reads "🙋 يتولّاه …" and keeps its keyboard;
  - the next repeat's responsible line names the assignee.
- [X] T535 [US3] Add `via_alert` to the attention "My work" split (`alerting.md` M1), with identical SQL in
  `apps/ai-api/app/application/moderation/metrics.py` and
  `apps/ai-control/app/Filament/Pages/Concerns/AttentionMetrics.php`.
  - `apps/ai-control/app/Filament/Support/TeamAssignment.php`: `alert` → "via alert", with its `ar.json`
    entry.
  - Tests: extend `apps/ai-api/tests/moderation/incidents/test_team_assignment.py` (the via counts sum to
    `assigned`) and `apps/ai-control/tests/Feature/TeamAssignmentPanelTest.php`.

---

## Phase 6: User Story 4 — the operator sets the rules and reads the alert history (P2)

**Goal**: the panel's Alert Rules, the destination setting, the Alerts history and the incident page's alerts.

**Independent test**: create, edit and disable rules through the panel, and confirm `alert_rules` follows. Plant
a failed alert and confirm the history shows its reason.

- [X] T536 [P] [US4] Create `apps/ai-control/app/Models/AlertRule.php`:
  - casts for the JSON fields;
  - validation mirroring R1–R8, including quiet hours as `HH:MM` with `from ≠ to`, and monitored chats only;
  - a `saving` hook that stamps `enabled_at` when `is_enabled` goes from false to true;
  - `deleting` throws when alerts exist (D-TG-212, backed by `RESTRICT`).
- [X] T537 [P] [US4] Create `apps/ai-control/app/Models/Alert.php`, read-only. `creating`, `updating` and
  `deleting` throw (D-TG-228). Add its relations to the rule, chat and acts.
- [X] T538 [US4] Create `apps/ai-control/app/Filament/Resources/AlertRules/`:
  - `AlertRuleResource.php`;
  - `Pages/{ListAlertRules,CreateAlertRule,EditAlertRule}.php`;
  - `Schemas/AlertRuleForm.php`: the trigger select drives the visible fields; the threshold is entered in
    minutes and stored in seconds; the group select offers monitored groups only; a repeater for the
    quiet-hours windows; the FR-515 helper line (S1);
  - `Tables/AlertRulesTable.php`: trigger, scope, threshold, filters, repeats, quiet hours, enabled and
    `enabled_at`;
  - no delete action anywhere;
  - navigation in the Moderation Intelligence group.
- [X] T539 [US4] Add the destination to the Telegram Groups resource (`apps/ai-control/app/Filament/Resources/TelegramChats/`, S2).
  - `apps/ai-control/app/Filament/Resources/TelegramChats/Tables/TelegramChatsTable.php`: "Use as alert
    destination" on unmonitored chats, "Stop using" on the destination, and a destination badge column.
  - `Schemas/TelegramChatForm.php` and `apps/ai-control/app/Models/TelegramChat.php`: monitoring is refused for
    the destination, with a notification. D2 backs this.
- [X] T540 [US4] Create `apps/ai-control/app/Filament/Pages/Alerts.php`, with a blade if the page needs one (S3):
  - read-only, paged at 10, newest first;
  - filters: rule, trigger, group, status and period, in `Asia/Riyadh` days;
  - columns: rule, trigger, group, a subject link to the incident page or the queue, repeat `k of N`, status
    with its reason or error category, fired, delivered and presses.
- [X] T541 [US4] Add an "Alerts" section to `apps/ai-control/app/Filament/Resources/Incidents/Schemas/IncidentInfolist.php`.
  It lists the incident's alerts with status and presses (S4).
- [X] T542 [US4] Add `apps/ai-control/lang/ar.json` entries for every new US4 string.
  - Extend `apps/ai-control/tests/Feature/PanelTranslationCoverageTest.php` if it needs the new files.
  - Extend `IncidentWordingArabicTest` to the new incident strings.
- [X] T543 [US4] Write the feature tests in `apps/ai-control/tests/Feature/`:
  - `AlertRuleResourceTest.php`: each refusal; `enabled_at` stamping; a chat rule muting; no delete action;
    only monitored groups offered;
  - `AlertDestinationTest.php`: designate; refuse a monitored chat; refuse monitoring the destination; one at a
    time;
  - `AlertsPageTest.php`: rows, filters, paging, and no edit action;
  - `AlertModelReadOnlyTest.php`.

---

## Phase 7: User Story 5 — group health alerts (P3)

**Goal**: one alert when a monitored group goes silent or the bot loses administrator, edited on recovery.

**Independent test**: move a monitored chat's `last_event_at` and `bot_status` and check each alert and its edit.

- [X] T544 [US5] Register the `group_silent` and `bot_not_admin` statements in
  `apps/ai-api/app/application/moderation/alerting.py` (D-TG-214):
  - episodes are `last_event_at` and `bot_status_at`;
  - `bot_status NOT IN ('administrator', 'unknown')`;
  - monitored chats only.
- [X] T545 [P] [US5] Write the health cases of `apps/ai-api/tests/moderation/alerts/test_evaluate_triggers.py`
  and `test_refresh.py`:
  - the silence boundary;
  - a newer event edits the alert to "عاد النشاط …";
  - a later silence is a new episode and alerts again;
  - a status change to `left` alerts;
  - `unknown` never alerts;
  - administrator again edits the alert;
  - an unmonitored chat never alerts;
  - the alert group itself never alerts.

---

## Phase 8: Polish and cross-cutting

- [X] T546 Add D5 to `apps/ai-api/app/scripts/tg_doctor.py`:
  - whether a destination is designated;
  - `getChatMember` for the bot there, which must be `member` or `administrator` and able to send;
  - that it is not monitored.

  Test it in `apps/ai-api/tests/moderation/ingest/test_tg_doctor.py`.
- [X] T547 [P] Add the dated "Amended by TG-M6" notes (`specs/004…012/contracts/`, the master plan):
  - `specs/004-tg-m1-telegram-ingestion/contracts/telegram-provider.md` §8;
  - `specs/005-tg-m2-groups-and-ownership/contracts/message-derivation.md` §1;
  - `specs/007-tg-m4-policy-incidents/contracts/incident-lifecycle.md` §2 and §5;
  - `specs/006-tg-m3-response-tracking/contracts/attention-metrics.md` (F3, `via_alert`);
  - `specs/012-tg-m2-1-group-teams/contracts/group-teams.md` (G1/G2);
  - `docs/plan/telegram/telegram-moderation-intelligence.md` §10.12, §16, §25 TG-M6 and §28 items 6–7
    (answered 2026-11-12).
- [X] T548 [P] Update `docs/runbooks/tg-operator-prerequisites.md`: in the TG-M6 rows, the destination is set in
  the panel, quiet hours are per rule, and the language is Arabic. Update `docs/runbooks/production-deployment.md`:
  `MODERATION_PANEL_BASE_URL` and `tg-doctor`'s destination line.
- [X] T549 [P] Check that a rollback works. At commit `79e7898`, read how `IncidentDisplay::kindLabel`,
  `TeamAssignment::viaLabel` and the incident infolist handle an unknown `action_type`/`assigned_via`.
  Record the result in `specs/013-tg-m6-alerts/quickstart.md` §5. If they throw, say "downgrade first" there.
- [X] T550 Update the TG-M6 status in `CLAUDE.md`. Run `make check` and record the result line on this task:
  ruff, architecture, mypy, pytest, PHP, secret scan.
  - **2026-11-15, `make check` exit 0:** ruff clean · architecture and moderation boundary clean · mypy clean
    (104 files) · pytest 1845 passed, 9 skipped, 2 deselected · PHP OK (278 tests, 3941 assertions) · secret
    scan OK · ALL CHECKS PASSED.
- [X] T551 *(operator)* Run the development probes P1–P5 (`quickstart.md` §1), and record the outcomes in
  `specs/013-tg-m6-alerts/research.md` §0b. If P2 refuses, the panel link moves into the text, as
  `alert-messages.md` §5 already allows.
  - **2026-11-23:** the operator reports done. The results are in research §0b: P2 accepted, and P5's
    migration finding fixed in the panel.
- [X] T552 *(operator)* Run the development smoke (`quickstart.md` §2), including reading the student group.
  - **2026-11-23:** the operator reports done. Development holds four sent alerts, every one edited to its
    final state, plus all three press kinds.
- [ ] T553 *(operator)* Go live in production (`quickstart.md` §4): `pg_dump`, deploy `0013`, set
  `MODERATION_PANEL_BASE_URL`, designate the group, `tg-doctor`, the first rules, then read every student
  group the next day.

---

## Dependencies and execution order

- **Setup (T501)**: none.
- **Foundational (T502–T518)**: depends on Setup. It **blocks every story**.
  - T502 comes first, then T503 and T504.
  - T505, T506 and T507 can run in parallel after T504.
  - T508, then T509.
  - T510 and T511 can run in parallel. T512 and T513 follow T511.
  - T514 and T515 need T508, T510 and T511. T516 needs both.
  - T517 needs T515, and T518 needs T514 and T517.
- **US1 (T519–T525)**: after Foundational. This is the MVP.
- **US2 (T526–T532)**: after Foundational. It reuses US1's tested framework but none of its code, so it can run
  beside US1. T532 is PHP and can run in parallel throughout.
- **US3 (T533–T535)**: after US2's T528 and T529, which provide the press pipeline it extends.
- **US4 (T536–T543)**: needs only the schema (T502). It can run in parallel with the Python stories.
- **US5 (T544–T545)**: after Foundational. It is independent of US1–US4.
- **Polish (T546–T553)**: after the stories it documents. T551–T553 are the operator's, in order, after T550.

## Parallel examples

- **After T504:** T505, T506 and T507 together (three test files).
- **After T511:** T512 and T513 together.
- **US1:** T520, T521, T522, T523 and T524 together (separate test files, all over T519).
- **US2 with US4:** one stream does T526–T531 (Python); another does T532 and T536–T543 (PHP).
- **Polish:** T547, T548 and T549 together (separate documents).

## Implementation strategy

1. **MVP:** Setup, Foundational, then US1. Stop and demonstrate it with a hand-made rule and destination:
   - one question alert;
   - no duplicates;
   - the edit on answer;
   - silence everywhere else.
2. **Add US2:** incident alerts and ✅/🚫. This is the team's daily use today, since the queue is paused.
3. **Add US4:** the operator can now manage rules without SQL. This is the minimum for production.
4. **Add US3 and US5**, in either order.
5. **Polish**, then the operator's probes, smoke and go-live.
