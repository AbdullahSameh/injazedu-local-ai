# Quickstart: TG-M5.3 — A Separate Attention Judgement

**Feature**: `specs/011-tg-m5-3-attention-judgement` · Operator steps, in order. Every command runs from the
repository root. Real fixtures stay in `~/Projects/injaz-m5-fixtures/`, outside Git.

> **Deploying this milestone pauses AI-assisted opening.** While `MODERATION_ATTENTION_PROMPT_VERSION` is blank,
> no model item opens, even with `MODERATION_AI_ATTENTION_FROM` set (D-TG-199). Rule items are unaffected.

## 1. Story 1: Member discussion (deployable alone)

1. Deploy the panel change. There is no migration and no restart of the AI services.
2. On **Live Attention Queue**, an open item now offers **Member discussion** beside "Not a real question" and
   "Message removed". Use it for a real question that was between members and needed no moderator.
3. On **Classification Accuracy**, every dismissal count now reads "dismissed (any reason)", with the split
   beneath it: not a real question · member discussion · message removed · other.
   - **What did not change:** every number, including the pilot gate.
   - **How to use it:** the `member_discussion` count on **rule** items is the evidence for, or against, a later
     rule-set change.

## 2. Schema and profiles

Rebuild the `migrate` tool image first whenever it may be stale, that is, whenever the code, the
revisions, the prompts or `seed_profiles.py` changed since it was built. `make migrate` and `make
seed-profiles` run inside that image, and `docker compose run` does not rebuild it: a stale image
reports the old head (`0007`) and seeds the old roster, with no error (2026-10-07).

```text
docker compose -f infra/docker-compose.yml --env-file .env --profile tools build migrate
make migrate            # revision 0008: two tables, the attention role, the item link (data-model)
make seed-profiles      # adds ollama-gemma4-e2b-attention and ollama-gemma4-e4b-attention, both inactive
make profiles           # check both are listed, role=attention, inactive; profiles 14 and 17 unchanged
```

Nothing is called yet: the attention instruction is blank.

## 3. Before qualification (operator)

- **Policy D** (spec FR-310): confirm it, or edit it through `/speckit-clarify`, before any fixture is written.
- **T031 annotations** of `real-attention*.jsonl`:
  - the ambiguous lines (`label_class`);
  - real moderation #1 → `"tracked": "no-link-rule"`;
  - `intent` and `"peer": true` on any peer line.
- **The fresh sample:** `fresh-attention.jsonl`, 20–30 real messages, each with `text`, `needs_response`,
  `intent` and `label_class`. Include peer discussion and peer-addressed service questions as they occur. Label
  every line before any run.

## 4. The selection round (once)

1. The implementer writes the three candidates (W1, W2, W3) into the fixtures directory and records their SHA-256
   in `research.md` §2. This happens **before the first run**.
2. Run the matrix: three candidates × two profiles.

   ```text
   make qualify TASK=attention PROFILE=ollama-gemma4-e2b-attention CANDIDATE=attention-candidate-w1.md \
        FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2
   … the same for w2 and w3, then for ollama-gemma4-e4b-attention
   ```

   Each run prints `CANDIDATE`, every gate, and the reported lines (asking vs discussion, rule-opened negatives,
   bursts).
3. Apply the decision rule (qualification §8 W-3).
4. Allow at most one revision, limited to the failing sentence, then freeze the wording as `attention_v1`.
5. If nothing passes, the milestone stops and reports.

## 5. Freeze, held-out and qualify

1. `attention_v1.md` is pinned and allowlisted. **Only then** is `attention_heldout_fixtures.jsonl` written.
2. Run the qualification once:

   ```text
   make qualify TASK=attention PROFILE=<chosen> PROMPT=attention_v1 FIXTURES_DIR=~/Projects/injaz-m5-fixtures REPEAT=2
   ```

   - **QUALIFIED** (exit 0): go on.
   - **NOT QUALIFIED** (exit 1): stop. The frozen version is never edited to pass.
   - **INCOMPLETE** (exit 2): a set is missing.
3. Confirm the moderation side is untouched:

   ```text
   make qualify TASK=moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=… REPEAT=2
   ```

   The per-line results should be the same as before this milestone (SC-305).

