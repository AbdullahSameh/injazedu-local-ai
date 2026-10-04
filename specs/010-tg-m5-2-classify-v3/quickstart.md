# Quickstart: TG-M5.2 — classify_v3 and Model Qualification

Who does each step is marked: **(agent)** is implementation, **(operator)** is you. Git stays yours
(constitution IV).

## 1. Checks first

1. `make check` with Ollama quit. Everything is scripted:
   - the hash pins (v1, v2 and v3);
   - the G4 sentence in every instruction;
   - config and model input;
   - the qualification scoring and gate.
2. Rebuild the tools image after any change to the code, prompts or shipped fixtures:

   ```sh
   docker compose -f infra/docker-compose.yml --env-file .env --profile tools build migrate
   ```

## 2. Annotate your external fixtures (operator)

These are in `~/Projects/injaz-m5-fixtures/`, outside Git. **Never change a label.** Only add the two optional
keys (data-model §1).

- **`real-attention.jsonl` and `real-attention-extra.jsonl`:** add `"label_class": "ambiguous"` to the lines you
  agree are bare declaratives, which are reported and not gated. Proposed in plan §13: original set #5–#13;
  paired set #1–#7, #10–#12 and #19.
  - The tools skip blank lines when numbering. The paired file has a blank line 13, so from #13 on, `#N` is file
    line N+1.
- **`real-moderation.jsonl`:** add `"tracked": "no-link-rule"` to #1.
- **New file `fresh-attention.jsonl`:** 20–30 real messages from the group that nobody looked at while
  `classify_v3` was written, each labelled **before** any run. It is needed for a `QUALIFIED` result (Q9);
  without it, the result is `INCOMPLETE`.
- **Review:** shipped moderation #11 (`tracked: "label-review"`), whose label is ABUSE but which the larger
  model reads as COMPLAINT.
  - Confirm ABUSE: remove `tracked`, and it becomes a hard gate.
  - Relabel it COMPLAINT: say so, and the agent makes that single edit at your instruction.

## 3. Development: the reference runs

The development machine cannot host the production class (research Finding 13). These runs fix v3's wording
and give the reference numbers.

```sh
# baseline: what development runs today
make qualify-moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures
# the freeze rounds F1/F2 and the held-out run (agent, contracts/classify-v3.md §3)
make qualify-moderation PROFILE=ollama-gemma4-e4b-moderation PROMPT=classify_v3 FIXTURES_DIR=~/Projects/injaz-m5-fixtures
```

Expected:
- e2b with v2 is `NOT QUALIFIED` (Q1).
- e4b with v3 passes every tuning gate. It is `INCOMPLETE` until `fresh-attention.jsonl` exists.

Record the counts only in `research.md` §2.

**Development stays on `classify_v2` and e2b.** Don't set `classify_v3` on e2b: it reintroduces the advert
flips (plan §14).

## 4. Production host: qualify, then switch on (operator)

1. **Pull the candidates** that fit the host, largest last: `ollama pull <model>`.
2. **Register each candidate as an inactive moderation profile**, on the panel's Model Profiles page or with one
   insert. Use the e2b profile's params: `num_ctx 2048`, `num_predict 128`, `temperature 0`,
   `reasoning_effort none`. If the runtime ignores `num_ctx`, keep `OLLAMA_CONTEXT_LENGTH` ≥ 4096 (TG-M5
   Finding 8).
3. **Run the qualification for each candidate** with `PROMPT=classify_v3` and the full fixtures directory.
   Choose the **smallest model that is `QUALIFIED`**, by latency and memory.
4. **Switch on, in this order:**
   1. activate that profile (only one moderation profile is active);
   2. set `MODERATION_PROMPT_VERSION=classify_v3`;
   3. recreate `ai-classifier` and `ai-worker`;
   4. set `MODERATION_AI_ATTENTION_FROM` to now, with an offset, for the pilot group;
   5. recreate again.
5. **Pilot.** Dismiss "Not a real question" items daily, because an undismissed false positive expires as
   permanently unanswered (TG-M3 G3). Each week, read C9 on Classification Accuracy:
   - dismissed ÷ model-opened ≤ 10% over the first 30 or more items means keep going;
   - above 10%, blank `MODERATION_AI_ATTENTION_FROM`.

## 5. Rollback

- **Attention:** blank `MODERATION_AI_ATTENTION_FROM` and recreate the services. The system is TG-M5 exactly.
- **Instruction or model:** set `MODERATION_PROMPT_VERSION` back and reactivate the previous profile.
- Nothing recorded is revisited. Every figure stays split by model and instruction.

## 6. When an exception ends

- **The no-link rule ships:** remove `tracked` from real moderation #1 and re-qualify.
- **The accusation's label is confirmed after review:** see §2.

The closed list (Q12) never grows without a new decision recorded in `research.md`.
