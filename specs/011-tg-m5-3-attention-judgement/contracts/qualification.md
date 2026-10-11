# Contract: Qualification, Version 2 (Core and Task Suites)

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Status**: durable from TG-M5.3 onwards. It supersedes
`specs/010-tg-m5-2-classify-v3/contracts/qualification.md` (version 1):
- version 1's command survives as an alias;
- its moderation gates survive unchanged;
- its attention gates move to the attention suite.

It decides whether one **task's** pair, a **model profile** and an **instruction**, may run in production
(spec FR-324 to FR-333).

## §1 — The command

```text
make qualify TASK=attention|moderation PROFILE=<profile> FIXTURES_DIR=<dir outside the repo>
             [PROMPT=<allowlisted version> | CANDIDATE=<file in FIXTURES_DIR>] [REPEAT=2]
→ python -m app.scripts.qualification --task … --profile … [--prompt … | --candidate-file …] --fixtures-dir /fixtures --repeat …
make qualify-moderation …   ≡   make qualify TASK=moderation …   (alias, unchanged interface)
```

- **C1. The profile and the instruction.**
  - `--profile` names a `model_profiles` row whose role matches the task (`attention` or `moderation`), active or
    not.
  - `--prompt` must be in that task's allowlist. Its default is the task's setting:
    `MODERATION_ATTENTION_PROMPT_VERSION` or `MODERATION_PROMPT_VERSION`.
- **C2. It writes nothing:** no row, no accounting and no file. It uses the real gateway on a bare `Gateway` with
  no accounting writer, never a scripted model.
- **C3. It prints no text.** It prints counts, line numbers, set names, intents, categories, routes, latencies,
  hashes and verdicts only (check 4).
- **C4. It judges each line on the live path**, through the suite's per-fixture function, the same one
  `make smoke-attention` and `make smoke-moderation` call (N2).
- **C5. Exit codes:** `0` QUALIFIED; `1` NOT QUALIFIED; `2` INCOMPLETE or a usage error; `3` CANDIDATE.
- **C6. Candidate mode** (attention only, D-TG-196).
  - `--candidate-file` reads an unpinned wording from the read-only fixtures mount, and prints `CANDIDATE` and
    its SHA-256.
  - Every gate is computed. The verdict is always `CANDIDATE`, never `QUALIFIED`.

## §2 — The sets

| Suite | Sets, in reading order | Required for QUALIFIED |
|---|---|---|
| attention | `real-attention*.jsonl` (sorted), `attention_smoke_fixtures.jsonl` → tuning; `attention_validation_fixtures.jsonl` → validation; `attention_heldout_fixtures.jsonl` → held-out; `fresh-attention.jsonl` → fresh; `attention_burst_fixtures.jsonl` → burst; `real-moderation.jsonl` and `moderation_smoke*_fixtures.jsonl` → A6 source | all except burst |
| moderation | `real-moderation.jsonl`, `moderation_smoke_fixtures.jsonl`, `moderation_smoke_policy_fixtures.jsonl` | all |

A missing required set gives `NOT RUN` on its gates, so the result is `INCOMPLETE`.

*(2026-10-09, the second cycle: Policy D′ and `attention_v2`; `docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`
§6.1.)* The attention suite reads these sets:
- **tuning:**
  - `real-attention*.jsonl` (sorted), now including `real-attention-fresh-v1.jsonl`, T077's 37-line sample
    relabelled under D′, picked up by the same pattern;
  - `attention_smoke_fixtures.jsonl`.
- **validation:** three sets, each judged on its own (A3).
  - `attention_validation_fixtures.jsonl`;
  - `attention_validation_scope_fixtures.jsonl` (new);
  - `attention_heldout_v1_fixtures.jsonl`: the v1 held-out set, byte-identical, with its SHA-256 pinned in a
    test.
- **held-out:** `attention_heldout_fixtures.jsonl`, a new set written after `attention_v2` is frozen.
- **fresh:** `fresh-attention.jsonl`, a new sample none of whose lines is in T077's.

The burst set and the A6 source are unchanged. The moderation suite is unchanged.

## §3 — Fixture keys

These are version 1's keys (`label_class`, `tracked`) plus the keys of data-model §8:
- **V1.** `intent`, when present, is one of the six, and `(intent == "asking") == needs_response`.
- **V2.** `peer: true` is a flag only. Rule-declinedness of in-repo `peer` lines is a test
  (`test_attention_fixture_files.py`), not a run-time check.
- **V3.** `burst` (2–5 strings) and `expected_opener` (`rule` | `model` | `none`) appear only in the burst set,
  and both are required there. `burst` replaces `text`.
- **V4.** Any violation is a `FixtureError` naming the set and the line. The run is `INCOMPLETE`, and no line is
  silently skipped.

## §4 — Scoring