## 5a. The second cycle: `attention_v2` under Policy D′ (2026-10-09)

`attention_v1` went through §4–§5 and is frozen. It is `QUALIFIED` under Policy D (2026-10-07) only. Policy D′
(spec FR-310) makes it unqualified, so **it is never the shadow or production instruction.** The second cycle
repeats §4–§5 (`docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`; qualification §8′):
1. **The operator:**
   - relabels T077's 37-line sample under D′ and saves it as `real-attention-fresh-v1.jsonl` in the fixtures
     directory, where it is tuning;
   - moves the old `fresh-attention.jsonl` out of that directory.
2. **The implementer:**
   - renames the v1 held-out set to `attention_heldout_v1_fixtures.jsonl`, byte-identical and pinned;
   - writes `attention_validation_scope_fixtures.jsonl`.

   Both are validation sets, and A3 is judged per validation set.
3. **The implementer** writes the three candidates (V2-A, V2-B, V2-C) into the fixtures directory and records their
   SHA-256 **before the first run**. Then run the matrix, as in §4, with `CANDIDATE=attention-candidate-v2-{a,b,c}.md`.
4. **Freeze** `attention_v2`. **Only then** is the new `attention_heldout_fixtures.jsonl` written. Run once with
   `PROMPT=attention_v2`; the expected verdict is `INCOMPLETE`, until the next step.
5. **The operator** adds a new `fresh-attention.jsonl`: 20–30 real messages, none of them T077's, labelled under D′.
   Re-run for `QUALIFIED`, then run §5 step 3's moderation check.

> *(2026-10-09)* **The second cycle stopped under W-7′:** no V2 candidate passed, so there is no `attention_v2`
> (research §2). Steps 4–5 above did not happen.

## 6. Development shadow

> *(2026-10-09)* Use `attention_v2` once it is `QUALIFIED` (§5a). `attention_v1` is history. Any shadow judgements
> it records keep their version and are never rewritten.

1. **Model Profiles:** activate the chosen attention profile.
2. In `.env`, set `MODERATION_ATTENTION_PROMPT_VERSION=attention_v1`.
3. Recreate `ai-worker` and `ai-classifier`.
   - `ai-classifier` now consumes `moderation_attention` and `moderation_classify`.
   - Under today's scheduling policy, Attention goes first.
4. With `MODERATION_AI_ATTENTION_FROM` blank, judgements accumulate and nothing opens.
5. On **Classification Accuracy**, read:
   - **"Attention judgements: what happened to every message"**: judged, excluded by reason (including
     `rule_opens`), failed, not judged yet;
   - **per attention block:** judgements by intent, and **on time / judged**. SC-306 wants at least 95%.

## 7. Switch on and the pilot

1. Set `MODERATION_AI_ATTENTION_FROM=<now, with offset>`, and recreate `ai-worker` and `ai-classifier`.
2. A burst the rules decline, whose member is judged `asking`, opens a **Model** item. A member the
   classification calls an advert or abuse never opens one.
3. After a week, on the **attention** row of "Questions the model opened": **dismissed (any reason) / opened**
   must be at most 10% over at least 30 items. Read the breakdown for why.
4. Under **operator-added items**, review the multi-message rows by hand. Note in the pilot record which were a
   request spread across messages (L-B1).

## 8. Roll back

- **Stop opening at once:** blank `MODERATION_AI_ATTENTION_FROM` (or the attention prompt), then recreate
  `ai-worker` and `ai-classifier`. Items already opened stay.
- **Stop all attention calls:** blank `MODERATION_ATTENTION_PROMPT_VERSION`, or deactivate the attention profile.
- **The schema:** revision `0008` is forward-only once judgements exist.
- **Story 1** never needs a rollback for safety. Removing the action leaves recorded reasons as they are.

## 9. Known limitations

These are in `contracts/attention-judgement.md` §11:
- a request spread across burst members, none of which asks alone (L-B1);
- an edit that removes a rule-skipped member's only signal inside the settle window;
- reply context is invisible to the model (D8);
- rule-opened peer questions are reached only by the Member discussion dismissal;
- V is read once, at opening;
- a greeting member costs one call;
- with the attention model down, model-only questions go untracked until it returns.
