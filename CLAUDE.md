<!-- SPECKIT START -->
Active feature: **TG-M4 — Policy Incidents** (`specs/007-tg-m4-policy-incidents/`)

Read before working on this feature:

- `specs/007-tg-m4-policy-incidents/plan.md` — implementation plan, Constitution Check, the three operator items (**all approved 2026-09-24**)
- `specs/007-tg-m4-policy-incidents/spec.md` — requirements (FR-001…FR-087), success criteria, 3 clarifications
- `specs/007-tg-m4-policy-incidents/research.md` — 31 decisions (D-TG-98…D-TG-128), 9 probes, **4 findings**
- `specs/007-tg-m4-policy-incidents/data-model.md` — revision `0006`: two tables, **two views**, the derived state machine
- `specs/007-tg-m4-policy-incidents/contracts/incident-lifecycle.md` — **the** TG-M4 contract: opening (I1–I7), evidence (V1–V15, the membership table), linkage (L1–L7), derived state (S1–S6), the guard (H1–H7), attribution (A1–A5), re-derivation (R1–R5), what may never happen (N1–N8)
- `specs/007-tg-m4-policy-incidents/contracts/incident-metrics.md` — the exact SQL behind every incident figure (M1–M19)
- `specs/007-tg-m4-policy-incidents/contracts/control-panel-incidents.md` — the Incidents resource, its actions, the wording rule, config
- `specs/007-tg-m4-policy-incidents/quickstart.md` — walkthrough, the evidence check, the runbook smoke test, 13 known limitations

This is the fifth milestone of a **second bounded domain**. Its source plan of record is
`docs/plan/telegram/telegram-moderation-intelligence.md` (TG-M0…TG-M10); the operator's human steps are
`docs/runbooks/tg-operator-prerequisites.md` — **§C's TG-M4 row (a disposable third account in the dev
group, willing to be restricted and banned) is the smoke-test prerequisite**, on top of §B and the
TG-M2 row (the operator's own account mapped as a moderator of the dev group). Every automated test runs
without any of them.

TG-M4 records **what moderators observably did about a flagged message** with **zero AI**: no model
call, no automatic opening, no alert, no outbound message, no bot action of any kind. Only operators open
incidents here (`source='operator'`; `ai` is reserved for TG-M5). Alembic revision `0006` is consumed;
`0007`–`0009` stay reserved.

The rules that carry this milestone:

- **Seeing is not acting.** A moderator's reaction or direct reply is *acknowledgement*; only
  enforcement (ban / expulsion / restriction of the sender, as the platform reports it) or a panel
  confirmation *resolves*. No acknowledgement kind carries a resolving strength — `ck_actions_strength`.
- **Nothing is ever called a deletion.** Telegram reports none and never its author. The standing
  sentence — *"Telegram does not report message deletion in groups; no removal evidence is available."* —
  is on every incident page, and a test fails any other `delet`/`remov` substring on those screens. The
  membership kind is `expulsion`, never `removal`, for exactly that reason.
- **State is derived, never stored.** An incident row holds only what was decided at the flag (anchor,
  `opened_at` = posting, `detected_at` = flag, labels, opener, responsible-at-detection). Status, moments
  and timings come from the views `moderation_incident_evidence` and `moderation_incident_state` — **the
  only definitions**, read by Python and PHP alike. Never compute a status in code (contract N6).
- **Human acts are guarded inserts under one lock.** Acknowledge / resolve / not-a-violation: take
  `pg_advisory_xact_lock(hashtext('moderation:incidents'))` (this exact literal, both languages), read the
  status from the view, insert or do nothing. Membership-evidence inserts take the same lock. The guard
  lives on `ModerationIncident` and is load-bearing (probe 8).
- **`moderation_actions` is append-only** — no `UPDATE`, no `DELETE`, ever.

Four measured facts that drive this design (see research.md §0):

1. ⚠ **The platform puts a fake `from` on every message sent on behalf of a chat, and TG-M2's
   `ck_telegram_messages_sender` rejects that row** — channel spam is never stored. Fix (D-TG-99): when
   `sender_chat` is present, ignore `from`. Edits a TG-M2 module — operator item 2, **approved**.
2. ⚠ **The running panel's percentile floor is 0**: `.env` lacks the key, Compose passes `''`, and
   `(int) env(…, 10)` is `0`. The new `MODERATION_INCIDENT_MAX_AGE_S` would inherit the trap. Fix
   (D-TG-122): `${KEY:-default}` in Compose, blank-safe `config/moderation.php` — operator item 3, **approved**.
3. ⚠ **The panel cannot run the Python matcher**, and TG-M3's hand-open already shows the disagreement
   (it skips the lookback — recorded, not fixed). Hence state-as-views — operator item 1, **approved**, a
   correction to §10.8.
4. ⚠ **No `chat_member` or `message_reaction` event has ever been captured** in dev. Every payload shape is
   pinned by `test_membership_classifier.py` against the Bot API reference; the smoke test first proves
   both kinds land. Anonymous-administrator performers are unverified live.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1);
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/`, and `app/`-root files such as `app/telegram_main.py` — are exempt **by directory**);
- **no Telegram SDK** outside `app/providers/telegram/`, and the provider exposes **no** ban / restrict /
  delete / react method;
- **no message text in any log line** (check 4). Correlation keys: `incident_id`, `message_id`,
  `update_id`, `chat_id` — never `message` (TG-M0's D-TG-24);
- **`app/domain/moderation/{attention,incident}.py` stay pure**: no I/O, no clock, no session.

Panel rules: Alembic owns the schema — **no migration from Filament**; no platform call, no model call,
no bulk action, **no average and no composite score anywhere** (tested); **no state computed in PHP**.
Feature tests use `DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase`,
`DatabaseMigrations` or `migrate:fresh`. No `GRANT` in a migration: the migrator's default ACL reaches
`ai_control` for tables **and views** (probe 6). Arabic content keeps `dir="auto"` **per field**; the
panel locale and chrome stay English and LTR.

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`,
`specs/002-m1-model-gateway/`, `specs/003-tg-m0-moderation-foundation/`,
`specs/004-tg-m1-telegram-ingestion/`, `specs/005-tg-m2-groups-and-ownership/`,
`specs/006-tg-m3-response-tracking/`. The M1 gateway is untouched. Consumed here: TG-M1's captured
`chat_member` / `message_reaction` events and `process_update`, TG-M2's `upsert_identity`,
`_is_declared_moderator`, `responsible_at` and `rederive_chat.py`, and TG-M3's anchor rule (Finding 2),
percentile floor, figures-on-own-page pattern and the Live Attention Queue (one row action added).

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
