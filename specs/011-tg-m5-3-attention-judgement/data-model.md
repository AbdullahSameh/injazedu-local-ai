# Data Model: TG-M5.3 — A Separate Attention Judgement

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Revision**: `0008_moderation_attention_judgement`
(D-TG-192) · **Date**: 2026-10-07

Story 1 (dismissal reasons, D-TG-182) needs **no DDL**; §5 is vocabulary only. Everything else is **one additive
revision**, `0008`. Every existing row satisfies it (Finding 19). No `GRANT` is needed: the migrator's default
ACL reaches `ai_control` and `ai_app` for new tables, as 0007 measured. No view is added. Every derived value has
one definition, in Python.

## §1 — `message_attention_judgements`: one immutable intent per message

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | the judged message, not the burst's anchor |
| `model_profile_id` | bigint | no | FK → `model_profiles.id` `ON DELETE RESTRICT`; a profile with role `attention` |
| `model_run_id` | bigint | yes | FK → `model_runs.id` `ON DELETE SET NULL`; nullable as in 0007 (Finding 6) |
| `prompt_version` | varchar(40) | no | the attention instruction's version, e.g. `attention_v1` |
| `intent` | varchar(20) | no | one of §1.1 |
| `needs_response` | boolean | no | `needs_response_for(intent)`, computed once at insert (D-TG-185) and never recomputed |
| `path` | varchar(20) | no | `live` only in this milestone; `catch_up` is allowed by the check so a later milestone needs no DDL |
| `is_current` | boolean | no | default `true`; flips only in TG-M8 |
| `created_at` | timestamptz | no | `server_default now()`; G5, G6 and timeliness read it |

**No text column, no confidence and no route.** Rows are never updated or deleted.

### §1.1 Constraints and indexes

| Name | Shape | Protects |
|---|---|---|
| `fk_attention_judgement_message` | FK `(telegram_chat_id, telegram_message_id)` → `telegram_messages (telegram_chat_id, message_id)` | a judgement of a message that was never stored |
| `uq_attention_judgement_identity` | `UNIQUE (id, telegram_chat_id, telegram_message_id)` | composite references, as 0007's `uq_classification_identity` |
| `ck_attention_judgement_intent` | `intent IN ('asking','discussion','informing','social','offering','other')` | the closed output (spec FR-309) |
| `ck_attention_judgement_path` | `path IN ('live','catch_up')` | as 0007 |
| `uq_attention_judgement_current` | `UNIQUE (telegram_chat_id, telegram_message_id) WHERE is_current` | one current judgement; the idempotent insert's target (I1) |
| `ix_attention_judgements_profile` | `(model_profile_id, prompt_version)` | per-model, per-instruction figures |

