# Implementation Plan: TG-M6 — Alerts

**Branch**: not yet created. Suggested name `m6/alerts`; creating it is the operator's (constitution IV).
Planning ran on `main` with no commit.
**Date**: 2026-11-12
**Spec**: `spec.md` (clarified 2026-11-12)
**Contracts**: `contracts/alerting.md` (the contract) and `contracts/alert-messages.md` (the wording)
**Plan of record**: master plan §16, §10.12 and §25 TG-M6, with its 2026-10-21 operator decision

## Summary

- **The destination.** The operator marks one unmonitored chat as the **alert destination**. A flag and two
  database constraints make "never a student group" a schema fact.
- **Rules.** Rules are rows. On each tick, `evaluate_alert_rules` runs one set-based statement per trigger over
  the existing derived views. It inserts alerts idempotently by `dedupe_key`, and `deliver_alert` posts each
  new one at most once.
- **Buttons.** A press arrives through the poller that already captures it. `process_update` derives it into a
  `moderation_actions` row of a new kind under the incident or chat lock. A separate actor answers the press.
- **Edits.** Every alert edit is driven by the tick, comparing the subject's derived state with the alert's
  stored render inputs. This covers every route an item or incident can end by, and means the panel never has
  to call Telegram.
- **Text.** Alerts are Arabic. They carry a redacted 100-character excerpt of the first-posted text. Nothing
  stores or logs that excerpt, and an edit removes it at the retention age.

## Technical Context

- **Language/Version:** Python 3.12 (`apps/ai-api`) and PHP 8.4 / Laravel 12 / Filament 5 (`apps/ai-control`),
  both existing.
- **Primary Dependencies:** the existing ones (httpx, SQLAlchemy async, Alembic, Dramatiq, Filament). Nothing is
  added.
- **Storage:** PostgreSQL, through one revision, `0013_moderation_alerts` (`data-model.md`).
- **Testing:**
  - pytest on `injaz_ai_test`, with the Telegram provider scripted by an `httpx` mock transport and no network;
  - PHPUnit feature tests with `DatabaseTransactions`;
  - `make check`.
- **Target Platform:** Docker Compose in development; the Contabo production host.
- **Project Type:** a web service and workers, plus an admin panel.
- **Performance Goals:**
  - an alert posted within one minute of qualifying (SC-503);
  - edits within one tick of a subject ending (SC-504).
- **Constraints:**
  - no message text, excerpt or rendered alert text in any log;
  - no state computed in PHP;
  - no average or composite score;
  - bilingual panel strings and Arabic-only alerts;
  - the panel never calls Telegram.
- **Scale/Scope:** a handful of groups and tens of items and incidents a day. That is far below Telegram's
  ~20 messages a minute per group.
- **Unknowns:** none block design. Five platform probes (research §0b, P1–P5) run in development before
  go-live (quickstart §1).

## Constitution Check

*It must pass before Phase 0, and again after the Phase 1 design. It passes both times.*

**1. Which behaviours need tests, and which are exempt (I)?**
- **Tested** (contract, safety and business rules; `contracts/alerting.md` §11):
  - **The silence guarantee:** the destination constraints both ways, the rewritten `test_no_outbound.py`, and
    the runtime send/edit guard.
  - **Firing:** every trigger at its boundaries, the group-first rule and muting, dedupe across two evaluators,
    a restart, no back-fill after an outage, FR-515's backlog rule, and quiet hours across midnight.
  - **Delivery:** claim, retry, the unknown outcome never retried, a migrated destination, a subject that ended
    before delivery, and that no state or figure changes.
  - **Presses:** every gate outcome, forged data, a deactivated moderator, concurrent presses, the team and
    non-team take, and idempotent re-runs.
  - **The view changes:** an alert false positive, and the take branch with its ties.
  - **Edits:** an end by each route, the retention crossing, and a deleted alert.
  - **Wording:** the excerpt cut and redaction, durations, escaping, no deletion or confidence word, and the
    glossary equal to `lang/ar.json`.
  - **The panel:** rule validation, the destination action, the read-only `Alert` model, the incident
    timeline, translation coverage, and the Arabic wording test.
  - **Figures:** `via_alert` in both languages.
- **Exempt:** the Filament layout and badge colours, and Telegram's own rendering of HTML (probed by hand,
  quickstart §1).

**2. Do any tests touch a database (II)?** Yes, `injaz_ai_test` only, through the existing fixtures. PHP uses
`DatabaseTransactions`, never `RefreshDatabase` or `migrate:fresh`.

**3. Anything inside `injazedu/` (III)?** No.

**4. Any Git actions (IV)?** None by the agent. These are the operator's steps:
- creating `m6/alerts`;
- every commit, push and PR;
- the production deploy.

Spec Kit's commit hooks are surfaced only.

**5. Is every task traceable to the spec (V)?**

| Work | Traces to |
|---|---|
| The destination flag and constraints, the `tg-doctor` check | FR-501–FR-504, FR-544 |
| `alert_rules`, the Alert Rules resource | FR-510–FR-515, FR-570 |
| The evaluator and the trigger statements | FR-520–FR-524 |
| Rendering, glossary, excerpt, mentions, links | FR-530–FR-536 |
| `deliver_alert`, provider sends, the guard, quiet hours | FR-540–FR-543 |
| Press derivation, the three act kinds, the view changes, `answer_alert_press` | FR-550–FR-557 |
| `refresh_alert` and the retention edit | FR-560–FR-562, FR-535 |
| The Alerts page, incident page, labels, translations | FR-571–FR-575 |
| `via_alert` | FR-580 |
| Contract amendment notes | spec Provenance |

