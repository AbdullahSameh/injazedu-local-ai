# Contract: model qualification

**Feature**: `specs/010-tg-m5-2-classify-v3` · **Status**: durable from TG-M5.2 on. It decides whether one
pair of **model profile** and **instruction** may run AI-assisted Attention in production (FR-206–FR-210).

## §1 — The command

```text
make qualify-moderation PROFILE=<profile name> PROMPT=<instruction version> FIXTURES_DIR=<dir outside the repo> [REPEAT=2]
→ python -m app.scripts.qualify_moderation --profile … --prompt … --fixtures-dir /fixtures --repeat …
```

- **C1. Inputs.**
  - `--profile` names a `model_profiles` row with `role = 'moderation'`, active or not (D-TG-161).
  - `--prompt` must be in the allowlist.
  - `--fixtures-dir` is mounted **read-only** into the tools container.
  - `--repeat` defaults to 2 and must be at least 2 for a `QUALIFIED` result (Q8).
- **C2. It writes nothing.** No prediction, no incident, no Attention item, no model-run accounting row and no
  file. The real gateway and the real runtime are used, never a scripted model.
- **C3. It prints no text.** Only counts, line numbers, set names, routes, categories, latencies and gate
  verdicts appear. The fixture's text, the redacted text and the model's raw output never do (check 4).
- **C4. It judges each fixture the way the smokes do** (D-TG-178), through the same extracted per-fixture
  functions:
  - **attention:** normalise, then the rule set (`evaluate`), then eligibility, then the model, then
    `route_prediction` (live), then `proposes_attention`;
  - **moderation:** normalise, then the model, then `route_prediction` (live).

  Floor and threshold are the configured ones. Nothing is re-derived (N7).
- **C5. Exit code.**
  - `0` when `QUALIFIED`;
  - `1` when `NOT QUALIFIED`;
  - `2` when `INCOMPLETE` (a required set is missing) or on a usage error.

## §2 — The sets

They are read in this order (data-model §2):
- attention tuning: `real-attention*.jsonl`, sorted, then the shipped attention set;
- the held-out set;
- the fresh sample;
- moderation: real, shipped, policy.

A missing **required** set makes the result `INCOMPLETE`, and its gates are `NOT RUN`. The fixture keys are in
data-model §1.

## §3 — Scoring

- **S1. Attention lines, by label class.** For each attention line, the opener is one of `rule`, `model`,
  `none`, `excluded` or `error` (B2).
  - A **clear negative** is model-opened when its opener is `model`.
  - A **clear positive** is missed when its opener is `none` or `excluded`.
  - A rule-declined clear positive is one with `rule_opens = False`.
  - **Ambiguous** lines are counted as "answered true" and as agreement with the label, and are **never gated**.
- **S2. Moderation lines.** False negatives, false positives and routes are counted exactly as the smoke counts
  them, with **tracked lines removed from the gated counts** and reported on their own line.
- **S3. Tracked lines.** Each prints its set, line, disposition and whether it passed. More than 2 tracked lines
  in one run fails the gate (Q12).
- **S4. Errors.** A gateway error or an out-of-range confidence is an error line. Any error fails Q11, and an
  error line is never scored as a prediction.
- **S5. Repeat.** Every set runs `--repeat` times. Two runs are the same when every line's predicted
  needs-response, needs-moderation, category and route match. The count of differing lines is printed.
- **S6. Latency.** The median and the p95 of every model call's wall time, across all runs.

## §4 — The gate

Every row is a hard gate unless marked otherwise.

| # | Gate | Passes when |
|---|---|---|
| Q1 | Tuning clear negatives model-opened | = 0 |
| Q2 | Held-out clear negatives model-opened | ≤ 1 |
| Q3 | Tuning clear positives missed | = 0 |
| Q4 | Held-out rule-declined clear positives missed | ≤ 1 (out of 10 or more) |
| Q5 | Real moderation: false negatives and false positives, excluding tracked lines | both = 0 |
| Q6 | Shipped moderation: false negatives and false positives, excluding tracked lines | both = 0 |
| Q7 | Policy moderation | false negatives ≤ 1; false positives = 0; legitimate lines routed to `incident` = 0 |
| Q8 | Repeat | 0 differing lines, with `--repeat` ≥ 2 |
| Q9 | Fresh sample | clear negatives model-opened ≤ 1; rule-declined clear positives missed ≤ 1 |
| Q10 | Latency | p95 ≤ 10,000 ms (D-TG-179) |
| Q11 | Errors | = 0 |
| Q12 | Tracked lines | ≤ 2, each disposition ∈ {`no-link-rule`, `label-review`} |
| — | Ambiguous | **reported only**, never gated |
| — | Category agreement | **reported only** (secondary) |

The overall result:
- **`QUALIFIED`**: every gate `PASS`.
- **`NOT QUALIFIED`**: any gate `FAIL`.
- **`INCOMPLETE`**: no `FAIL`, and at least one `NOT RUN`.

**Where the thresholds come from:**
- Q5–Q7 are `classify_v2`-on-e2b's measured advert numbers (research Finding 12, D-TG-174).
- Q1–Q4 and Q9 are the plan's §10.

## §5 — Output

1. **A header:** profile, model, prompt, floor, threshold, repeat.
2. **For each set:** the smoke's summary lines, then the label-class line from S1 and the tracked lines.
3. **A latency line and a repeat line.**
4. **The gate table:** one line per Q1–Q12 with `PASS`, `FAIL` or `NOT RUN`, and the line numbers that caused
   a `FAIL`.
5. **The overall verdict line.**

The per-line detail is the smoke's own `[OK]`, `[FN]`, `[FP]` and `[MISMATCH]` line format, for run 1 only.

## §6 — What the result means operationally

- **R1.** Production may set `MODERATION_AI_ATTENTION_FROM` for a group only when its active moderation profile
  and `MODERATION_PROMPT_VERSION` produced `QUALIFIED` on the production host (FR-210). Recording the result
  (counts only) in `research.md` §2 is the operator's evidence.
- **R2.** After switch-on, the pilot is governed by C9: dismissed ÷ model-opened ≤ 10% over the first 30 or more
  items (SC-206). Above that, the switch is blanked.
- **R3.** Changing the active profile or the instruction requires a new `QUALIFIED` run first. Nothing already
  recorded is revisited (FR-213).

## §7 — What may never happen

- **N1.** The command printing message text, or writing anything.
- **N2.** A second definition of the benchmark path, gate, route or eligibility.
- **N3.** Ambiguous lines counted in a hard gate, or tracked lines silently dropped.
- **N4.** `QUALIFIED` with a required set missing, or with `--repeat` < 2.