There is deliberately **no CHECK** relating `needs_response` to `intent`. The mapping has one definition, in the
domain (008 data-model §2's rule). A test asserts every stored row agrees with `needs_response_for`.

## §2 — `message_attention_attempts`: exclusions and failures

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | |
| `path` | varchar(20) | no | `live` \| `catch_up` |
| `outcome` | varchar(20) | no | `excluded` \| `failed` |
| `reason` | varchar(40) | no | below |
| `model_profile_id` | bigint | yes | FK → `model_profiles.id`; required exactly for a failure |
| `created_at` | timestamptz | no | `server_default now()` |

| Name | Shape |
|---|---|
| `fk_attention_attempt_message` | FK `(telegram_chat_id, telegram_message_id)` → `telegram_messages` |
| `ck_attention_attempt_path` | `path IN ('live','catch_up')` |
| `ck_attention_attempt_outcome` | `outcome IN ('excluded','failed')` |
| `ck_attention_attempt_reason` | `(outcome = 'excluded' AND reason IN ('no_text','media','service','moderator','group_itself','linked_channel','acknowledgement','text_removed','rule_opens')) OR (outcome = 'failed' AND reason IN ('provider_unreachable','model_timeout','circuit_open','model_truncated','structured_output_invalid','model_not_available','provider_rejected','provider_auth'))` |
| `ck_attention_attempt_profile` | `(outcome = 'failed') = (model_profile_id IS NOT NULL)` |
| `uq_attention_attempt_exclusion` | `UNIQUE (telegram_chat_id, telegram_message_id) WHERE outcome = 'excluded'`: an exclusion is recorded once |
| `ix_attention_attempts_message` | `(telegram_chat_id, telegram_message_id, created_at)`: the latest failure per message |

**The reasons:**
- The exclusion reasons are E1–E8's eight values, plus `rule_opens` (AE2).
- The failure reasons are 0007's, minus `confidence_out_of_range`: there is no confidence.
- Failures are appended.

**Status precedence per message,** as 008 M14: a current judgement, then an exclusion, then the latest failure,
then "not yet". The four outcomes partition the eligible-or-excluded messages (C10).

## §3 — `attention_items`: which judgement opened it

| Change | Shape |
|---|---|
| new column `attention_judgement_id` | bigint, nullable, FK `fk_attention_judgement` → `message_attention_judgements.id`. Set at insert on a TG-M5.3 model item, never updated |
| new check `ck_attention_ai_link` | `CASE WHEN source = 'ai' THEN num_nonnulls(message_classification_id, attention_judgement_id) = 1 ELSE num_nonnulls(message_classification_id, attention_judgement_id) = 0 END` |

- **Every row passes today** (Finding 19): the one `ai` item has a classification link, and no other item has a
  link.
- **Eras:** historical TG-M5.1 items keep `message_classification_id`. From this revision on, `open_item` writes
  only `attention_judgement_id`.
- **The FK is to `id` alone,** like `fk_attention_classification`. The opening judgement may belong to a later
  burst member than the anchor, so a composite FK on the anchor's message would be wrong.

## §4 — `model_profiles`: the `attention` role

`ck_model_profiles_role` becomes `role IN ('llm','embedding','moderation','attention')`. Then
`uq_model_profiles_one_active_per_role` gives exactly one active attention profile.

**The seed roster** (D-TG-190) adds two rows, both `is_active = false`, with `num_ctx 2048`, `num_predict 128`,
`temperature 0` and `reasoning_effort "none"`:
- `ollama-gemma4-e2b-attention` (`gemma4:e2b-it-qat`);
- `ollama-gemma4-e4b-attention` (`gemma4:e4b-it-qat`).

## §5 — `attention_items.close_reason`: vocabulary only (Story 1, no DDL)

| Value | Written by | Meaning |
|---|---|---|
| `not_a_question` | operator, "Not a real question" | not a question or request at all |
| `member_discussion` | operator, "Member discussion" (**new**) | a real question or discussion between members; no moderator needed |
| `message_removed` | operator, "Message removed" | the operator's own judgement that the message is gone (TG-M3 P7) |
| `expired` | expiry (`status = 'expired'`) | not a dismissal |
| anything else | operator free text (TG-M3 FR-046's column note) | counted as `other` in the breakdowns |

The column stays `varchar(40)` with no CHECK (Finding 16). `status` is `dismissed` for the three operator
reasons.

## §6 — Downgrade

`0008`'s downgrade:
- drops `ck_attention_ai_link`, `fk_attention_judgement` and the column;
- restores the three-value role check;
- drops both new tables.

It fails, correctly, once any `attention` profile, judgement or attention-linked item exists. Once judgements
exist the revision is forward-only (plan §14).

## §7 — Settings

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `MODERATION_ATTENTION_PROMPT_VERSION` | `apps/ai-api` `Settings` | blank | `str \| None`, which must be in `ATTENTION_PROMPT_VERSIONS` (empty until the freeze, D-TG-189). Blank means no attention call and nothing recorded (FR-307) |
| `MODERATION_AI_ATTENTION_FROM` | unchanged | blank | the opening switch. A model item now also needs the prompt set (FR-322) |
| `MODERATION_BURST_GAP_S` | `apps/ai-control/config/moderation.php` (new key `burst_gap_s`) | 90 | read by C10's timeliness and multi-message figures, as the panel already reads two moderation settings |

The two actors' priorities are compose and actor settings (D-TG-187), not application settings.

## §8 — Benchmark fixtures

Each line is one JSONL object. Existing keys keep their meaning (010 data-model §1); these are added (D-TG-193):

| Key | Kinds | Value | Rule |
|---|---|---|---|
| `intent` | attention | one of §1.1's six | `(intent == "asking") == needs_response`, otherwise `FixtureError` |
| `peer` | attention | `true` | in the in-repo validation and held-out files, the line must be rule-declined (a test) |
| `burst` | attention, burst set only | 2–5 strings, in posting order | replaces `text`; `needs_response` is the human label for the whole burst |
| `expected_opener` | attention, burst set only (required there) | `rule` \| `model` \| `none` | what the live path is expected to do. L-B1 lines are `needs_response: true` with `expected_opener: "none"`. R-burst compares it with the actual opener |

**The sets the attention suite reads, in order:**

| Set | Where | Role | Gate |
|---|---|---|---|
| `real-attention*.jsonl` | the operator's directory | tuning | A1, A2 |
| `attention_smoke_fixtures.jsonl` | `app/scripts/` | tuning | A1, A2 |
| `attention_validation_fixtures.jsonl` | `app/scripts/` (new, before selection) | validation | A3 |
| `attention_heldout_fixtures.jsonl` | `app/scripts/` (new, after the freeze) | held-out | A4 |
| `fresh-attention.jsonl` | the operator's directory | fresh | A5 |
| `attention_burst_fixtures.jsonl` | `app/scripts/` (new, with validation) | burst | reported |
| `real-moderation.jsonl`, `moderation_smoke*_fixtures.jsonl` | as today | A6 source | A6 |

*(2026-10-09, the second cycle: Policy D′ and `attention_v2`; addendum §6.1.)* The keys are unchanged. The sets
become:

| Set | Where | Role | Gate |
|---|---|---|---|
| `real-attention*.jsonl`, now with `real-attention-fresh-v1.jsonl` (T077's 37-line sample, relabelled under D′) | the operator's directory | tuning | A1, A2 |
| `attention_smoke_fixtures.jsonl` | `app/scripts/` | tuning | A1, A2 |
| `attention_validation_fixtures.jsonl` | `app/scripts/`, unchanged | validation | A3, judged on its own |
| `attention_validation_scope_fixtures.jsonl` | `app/scripts/` (new, before any v2 candidate) | validation | A3, judged on its own |
| `attention_heldout_v1_fixtures.jsonl` | `app/scripts/`: the v1 held-out set renamed, byte-identical, with its SHA-256 pinned in a test | validation | A3, judged on its own |
| `attention_heldout_fixtures.jsonl` | `app/scripts/` (new, after the `attention_v2` freeze) | held-out | A4 |
| `fresh-attention.jsonl` | the operator's directory (new; none of T077's lines) | fresh | A5 |
| burst; the A6 source | unchanged | unchanged | unchanged |

**Sets 010 named but never wrote:** `attention_smoke_heldout_fixtures.jsonl` was never written. The attention
held-out set takes the new name above, with the grid and topics of plan §9.

## §9 — Pure domain values (`app/domain/moderation/attention_judgement.py`)

| Name | Value |
|---|---|
| `INTENTS` | `("asking","discussion","informing","social","offering","other")` |
| `needs_response_for(intent)` | `intent == "asking"`: the single derivation |
| `attention_exclusion(facts, text)` | `eligibility(facts)` (E1–E8), else `"rule_opens"` when `evaluate([text])`, else `None` |
| `judgement_proposes(path, needs_response)` | `path == "live" and needs_response`: A1–A2 |
| `vetoed(category)` | `category in {"SPAM_OR_AD","ABUSE"}`: V |
| `within_attention_window` | unchanged (`classification.py`, G5–G6) |
