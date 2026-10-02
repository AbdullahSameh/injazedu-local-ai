# Data Model: TG-M5 — AI Classification

**Feature**: `specs/008-tg-m5-ai-classification`
**Revision**: `0007_moderation_classification` — down-revision `0006`, confirmed head in both databases
(research probe 9). `0008`–`0009` stay reserved for TG-M6…TG-M8.

Two tables created; one check widened; one column and four constraints added to `moderation_incidents`; one
foreign key added to `attention_items`. Alembic owns all of it; the panel owns none of it. Every statement
below ran exactly as written, as `ai_migrator`, inside `BEGIN … ROLLBACK` in `injaz_ai_test`, and twelve
planted violations were each rejected by the constraint named for them (research probe 9).

The shape follows the spec's one discipline: **a prediction is a claim, recorded once with its provenance and
never changed**. What the system then did with it — the route, the thresholds in force, the path — is written
beside it at the same moment and never revisited. Whether a message "was already flagged" is not written
anywhere: it is the observable fact that its incident does not cite this prediction.

---

## §1 — `model_profiles` — one more role

```sql
ALTER TABLE model_profiles DROP CONSTRAINT ck_model_profiles_role;
ALTER TABLE model_profiles ADD CONSTRAINT ck_model_profiles_role
  CHECK (role IN ('llm', 'embedding', 'moderation'));
```

Nothing else changes. `uq_model_profiles_one_active_per_role` already gives exactly one active classification
model (probe 9 E9); `ck_model_profiles_dim` already requires `dim IS NULL` for a non-embedding role. The seed
row (`make seed-profiles`, D-TG-129):

| name | provider | model | role | params | is_active |
|---|---|---|---|---|---|
| `ollama-gemma4-e2b-moderation` | `ollama` | `gemma4:e2b-it-qat` | `moderation` | `{"num_ctx": 2048, "num_predict": 128, "temperature": 0, "reasoning_effort": "none"}` | **false** |

---

## §2 — `message_classifications` — immutable predictions

