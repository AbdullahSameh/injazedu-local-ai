# Data Model: TG-M5.2 — classify_v3 and Model Qualification

**No migration and no schema change** (FR-214). Revisions `0008`–`0009` stay reserved. Nothing here is
stored in a database.

## §0 — Stored data this milestone touches

| What | Change |
|---|---|
| `message_classifications.prompt_version` | A new possible value, `classify_v3`. The column is `varchar(40)`, not a foreign key, and has no check constraint (008 data-model §2), so nothing in the schema changes. Every figure already groups by it (classification-metrics K3). |
| `model_profiles` | Possible new rows, inactive, with `role = 'moderation'`, one per candidate model (D-TG-180). There is no column change. |
| Everything else | Unchanged. |

## §1 — The benchmark fixture line (JSONL, one object per line)

Two optional keys are added; every existing key and file keeps its meaning (D-TG-177).

**Attention fixture**

| Key | Type | Required | Meaning |
|---|---|---|---|
| `text` | string | yes | The message as posted. It is never printed. |
| `needs_response` | bool | yes | The human label. |
| `category` | string | no | The expected category (secondary). |
| `label_class` | `"clear"` \| `"ambiguous"` | no, default `"clear"` | `ambiguous` = reported, never gated (D-TG-173). Attention sets only. |
| `tracked` | `"no-link-rule"` \| `"label-review"` | no | A tracked boundary case (D-TG-176). Any other value is refused. |

**Moderation fixture**

| Key | Type | Required |
|---|---|---|
| `text` | string | yes |
| `category` | string | yes |
| `needs_moderation` | bool | yes |
| `tracked` | as above | no |

**Validation:**
- An unknown `label_class` or `tracked` value is a load error that names the set and line, never the text.
- `label_class` on a moderation fixture is refused.
- More than **2** `tracked` lines across all sets in one run fails qualification (the closed list).

**Annotations the implementer adds to shipped synthetic sets.** These are listed for operator review, and labels
are never changed:
- `attention_smoke_fixtures.jsonl` #4, #5, #6 → `label_class: "ambiguous"`. These are bare declaratives under
  Policy S.
- `moderation_smoke_fixtures.jsonl` #11 → `tracked: "label-review"`.

**Annotations the operator adds to external sets** (quickstart §2):
- `real-attention.jsonl` and `real-attention-extra.jsonl`: `label_class: "ambiguous"` on the lines the
  operator agrees are ambiguous. Proposed in plan §13: original set #5–#13; paired set #1–#7, #10–#12 and #19.
- `real-moderation.jsonl` #1 → `tracked: "no-link-rule"`.

## §2 — The benchmark sets the qualification reads

| Set | Where | Role | Kind | Required |
|---|---|---|---|---|
| `real-attention*.jsonl` | the fixtures directory, outside Git | tuning | attention | yes, at least one |
| `attention_smoke_fixtures.jsonl` | `app/scripts/` | tuning | attention | yes |
| `attention_smoke_heldout_fixtures.jsonl` | `app/scripts/` (written after the freeze) | held-out | attention | yes |
| `fresh-attention.jsonl` | the fixtures directory, outside Git | fresh sample (G-F) | attention | yes for **qualified**. When absent, the result is **incomplete** |
| `real-moderation.jsonl` | the fixtures directory, outside Git | advert, real | moderation | yes |
| `moderation_smoke_fixtures.jsonl` | `app/scripts/` | advert, shipped | moderation | yes |
| `moderation_smoke_policy_fixtures.jsonl` | `app/scripts/` | advert, policy | moderation | yes |

## §3 — The held-out set (FR-209)

`apps/ai-api/app/scripts/attention_smoke_heldout_fixtures.jsonl` is written only after `classify_v3`'s hash is
pinned, and run once per frozen version. It holds about 50 synthetic or sanitised lines and no real text.

**Topics** are kept apart from the tuning sets:
- certificate;
- grades and results;
- homework submission;
- payment receipt;
- group link;
- exam hall or seat;
- meeting app;
- timetable file.

**Dialect and form:** at least 40% Saudi and 30% Egyptian phrasing, at least 80% without a question mark, and
at least 8 near-pairs.

**Clear lines, about 40:**

| Kind | Count | Label |
|---|---|---|
| Clear positives that rule set v1 declines: 4 requests, 4 unresolved problems, 2 detail-plus-tag confirmations | 10 | true |
| Positives the rules catch (sanity) | 4 | true |
| Mixed: informs, plus a request or a remaining problem | 3 | true |
| Relapse: it worked, then stopped | 1 | true |
| A question wrapped in a social opener | 1 | true |
| Informing with detail | 8 | false |
| Resolved status | 5 | false |
| Passing on an announcement | 3 | false |
| Social comment on a past event | 3 | false |
| Acknowledgements | 2 | false |

Before any model run, the rule outcome of every "rule-declined" line is checked with `evaluate` (pure, with no
model involved).

**Ambiguous lines, about 10:** bare declaratives on the new topics, labelled true under Policy S, each with its
detailed twin among the clear lines.

## §4 — The qualification result (printed, never stored)

For **one** pair of model profile and instruction:
- **per set:** the smoke's own summary lines, plus a split by label class:
  - clear positives with no opener;
  - clear negatives the model opened;
  - ambiguous lines answered true, and their agreement with the label;
  - rule-declined clear positives missed;
- **tracked lines:** each with its set, line, disposition, and whether it passed;
- **latency:** median and p95, in milliseconds, over every model call;
- **the repeat comparison:** the number of lines that differ between run 1 and run 2;
- **the gate:** one line per gate, `PASS`, `FAIL` or `NOT RUN`, and an overall `QUALIFIED`, `NOT QUALIFIED` or
  `INCOMPLETE`.

## §5 — Instruction allowlist

`ModerationPromptVersion` is `classify_v1 | classify_v2 | classify_v3`. The default stays `classify_v1`. The
allowlist, the files and the SHA-256 pins remain one set (tested).