- **S1. One attention line.**
  1. `normalize`, then `evaluate([text])`, which gives the opener `rule` (AE2: **no call**).
  2. Then `eligibility`, which gives `excluded`.
  3. Then the model (`role="attention"`), which gives the intent.
  4. Then `needs_response_for`, which gives `model` when true and `none` otherwise. A gateway error gives
     `error`.

  Version 1's S1 class rules then apply:
  - a clear negative counts when its opener is `model`;
  - a clear positive is missed when its opener is `none` or `excluded`;
  - ambiguous lines are reported, never gated.
- **S1b. One burst line.**
  1. `evaluate(all members)` gives `rule`.
  2. Otherwise each member goes through S1's steps 2–4, in order. The first member with needs-response true gives
     `model`, and its index is recorded.
  3. Otherwise `none`.

  Reported, never gated.
- **S2. A6 lines.** Every moderation-set line whose label has `needs_moderation` true is judged by S1's steps
  2–4, with no rule step and no veto. It counts when the intent is `asking`.
- **S3. Moderation lines** are scored exactly as in version 1 (S2, S3 for tracked lines).
- **S4. Errors.** A gateway error is an error line. It is never scored as a prediction, and any error fails A9
  (respectively Q11).
- **S5. Repeat.** Every set runs `--repeat` times.
  - Two attention runs are the same when every line's opener and intent match; for a burst line, every member's
    intent.
  - Moderation lines are compared as in version 1.
- **S6. Latency.** Median and p95 of every model call across all runs.
  - The attention suite also prints a **per-message estimate**, reported only:
    - when `--moderation-p95-ms` is given, the sum of the two p95s on a single-occupancy lane;
    - with `--serving concurrent`, the larger of the two;
    - otherwise "not computed".

## §5 — The gates

### Attention suite

| # | Gate | Passes when |
|---|---|---|
| A1 | Tuning clear negatives model-opened | = 0 |
| A2 | Tuning clear positives missed | = 0 |
| A3 | Validation: clear negatives model-opened / rule-declined clear positives missed | ≤ 1 / ≤ 1 *in each validation set* (2026-10-09) |
| A4 | Held-out: the same | ≤ 1 / ≤ 1, with at least 10 rule-declined clear positives |
| A5 | Fresh sample: the same | ≤ 1 / ≤ 1 |
| A6 | A6-source lines answered `asking` | ≤ 1 (lines listed) |
| A7 | Repeat | 0 differing lines, `--repeat` ≥ 2 |
| A8 | Latency | single-call p95 ≤ 10,000 ms |
| A9 | Errors | = 0 |

### Moderation suite

The 010 identifiers are kept so the history reads straight through.

| # | Gate | Passes when |
|---|---|---|
| Q5 | Real moderation: false negatives and false positives, excluding tracked lines | both = 0 |
| Q6 | Shipped moderation: the same | both = 0 |
| Q7 | Policy moderation | false negatives ≤ 1; false positives = 0; legitimate lines routed to `incident` = 0 |
| Q8 | Repeat | 0 differing lines, `--repeat` ≥ 2 |
| Q11 | Errors | = 0 |
| Q12 | Tracked lines | ≤ 2, each disposition ∈ {`no-link-rule`, `label-review`} |

*(2026-10-09)* **A3 per validation set.** With three validation sets, A3 passes when every one of them passes
≤ 1 / ≤ 1. Its gate line lists each set's counts. Pooling them (about 115 lines) under one ≤ 1 / ≤ 1 would hold the
v1-era sets to a stricter bar than the one they were designed for. With one validation set, as in the first cycle,
the two readings are the same.

**Verdicts:**
- **`QUALIFIED`:** every gate passes.
- **`NOT QUALIFIED`:** any gate fails.
- **`INCOMPLETE`:** no gate fails, and at least one is `NOT RUN`.
- **`CANDIDATE`:** C6.

## §6 — Reported lines (never gated)

These are printed per attention set, after the gate inputs:
- **R-ambiguous.** Ambiguous lines: answered true and agreed, with lines listed.
- **R-intent.** Intent agreement on lines that carry `intent`: n / N, with disagreeing lines listed as
  `#line label→answer`.
- **R-discussion.** Four counts, each with its lines:
  - label `asking` answered `discussion`;
  - label `discussion` answered `asking`;
  - `peer` lines correct;
  - `peer` lines judged.
- **R-rule.** Clear negatives rule-opened, with `peer` lines counted apart. This is the rule baseline on the set.
- **R-burst** (burst set only). Per line: the opener, the opening member's index, `expected_opener`, and whether
  they match. L-B1 lines are `needs_response: true` with `expected_opener: "none"`.

## §7 — Output

1. **A header:** task, profile, model, prompt version or `CANDIDATE <sha256>`, repeat.
2. **Per set:** summary counts, the class split, the reported lines, and the tracked lines (moderation).
3. **Latency and repeat lines,** plus the per-message estimate (attention).
4. **The gate table:** one line per gate, with `PASS`, `FAIL` or `NOT RUN` and the failing line numbers.
5. **The verdict line.**

Per-line detail is printed for run 1 only, as `#line [OK|FN|FP|MISMATCH] opener=… intent=…`.

## §8 — Wording selection (spec FR-330, FR-331, FR-333)