One model's claim about one message. Source plan §10.10, anchored like TG-M3's items and TG-M4's incidents
on `(telegram_chat_id, telegram_message_id)` — the platform numbers messages per chat (TG-M3 Finding 2).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | the message's **platform** id, per chat |
| `model_profile_id` | bigint | no | FK → `model_profiles.id` `ON DELETE RESTRICT` — a profile that ever predicted cannot be deleted |
| `model_run_id` | bigint | yes | FK → `model_runs.id` `ON DELETE SET NULL`. NULL only when M1's accounting write failed (research Finding 6) |
| `prompt_version` | varchar(40) | no | the instruction file's stem — `classify_v1` or `classify_v2`, whichever `MODERATION_PROMPT_VERSION` named when the prediction was made (D-TG-136, D-TG-163). Not a FK: `prompt_versions` does not exist (§10.10) |
| `taxonomy_version` | smallint | no | `1` (D-TG-08) |
| `category` | varchar(30) | no | the seven categories, D-TG-08's spelling |
| `needs_response` | boolean | no | |
| `needs_moderation` | boolean | no | |
| `severity` | varchar(10) | no | `none` \| `low` \| `medium` \| `high` |
| `confidence` | numeric(4,3) | no | the model's self-report, quantised half-up to three places **before** routing (D-TG-135) |
| `path` | varchar(20) | no | `live` (the actor) \| `catch_up` (the operator's command) |
| `route` | varchar(20) | no | what the system did with it — `incident` \| `possible_violation` \| `review` \| `none` \| `measurement_only` (D-TG-142) |
| `route_reason` | varchar(20) | yes | `uncertain` \| `inconsistent`; present exactly when `route = 'possible_violation'` |
| `confidence_floor` | numeric(4,3) | yes | the floor in force when routed; NULL on the catch-up path |
| `incident_threshold` | numeric(4,3) | yes | the threshold in force when routed; NULL on the catch-up path |
| `is_current` | boolean | no | default `true`. Always true in this milestone; TG-M8's reprocessing flips it |
| `created_at` | timestamptz | no | `server_default now()` — the moment the prediction was made |

**No message text, in any form** (FR-016). **No `UPDATE`, no `DELETE`**, from any code path (D-TG-147).

### DDL

```sql
CREATE TABLE message_classifications (
  id                  bigserial PRIMARY KEY,
  telegram_chat_id    bigint       NOT NULL REFERENCES telegram_chats (id),
  telegram_message_id bigint       NOT NULL,
  model_profile_id    bigint       NOT NULL REFERENCES model_profiles (id) ON DELETE RESTRICT,
  model_run_id        bigint       NULL REFERENCES model_runs (id) ON DELETE SET NULL,
  prompt_version      varchar(40)  NOT NULL,
  taxonomy_version    smallint     NOT NULL,
  category            varchar(30)  NOT NULL,
  needs_response      boolean      NOT NULL,
  needs_moderation    boolean      NOT NULL,
  severity            varchar(10)  NOT NULL,
  confidence          numeric(4,3) NOT NULL,
  path                varchar(20)  NOT NULL,
  route               varchar(20)  NOT NULL,
  route_reason        varchar(20)  NULL,
  confidence_floor    numeric(4,3) NULL,
  incident_threshold  numeric(4,3) NULL,
  is_current          boolean      NOT NULL DEFAULT true,
  created_at          timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT fk_classification_message FOREIGN KEY (telegram_chat_id, telegram_message_id)
    REFERENCES telegram_messages (telegram_chat_id, message_id),
  CONSTRAINT uq_classification_identity UNIQUE (id, telegram_chat_id, telegram_message_id),
  CONSTRAINT ck_classification_category CHECK (category IN
    ('QUESTION_COURSE','QUESTION_ACCESS','COMPLAINT','CHITCHAT','SPAM_OR_AD','ABUSE','OTHER')),
  CONSTRAINT ck_classification_severity CHECK (severity IN ('none','low','medium','high')),
  CONSTRAINT ck_classification_confidence CHECK (confidence >= 0 AND confidence <= 1),
  CONSTRAINT ck_classification_path CHECK (path IN ('live','catch_up')),
  CONSTRAINT ck_classification_route CHECK (route IN
    ('incident','possible_violation','review','none','measurement_only')),
  CONSTRAINT ck_classification_route_path CHECK ((path = 'catch_up') = (route = 'measurement_only')),
  CONSTRAINT ck_classification_route_reason CHECK (
    (route = 'possible_violation') = (route_reason IS NOT NULL)
    AND (route_reason IS NULL OR route_reason IN ('uncertain','inconsistent'))),
  CONSTRAINT ck_classification_thresholds CHECK (
    (path = 'live') = (confidence_floor IS NOT NULL AND incident_threshold IS NOT NULL)
    AND (confidence_floor IS NULL OR confidence_floor <= incident_threshold))
);
CREATE UNIQUE INDEX uq_classification_current
  ON message_classifications (telegram_chat_id, telegram_message_id) WHERE is_current;
CREATE INDEX ix_classifications_possible
  ON message_classifications (created_at) WHERE route = 'possible_violation';
CREATE INDEX ix_classifications_profile
  ON message_classifications (model_profile_id, prompt_version, taxonomy_version);
```

### Constraints

| Name | Protects |
|---|---|
| `fk_classification_message` | a prediction about a message that was never stored is impossible |
| `uq_classification_identity` | the target of the composite links in §4 — a link can only cite a prediction **about the same message** |
| `uq_classification_current` | FR-005, FR-015 — at most one current prediction per message; the classifier inserts `ON CONFLICT (telegram_chat_id, telegram_message_id) WHERE is_current DO NOTHING` |
| `ck_classification_category`, `_severity` | FR-011 — the vocabulary, D-TG-08's spelling, so operator labels and predictions compare without a mapping (D-TG-101) |
| `ck_classification_confidence` | FR-011 — backstop for D-TG-135's application check, which rejects first and records the failure kind |
| `ck_classification_route_path` | FR-062 — a catch-up prediction is always `measurement_only`, and only a catch-up prediction is |
| `ck_classification_route_reason` | FR-017 — a possible violation always says why; nothing else carries a reason |
| `ck_classification_thresholds` | FR-017, FR-026 — every live prediction records the thresholds it was routed under, and they were ordered |

The database constrains the route's **shape**; the route's **value** is the pure function of D-TG-142, the only
definition (`contracts/classification-pipeline.md` §5). A CHECK restating the routing arithmetic would be a
second definition.

### Indexes

| Name | Serves |
|---|---|
| `uq_classification_current` | the idempotent insert; every "the message's prediction" join |
| `ix_classifications_possible` | the possible-violations list (`contracts/classification-metrics.md` C4) |
| `ix_classifications_profile` | the comparison's grouping by model, instruction and vocabulary version (C1–C3) |

---

## §3 — `message_classification_attempts` — messages that produced no prediction

Every message the classifier handles ends as a prediction (§2), an **exclusion**, or a **failure** — the last
two recorded here (D-TG-146). A message with none of the three has not been classified yet.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | platform id, per chat |
| `path` | varchar(20) | no | `live` \| `catch_up` |
| `outcome` | varchar(20) | no | `excluded` \| `failed` |
| `reason` | varchar(40) | no | an eligibility reason for an exclusion; a failure kind for a failure |
| `model_profile_id` | bigint | yes | FK → `model_profiles.id`. Required for a failure, absent for an exclusion |
| `created_at` | timestamptz | no | `server_default now()` |

### DDL

```sql
CREATE TABLE message_classification_attempts (
  id                  bigserial PRIMARY KEY,
  telegram_chat_id    bigint      NOT NULL REFERENCES telegram_chats (id),
  telegram_message_id bigint      NOT NULL,
  path                varchar(20) NOT NULL,
  outcome             varchar(20) NOT NULL,
  reason              varchar(40) NOT NULL,
  model_profile_id    bigint      NULL REFERENCES model_profiles (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_attempt_message FOREIGN KEY (telegram_chat_id, telegram_message_id)
    REFERENCES telegram_messages (telegram_chat_id, message_id),
  CONSTRAINT ck_attempt_path CHECK (path IN ('live','catch_up')),
  CONSTRAINT ck_attempt_outcome CHECK (outcome IN ('excluded','failed')),
  CONSTRAINT ck_attempt_reason CHECK (
    (outcome = 'excluded' AND reason IN
      ('no_text','media','service','moderator','group_itself','linked_channel','acknowledgement','text_removed'))
    OR (outcome = 'failed' AND reason IN
      ('provider_unreachable','model_timeout','circuit_open','model_truncated','structured_output_invalid',
       'confidence_out_of_range','model_not_available','provider_rejected','provider_auth'))),
  CONSTRAINT ck_attempt_profile CHECK ((outcome = 'failed') = (model_profile_id IS NOT NULL))
);
CREATE UNIQUE INDEX uq_attempt_exclusion
  ON message_classification_attempts (telegram_chat_id, telegram_message_id) WHERE outcome = 'excluded';
CREATE INDEX ix_attempts_message
  ON message_classification_attempts (telegram_chat_id, telegram_message_id, created_at);
```

- **Exclusions are recorded once** (`uq_attempt_exclusion`, inserted `ON CONFLICT DO NOTHING`): a message's
  eligibility follows from facts written once — `is_service`, `is_from_moderator`, the captured payload — so
  it cannot change, except to `text_removed` at retention, which the catch-up command then records for a
  message it never reached.
- **Failures are appended**, one per final failure, naming the model. The latest is the one shown.
- `no_active_profile` is **not** a failure kind: with no active classification model nothing is recorded at
  all (FR-025, D-TG-152).
- Reason vocabulary — exclusions: D-TG-137's eight reasons; failures: M1's gateway categories that can reach
  the classifier, plus `confidence_out_of_range` (D-TG-135).

### A message's classification status — derived, in precedence

| Status | When |
|---|---|
| **classified** | a current prediction exists |
| **excluded (reason)** | else an exclusion row exists |
| **failed (kind)** | else a failure row exists — the latest by `(created_at, id)` |
| **not classified yet** | else — awaiting the model, or recorded before classification began |

Defined once in `contracts/classification-metrics.md` C5 and read by the panel wherever a prediction would be
shown (FR-055).

---

## §4 — `moderation_incidents` — who opened it, and what prompted it

```sql
ALTER TABLE moderation_incidents ADD COLUMN prompted_by_classification_id bigint NULL;
ALTER TABLE moderation_incidents ADD CONSTRAINT fk_incident_classification
  FOREIGN KEY (message_classification_id, telegram_chat_id, telegram_message_id)
  REFERENCES message_classifications (id, telegram_chat_id, telegram_message_id);
ALTER TABLE moderation_incidents ADD CONSTRAINT fk_incident_prompted_by
  FOREIGN KEY (prompted_by_classification_id, telegram_chat_id, telegram_message_id)
  REFERENCES message_classifications (id, telegram_chat_id, telegram_message_id);
ALTER TABLE moderation_incidents ADD CONSTRAINT ck_incident_ai_link
  CHECK (source <> 'ai' OR message_classification_id IS NOT NULL);
ALTER TABLE moderation_incidents ADD CONSTRAINT ck_incident_prompted_by
  CHECK (prompted_by_classification_id IS NULL OR source = 'operator');
```

| Column / constraint | Meaning |
|---|---|
| `message_classification_id` (TG-M4, NULL until now) | **the prediction that opened the incident.** Set only on a model-opened incident, and required there (`ck_incident_ai_link`). TG-M4's `ck_incident_operator_labels` still forbids it on an operator's flag |
| `prompted_by_classification_id` (new) | **the prediction that prompted an operator's flag** from the possible-violations list (FR-044). Only an operator flag may carry it (`ck_incident_prompted_by`); a flag made anywhere else leaves it NULL and is *independent* |
| `fk_incident_classification`, `fk_incident_prompted_by` | composite, `MATCH SIMPLE`: a NULL link is unchecked; a non-NULL link must cite a prediction **about this incident's own message** (probe 9 E2, E3) |

Existing rows — all operator flags with NULL links — satisfy every new constraint as they stand. A
model-opened incident otherwise uses TG-M4's columns exactly: `source = 'ai'`, `opened_by_user_id` NULL
(`ck_incident_opener`), `category` and `severity` copied from the prediction — within TG-M4's label checks,
because only a consistent prediction can route to `incident` (D-TG-141).

**Unchanged:** `uq_incident_anchor`, both TG-M4 views, `moderation_actions`, every lifecycle rule. A
model-opened incident's state, timings and outcome are computed by `moderation_incident_state` like any other.

---

## §5 — `attention_items` — the link TG-M3 shaped, and no more

```sql
ALTER TABLE attention_items ADD CONSTRAINT fk_attention_classification
  FOREIGN KEY (message_classification_id) REFERENCES message_classifications (id);
```

TG-M3 created the column and deferred the foreign key to this revision. It stays NULL on every row: the model
opens no question item in this milestone (the second clarification), and `source = 'ai'` stays reserved. The
queue shows the model's view of an item's messages by joining through the messages (C6), not through this
column.

---

## §6 — Changes outside the schema

| Where | Change | Why |
|---|---|---|
| `app/domain/model_profile.py` | `Role` gains `moderation`; `GenerationRole = Literal["llm","moderation"]` | D-TG-131 |
| `app/application/gateway/gateway.py` | `role: GenerationRole = "llm"` on `generate_text` / `generate_structured`; `model_run_id` attached to responses; `reasoning_effort` in `_generation_params` when present | D-TG-131, D-TG-133, D-TG-130 |
| `app/application/gateway/__init__.py` | re-exports the request/response vocabulary and the error classes | D-TG-132, Finding 3 |
| `app/application/gateway/accounting.py` | `record` returns the inserted id (`RETURNING id`), `None` when nothing was written | D-TG-133 |
| `app/providers/llm/base.py` | `TextResponse` / `StructuredResponse` gain `model_run_id: int \| None = None` | D-TG-133 |
| `app/providers/llm/openai_compatible.py` | `_bound_params` forwards `params["reasoning_effort"]` when present | D-TG-130, Finding 1 |
| `app/domain/moderation/attention.py` | `_matches_ack_stoplist` becomes public `is_acknowledgement`; its one caller follows | D-TG-137 |
| `app/application/moderation/messages.py` | `_text_and_normalized` becomes public `extract_text`; `derive_message(…, schedule_classification=True)` enqueues `classify_message` after commit | D-TG-138, D-TG-149 |
| `app/application/moderation/incidents.py` | the insert is extracted into `insert_incident(session, …)`, which `open_incident` and the classifier both call; `opened_by_user_id` becomes optional; `message_classification_id` accepted | D-TG-153 |
| `app/scripts/rederive_chat.py` | passes `schedule_classification=False` | D-TG-149 |
| `app/scripts/seed_profiles.py` | one roster row, inactive | D-TG-129 |
| `infra/docker-compose.yml` | new `ai-classifier` service; `ai-worker` gains `--queues default` | D-TG-148, Finding 4 |

---

## §7 — Retention

Neither new table stores message text, redacted or not; `model_runs` holds a digest unless
`GATEWAY_CAPTURE_PAYLOADS` is on, and then only redacted text (D-TG-140). When TG-M10's purge removes a
message's words, every prediction, route, exclusion, failure and link survives; the message can no longer be
classified, and the catch-up command records it as `text_removed`. Predictions are kept for as long as the
domain keeps its figures (FR-069).

---

## §8 — What revision `0007` deliberately does not do

- **No `GRANT`.** The migrator's default ACL covers both tables (probe 9).
- **No view.** Nothing here is derived from evidence that arrives later; the route is decided once, at insert.
- **No routing CHECK.** The route's value has one definition, in Python (D-TG-142); the database checks shape.
- **No change to TG-M4's views, to `moderation_actions`, or to any lifecycle rule.**
- **No `prompt_versions` table and no FK for `prompt_version`** — assessment milestone M5 owns that design (§10.10).
- **No `classification_reviews`** — `0008`/`0009`, TG-M8.
- **No enum types** — D-TG-103.
- **No data backfill.** History is classified only by the operator's catch-up command, which opens nothing.