**Post-design re-check.** The design adds no service, queue or dependency (D-TG-226). It adds one non-secret
key, `MODERATION_PANEL_BASE_URL`, which is not a threshold or destination, so TG-M0's environment contract
holds. No principle is touched, and the gate still passes.

## Project Structure

**Python** (`apps/ai-api/`)
- `alembic/versions/0013_moderation_alerts.py`, and ORM parity in `app/infrastructure/models_moderation.py`.
- `app/providers/telegram/client.py` and `errors.py`:
  - `send_message`, `edit_message_text` and `answer_callback_query` on the Protocol and the client;
  - `TelegramOutcomeUnknownError`, which separates connect-phase failures from failures after the request was
    written (D-TG-215);
  - the error carries Telegram's `parameters` (`migrate_to_chat_id`).
- `app/domain/moderation/alerting.py`, pure:
  - the trigger and outcome enums;
  - `in_quiet_hours`, `due_repeat_index`, `dedupe_key`;
  - `encode_callback`/`decode_callback`;
  - `severity_at_least`.
- `app/application/moderation/`:
  - `alerting.py`: the five trigger statements, `evaluate`, the refresh scan;
  - `alert_delivery.py`: the only provider caller; claim, guard, send, edit, answer;
  - `alert_press.py`: `derive_alert_press`, the gate;
  - `alert_render.py`: the templates, glossary, durations and excerpt;
  - `metrics.py`: `via_alert`.
- `app/workers/tasks/moderation/`:
  - `evaluate_alert_rules.py`, `deliver_alert.py`, `refresh_alert.py` and `answer_alert_press.py`, all new;
  - `process_update.py`: the `callback_query` branch.
- `app/telegram_main.py`: the tick also enqueues `evaluate_alert_rules`.
- `app/workers/main.py`: the four actors are registered.
- `app/scripts/tg_doctor.py`: the destination check.
- `app/infrastructure/config.py`: `MODERATION_PANEL_BASE_URL`.
- `tests/moderation/alerts/`, new: the files listed in `alerting.md` §11.
- `tests/moderation/ingest/test_no_outbound.py`, rewritten (D-TG-227).

**Panel** (`apps/ai-control/`)
- Models:
  - `AlertRule`, writable, with validation mirroring R1–R8 and `enabled_at` stamping;
  - `Alert`, read-only;
  - `TelegramChat`, with the destination action and the monitoring guard;
  - `ModerationAction`, with the new kinds.
- `Filament/Resources/AlertRules/`, new: the resource, pages, form and table.
- `Filament/Pages/Alerts.php`, new, with its blade.
- `Filament/Resources/TelegramChats/Tables/TelegramChatsTable.php`: the destination actions.
- `Filament/Resources/Incidents/Schemas/IncidentInfolist.php` and `Support/IncidentDisplay.php`: the alerts
  section, timeline labels and closer moderator.
- `Filament/Support/TeamAssignment.php`: the via labels.
- `Filament/Pages/Concerns/AttentionMetrics.php`: `via_alert`.
- `lang/ar.json`, and the feature tests listed in `alerting.md` §11.

**Infra and docs**
- `.env.example` and `infra/docker-compose.yml`: `MODERATION_PANEL_BASE_URL` for `ai-worker` and `ai-telegram`.
- Dated amendment notes in:
  - `specs/004…/contracts/telegram-provider.md` §8;
  - `specs/005…/contracts/message-derivation.md` §1;
  - `specs/007…/contracts/incident-lifecycle.md` §2 and §5;
  - `specs/006…/contracts/attention-metrics.md` (F3);
  - `specs/012…/contracts/group-teams.md` (G1/G2);
  - master plan §10.12, §16 and §25.
- `docs/runbooks/production-deployment.md`: `tg-doctor`'s destination line.
- `CLAUDE.md`: the active feature.

## Implementation order

1. **Schema:** revision 0013, ORM parity, and the view tests (§5) with constraint plants.
2. **Provider:** the three methods, `TelegramOutcomeUnknownError`, and the rewritten silence test.
3. **Pure domain helpers** and `alert_render.py`, with the glossary test against `lang/ar.json`.
4. **The evaluator and delivery:** triggers, dedupe, quiet hours, `deliver_alert`, the guard. US1 can be
   demonstrated here with `question_waiting`.
5. **Presses and refresh:** derivation, answer, refresh, and the retention edit. US2 and US3.
6. **Health triggers.** US5.
7. **Panel:** rules, destination, Alerts page, incident page, labels, `via_alert`, translations. US4.
8. **Wrap-up:** `tg-doctor`, configuration, the contract notes, the quickstart probes, then `make check`.

## Complexity Tracking

- **Two views are replaced** (`CREATE OR REPLACE`, columns only appended), not added. The alternative was new
  "v2" views and moving every reader, which would put two definitions of incident state live at once (N6).
- **The provider gains outbound methods.** This is the milestone's purpose, and every prior contract reserved
  it for TG-M6. The provider still has no ban, restrict, delete, react or pin method, and one module is the
  only caller (D-TG-227).