- **W-1. The candidates.** Three are fixed before any run, as files in the fixtures directory, and their SHA-256s
  are recorded in `research.md` §2 first.
  - **W1, generic:** no domain nouns.
  - **W2, P2-derived:** P2's measured asking and informing paragraphs, with its noun lists.
  - **W3:** W1 plus one sentence naming what the service provides.

  All three carry the same six intent definitions and Policy D D1–D7, word for word.
- **W-2. The matrix.** Each candidate × {e2b attention profile, e4b attention profile}, run with
  `--candidate-file … --repeat 2` over tuning, validation, the A6 source and burst. The held-out and fresh sets
  are not read; they are reported `NOT RUN`.
- **W-3. The decision rule,** written before running:
  - take the smallest model with any candidate passing A1, A2, A3, A6, A7 and A9;
  - among those, prefer W1, then W3, then W2.
  - If W2 or W3 win only on tuning lines and not on validation, record it as noun memorisation.
- **W-4. Revision.** At most one round, limited to the failing sentence of the best candidate, then a freeze.
  The frozen text becomes `attention_v1.md` with its pin and allowlist entry.
- **W-5. The held-out set** is written only after the freeze, from plan §9's topics and grid, with the peer
  minimums of spec FR-331. It is run once on the chosen pair and never edited afterwards.
- **W-6. The fresh sample** is the operator's, labelled before any run.
- **W-7. The stop condition.** If no candidate passes W-3 after the revision, the milestone stops and reports, as
  010 FR-216 did. There are no further rounds.

### §8′ — The second cycle: `attention_v2` under Policy D′ (2026-10-09)

The operator amended Policy D (option (a), 2026-10-08) and approved the addendum
(`docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`) on 2026-10-09, with every recommended option.
`attention_v1` no longer states the policy (`attention-judgement.md` §5′), so W-1 to W-7 run once more:
- **W-1′. The candidates.**
  - Each is `attention_v1.md` with its policy-bound sentences replaced by Policy D′'s, verbatim: the `asking`,
    `discussion` and `informing` definitions, Policy S's scope and D0–D7. Everything else stays byte-identical.
  - The three differ only in where D0 sits:
    - **V2-A, in place:** the policy list becomes D0–D7, in order;
    - **V2-B, scope first:** D0 directly after "The question: …";
    - **V2-C:** V2-B plus one generic sentence, "The same kind of question can be either: what decides is whose
      service it is."
  - No candidate names Qiyas, a university, a licence, or any institution in the addendum's topic lists.
  - The files are written to the fixtures directory, and their SHA-256s are recorded in `research.md` §2 before
    any run.
- **W-2′. The matrix:** {V2-A, V2-B, V2-C} × {e2b, e4b}, in candidate mode with `--repeat 2`. The held-out and
  fresh sets are withheld.
- **W-3′. The decision rule:**
  - the smallest model with any candidate passing A1, A2, A3 (every validation set), A6, A7 and A9;
  - among those, V2-A, then V2-B, then V2-C.
- **W-4′. Revision:** at most one, limited to the failing sentence of the best candidate. A policy sentence is never
  revised. The frozen text becomes `attention_v2.md` with its pin and allowlist entry; `attention_v1` is unchanged.
- **W-5′. The held-out set:**
  - It is written only after the freeze, on the topics fixed in the addendum §6.6 before any v2 candidate:
    - outside institutions: embassy or visa, degree equivalency, the labour office, civil service;
    - the course's own service: subscription, discount code, question bank, simulated test.
  - Its minimums are spec FR-331's (2026-10-09).
  - It is run once and never edited afterwards.
- **W-6′. The fresh sample** is the operator's: 20–30 real messages, none of them in T077's sample, labelled under
  D′ before any run.
- **W-7′. The stop condition:** if no candidate passes W-3′ after the revision, the cycle stops and reports.
  `attention_v1` stays frozen and unqualified under D′, and opening stays rules-only. There are no further rounds.

## §9 — What the result means operationally

- **R1.** `MODERATION_AI_ATTENTION_FROM` may be set on a host only when its active `attention` profile and
  `MODERATION_ATTENTION_PROMPT_VERSION` gave `QUALIFIED` there.
- **R2.** A change to the active moderation profile or `MODERATION_PROMPT_VERSION` requires a `QUALIFIED`
  moderation suite on that host.
- **R3.** After switch-on, the pilot is governed by C9′'s `attention` row: dismissed (any reason) ÷ opened ≤ 10%
  over the first 30 or more items. Above that, the switch is blanked.
- **R4.** Results are recorded as counts in `research.md` §2.

## §10 — What may never happen

- **N1.** Printing message text, or writing anything.
- **N2.** A second definition of the benchmark path, AE1–AE2, the derivation, the route or eligibility.
- **N3.** Ambiguous or burst lines counted in a gate, or tracked lines silently dropped.
- **N4.** `QUALIFIED` with a required set missing, `--repeat` < 2, or a candidate file.
- **N5.** A held-out set written or edited after its results were seen, or validation results seen before the
  held-out topics were fixed.
