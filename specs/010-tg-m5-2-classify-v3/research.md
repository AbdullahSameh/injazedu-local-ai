# Research: TG-M5.2 — classify_v3 and Model Qualification

Every figure here is a count or a line number; no message text appears (pipeline N-rules). Line numbers are the
benchmark tools' `#N`, which skip blank lines. The full tables and option analysis are in the plan of record,
`docs/plan/telegram/tg-m5-classify-v3-plan.md`: §1–§4 cover the root cause, §14 the tuning outcome and §16 the
larger model.

Decision numbers continue from 009's D-TG-171.

## §0 — Findings carried in

**Finding 10 — needs-response follows the topic, not the function.** TG-M5.1's Finding 9 is now explained.
- Under `classify_v1` and `classify_v2`, needs-response was a **pure function of the category** on all 48
  attention fixtures:
  - QUESTION_* and COMPLAINT gave true;
  - CHITCHAT and OTHER gave false.
- Both question categories are defined by topic lists, and the only explicit "false" path is the purely social
  category.
- 12 of 20 clear informing or resolved-status statements were model-opened under both versions. The relevant
  lines are byte-identical in v1 and v2.
- Exact wording: plan §2, W1–W7.

**Finding 11 — on the 2B-effective model, one prompt cannot hold both policies.**
- Wording that separates asking from informing removes every clear false positive on the Attention side.
- The same wording moves the advert boundary:
  - a legitimate question is opened as an incident;
  - a real outside announcement is no longer flagged.
- Three tuning rounds found no wording that satisfies both (plan §14).

**Finding 12 — a 7.5B model holds both, apart from two boundary cases.** This is `gemma4:e4b-it-qat` with the
probe wording P2 (plan §16).

| Measure | e2b + `classify_v2` | e4b + P2 |
|---|---|---|
| Clear negatives opened | 13 of 27 | **0 of 27** |
| Clear positives missed | 0 of 13 | 0 of 13 |
| Ambiguous answered true | — | 15 of 23 |
| Policy set (64) | — | 64/64, no legitimate → incident |
| Real moderation | — | 11/12: #1, the outside announcement |
| Shipped moderation | — | 11/12: #11, the insulting accusation, read as COMPLAINT |
| Repeat run | — | identical |
| Median latency | 0.85 s | 1.36 s |

The accusation comes back COMPLAINT with needs-response true, so the model still opens an Attention item for
it.

**Finding 13 — the development machine cannot host the production class.** It has 16 GB, and Docker holds
7.8 GiB.
- With e4b loaded, macOS swap rose from 6.6 GB to 10.3 GB.
- The 12B variant (7.15 GB) was not tried.
- Production will run on a powerful host (spec clarification 2026-10-04).

## §1 — Decisions

**D-TG-172 — The `classify_v3` wording: principles, starting draft and freeze protocol.** FR-202–FR-205.
- **Principles** (plan §6):
  - function over topic on the question side;
  - one asking/informing test, whose "mixed" case counts as asking;
  - informing statements belong in OTHER;
  - Policy S stated once;
  - v2's advert, abuse and needs-moderation wording kept byte-identical, together with the "Always false for
    SPAM_OR_AD, ABUSE and CHITCHAT." sentence;
  - no benchmark strings and no fixture-shaped nouns.
- **Starting draft:** the measured P2, with its noun lists made generic and one "mixed" sentence added
  (`contracts/classify-v3.md` §2).
- **Size cap:** at most v2 + 1,200 characters. This reads FR-205's "about 1,000". P2 measured +1,118 and the
  starting draft +1,084 (characters, not bytes; v2 is 2,645).
- **Freeze protocol.** At most **two** measurement rounds through the qualification command on the e4b
  reference profile.
  - F1 measures the starting draft.
  - F2 runs only if F1 fails a tuning gate that P2 passed, and it may only move the wording back toward P2's
    measured text.
  - Then the file is pinned by SHA-256, or the milestone stops under FR-216.
  - e2b results are recorded for information; e2b is not expected to qualify.
- **Rejected:**
  - more rounds (overfitting; plan §12);
  - R1–R3's placements (measured worse on both models; plan §14, §16).

**D-TG-173 — Policy S.** Spec clarification 2026-10-04.
- A member's bare statement of a course arrangement, with nothing added, counts as a check: needs-response true.
- Missing a real question is worse than an ambiguous false positive, which moderators dismiss.
- Ambiguous fixtures are reported and never gated.

**D-TG-174 — The qualification gate.** FR-208; the thresholds are in `contracts/qualification.md` §4.
- The gate is absolute: it uses `classify_v2`-on-e2b's measured advert numbers as the floor and does not re-run
  a baseline on each qualification.
- A pair is qualified only when every hard gate passes and every required set ran.
- **Rejected:**
  - a relative "no worse than a baseline run" check, which doubles every run and lets a weak baseline excuse a
    weak candidate;
  - pooling clear and ambiguous results.

**D-TG-175 — One call per message.** The separate-judgement design (plan §15 Option B) is rejected.
- It adds a second call and a schema change to every deployment, only to work around a small model.
- Production will run a larger model, and e4b already passes the Attention side with one call.
- **FR-216:** if no production-class model qualifies, Option B becomes its own specification.

**D-TG-176 — Two tracked exceptions, a closed list** (spec clarification, FR-212, Option A):
- real moderation #1 → disposition `no-link-rule`;
- shipped moderation #11 → disposition `label-review`.

Rules:
- They are reported on every run and never fail qualification.
- Any other missed violation, or any legitimate message flagged or routed to an incident, fails.
- The command refuses any disposition other than these two. A third tracked line fails qualification,
  because the limit of 2 is checked mechanically.
- The accusation's exception ends on the operator's label review (ABUSE confirmed makes it a hard gate). The
  announcement's ends when the no-link rule ships. Ending either means removing its `tracked` field.

**D-TG-177 — Label class and tracking are optional fields on the fixture line, not separate files or command
arguments.**
- `label_class` is `clear` (the default) or `ambiguous`, on attention fixtures.
- `tracked` is `no-link-rule` or `label-review`, on any fixture.
- The existing smokes ignore unknown keys, so every current file keeps working unchanged.
- The operator annotates the external files; the implementer annotates only the shipped synthetic ones, as
  listed in data-model §1, and lists them for review. **A label (`needs_response`, `category`,
  `needs_moderation`) is never changed.**
- **Rejected:**
  - splitting files, which restructures the operator's data;
  - `--ambiguous 5-13` style arguments, whose line ranges go stale silently.

**D-TG-178 — The qualification command reuses the smokes' per-fixture judgement.**
- `smoke_attention` and `smoke_moderation` each gain one extracted function that judges one fixture, using the
  same calls in the same order (normalise, rules, eligibility, model, `route_prediction`,
  `proposes_attention`; N7).
- Their printed output and exit codes are unchanged, and their existing scoring tests still pass.
- **Rejected:** copying the orchestration into the new command, which would be a second definition of the
  benchmark's path.

**D-TG-179 — Latency proxy: p95 single-call time ≤ 10 s.**
- With one classifier thread and a 90 s settle, a p95 of 10 s lets a queue of about 8 messages still land
  before the settle (SC-207).
- The command measures single-call latency only. Load is the pilot's to observe.

**D-TG-180 — Candidate profiles are registered inactive, through the panel's Model Profiles page or one
insert. The seed roster is unchanged.**
- The e4b reference row (id 17) already exists in development.
- The production host registers its own candidates.
- **Rejected:** adding candidates to `seed_profiles.py`, which would ship a model choice that only the host's
  qualification can make.

**D-TG-181 — Where the work is recorded.**
- The frozen bytes go into 008's pipeline contract as §2b, beside §2 and §2a.
- 009 gets dated pointer notes: G4's "both instructions" becomes "every instruction", and the quickstart points
  to the qualification.
- History is never rewritten.

## §2 — Qualification runs

To be filled during implementation, counts only. The F1 and F2 rounds, the frozen hash, the held-out run on e4b,
and later the production host's runs.

### Baseline before any change (T001, 2026-10-04)

`make check` before the first edit, with Ollama **running** (the live stack was using it; the Ollama-quit proof
is T035's):
- ruff, the architecture and domain-boundary checks, and mypy: green.
- pytest: 911 passed, **4 failed**, all in `tests/moderation/test_secret_scan.py`. The secret scan's `*_KEY = …`
  heuristic flags `by_key = {…}` at `tests/moderation/classification/test_metrics_model_opened.py:129`, a
  TG-M5.1 test that became Git-tracked in commit `2431adc`. It predates this milestone and is not caused by it.
  The PHP feature test and the secret-scan step did not run, because `make check` stops at pytest.
- Fixing it means renaming that test's local variable. That is a TG-M5.1 file, so the edit is left to the
  operator's decision.

### Development baseline: e2b + `classify_v2` (T013, 2026-10-04)

`make qualify-moderation PROFILE=ollama-gemma4-e2b-moderation PROMPT=classify_v2 FIXTURES_DIR=~/Projects/injaz-m5-fixtures`

- **Model:** `gemma4:e2b-it-qat` (inactive profile).
- **Run:** floor 0.600, threshold 0.850, `--repeat 2`, 300 calls, 4 min 34 s on the development machine.
- **External sets:** not annotated yet (T031), so every real attention line counts as `clear`, and real
  moderation #1 is not yet tracked.
- **Writes:** none. No `model_runs` or `message_classifications` row was written in the run window (C2).
- **Text:** none in the output. No Arabic character appeared (C3).

| Gate | Status | Counts |
|---|---|---|
| Q1 | FAIL | 14: `real-attention-extra.jsonl` #13, #15, #16, #17, #19, #20, #21, #22, #23, #24; `real-attention.jsonl` #18, #21, #22; shipped #10 |
| Q2 | NOT RUN | the held-out set is not written yet (Phase 5) |
| Q3 | FAIL | 2: `real-attention-extra.jsonl` #2, #5. Both may be among plan §13's proposed-ambiguous lines; the operator's annotation (T031) decides whether they stay gated. |
| Q4 | NOT RUN | the held-out set is not written yet |
| Q5 | PASS | real moderation: needs-moderation 12/12, false negatives 0, false positives 0 |
| Q6 | PASS | shipped moderation: false negatives 0, false positives 0, tracked #11 excluded |
| Q7 | PASS | policy: false negatives 1 (#17), false positives 0, legitimate → incident 0 |
| Q8 | PASS | 0 differing lines between the two runs |
| Q9 | NOT RUN | no `fresh-attention.jsonl` yet |
| Q10 | PASS | p95 977 ms, median 880 ms |
| Q11 | PASS | 0 errors |
| Q12 | PASS | 1 tracked line: shipped moderation #11 `label-review`, which passed (needs-moderation agreed) |

- **Ambiguous (reported only):** shipped attention #4–#6 were answered true 3/3.
- **Per set, clear negatives model-opened:** `real-attention-extra.jsonl` 10 of 12, `real-attention.jsonl` 3 of 9,
  shipped 1 of 7.
- **Result:** `NOT QUALIFIED` (exit 1), as expected. Q1 fails, and the held-out set and fresh sample are
  `NOT RUN`.

### F1: the starting draft (T021–T024, 2026-10-04)

`classify_v3.md` was built by script from v2's bytes and `contracts/classify-v3.md` §2: 3,729 characters
(v2 + 1,084). Provisional pin `b8039d94…e9aa6c`. The tools image was rebuilt; no running service was
changed or set to v3 (X3).

**How the gate is read for the freeze.** The external sets are not annotated yet (T031), so the command
counts every real attention line as `clear` and does not track real moderation #1. P2's reference figures
(plan §16) used plan §13's label classes. The freeze compares like with like: the printed gate, plus the
same gate re-read under plan §13's proposed annotations (`real-attention.jsonl` #5–#13 and
`real-attention-extra.jsonl` #1–#7, #10–#12, #19 ambiguous; real moderation #1 `no-link-rule`). The
re-reading comes from the per-line output of run 1. Nothing was re-run, and no fixture file was touched.

**e4b + F1** (`gemma4:e4b-it-qat`, profile id 17), `--repeat 2`, 300 calls, 7 min 27 s. No row was
written (`model_runs` 22, `message_classifications` 19 and `message_classification_attempts` 8, before
and after; C2). No Arabic character appeared in the output (C3).

| Gate | Printed | Under plan §13's annotations | e4b + P2 (plan §16) |
|---|---|---|---|
| Q1 | FAIL, 1: `real-attention-extra.jsonl` #15 (QUESTION_COURSE, needs-response true) | **FAIL, 1** (#15 is a clear negative there too) | 0 of 27 |
| Q3 | FAIL, 7: extra #6, #7, #10; original #7, #9, #11, #13 | PASS, 0: all 7 are proposed-ambiguous | 0 of 13 |
| Q5 | FAIL: false negatives 1 (#1), false positives 0 | PASS: #1 tracked, `no-link-rule` | 11/12 (#1) |
| Q6 | PASS: 0 / 0; tracked #11 `label-review` FAIL (read COMPLAINT, as under every e4b prompt) | PASS | 11/12 (#11) |
| Q7 | PASS: 64/64, legitimate → incident 0 | PASS | 64/64 |
| Q8 | PASS: 0 differing lines | PASS | identical |
| Q10 | PASS: p95 1,807 ms, median 1,396 ms | PASS | median 1.36 s |
| Q11 | PASS: 0 errors | PASS | — |
| Q12 | PASS: 1 tracked line | PASS: 2 tracked lines | — |
| Q2, Q4, Q9 | NOT RUN (held-out not written; no fresh sample) | NOT RUN | — |

- **Ambiguous answered true, under plan §13's classes:** 14 of 23 (original 5/9, extra 7/11, shipped
  2/3), beside P2's 15/23. Shipped #4 came back false.
- **Result:** `NOT QUALIFIED` (exit 1).

**e2b + F1, information only** (`gemma4:e2b-it-qat`, profile id 14), 300 calls. Again no row and no text.
- Q1 FAIL, 2: extra #16, #17.
- Q3 FAIL, 13: extra #1, #2, #3, #5, #6, #7 and original #5, #6, #7, #9, #10, #11, #13. All are
  proposed-ambiguous.
- Q5 FAIL (#1, untracked). Q6 PASS, with tracked #11 PASS.
- Q7 FAIL: policy #21 false positive, routed to `incident`. This is the same e2b flip as under P2, R1 and R2
  (plan §14).
- Q8 PASS, 0 differing. Q10 PASS, p95 891 ms. Q11 PASS. Q12 PASS.
- Ambiguous answered true: 6 of 23. Result `NOT QUALIFIED`. As expected, e2b does not qualify (D-TG-172).

**Readings.**
- **T022 (US2):** Q3 = 0 on e4b under the proposed annotations; ambiguous 14/23 beside P2's 15/23. Q3 does
  not fail where P2 passed.
- **T023 (US3):** Q5–Q7 pass on e4b, with real moderation #1 and shipped #11 as the tracked lines. No
  legitimate line was routed to `incident`.
- **T024:** F1 fails **Q1**, a tuning gate P2 passed (one line, extra #15), so F2 runs.

**The F2 edit (operator's choice, 2026-10-04).** F1 differs from P2 in exactly three places: the Asking
noun list made generic (FR-205), the Informing scope made generic (FR-205), and the added sentence "A
message that informs and also asks is asking." (FR-202's Mixed). Restoring P2's nouns would mirror the
failing line's own topic (FR-205, X4's spirit). The operator chose instead to **drop the mixed sentence**,
which brings the Informing bullet back to P2's shape.
- **Ruling:** FR-202's Mixed is now carried by P2's measured wording, "False when the message only informs"
  (needs_response) and "a message that only informs" (OTHER). A message that informs and also asks does not
  only inform.
- The held-out set's 3 mixed lines test it.
- F2 is 3,681 characters (v2 + 1,036), provisionally re-pinned `872ccf54…a00d8e8`.

### F2 and the stop (T024, 2026-10-04)

**e4b + F2** (pin `872ccf54…a00d8e8`), `--repeat 2`, 300 calls. No row was written (22 / 19 / 8, before
and after; C2), and no Arabic character appeared in the output (C3).

| Gate | Printed | Under plan §13's annotations | F1 |
|---|---|---|---|
| Q1 | FAIL, 1: extra #15 (QUESTION_COURSE, needs-response true) | **FAIL, 1** | FAIL, 1 (#15) |
| Q3 | FAIL, 7: the same proposed-ambiguous lines as F1 | PASS, 0 | PASS |
| Q5 | FAIL: #1, untracked | PASS: #1 tracked | PASS |
| Q6 | **FAIL**: false positive 1, shipped #12 (labelled OTHER) read SPAM_OR_AD, routed to `incident`; tracked #11 FAIL (COMPLAINT) | **FAIL**: legitimate → incident 1 | PASS (#12 read CHITCHAT/false) |
| Q7 | PASS: 64/64, legitimate → incident 0 | PASS | PASS |
| Q8 | PASS: 0 differing lines | PASS | PASS |
| Q10 | PASS: p95 1,995 ms, median 1,481 ms | PASS | PASS |
| Q11 | PASS: 0 errors | PASS | PASS |
| Q12 | PASS | PASS | PASS |

- **Ambiguous answered true, under plan §13's classes:** 14 of 23, identical per line to F1.
- **Result:** `NOT QUALIFIED` (exit 1).

**Decision: stop (FR-216, `contracts/classify-v3.md` §3 step 5).**
- F2 fails a tuning gate on e4b, so no `classify_v3` is frozen, and there are no further rounds.
- The held-out set is not written (it follows a freeze only), so T025–T027 do not run.
- **No final hash.** The working tree holds F2's bytes under a *provisional* pin only. Per §3 step 1, nothing
  of `classify_v3` is to be committed until a freeze. Whether to keep or remove the provisional file,
  allowlist entry, pin and tests is the operator's decision.

**What the two rounds show (counts only):**
- **Extra #15** (a clear negative) is model-opened under F1 and F2 alike, but not under P2. The only
  wording F2 still has that P2 lacks is the two generic noun scopes (FR-205). On e4b, P2's 0/27 rested on
  its explicit course nouns, which principle 6 and FR-205 remove as fixture-shaped.
- **Shipped #12** (legitimate) flips between F1 (CHITCHAT/false, route none) and F2 (SPAM_OR_AD/true,
  `incident`) on a one-sentence change to the needs-response wording. e4b + v2 also routed it to `incident`
  (plan §16). The advert boundary on e4b is as fragile to needs-response wording as on e2b (Finding 11).
- **Not shown:** whether a larger production-class model qualifies with F1 or F2. FR-216 asks for the stop
  and a proposal; it does not forbid measuring candidates on the production host.

**Proposed next step (FR-216):** a separate needs-response judgement (plan §15 Option B), as its own
specification. The operator may instead first qualify a production-host candidate against a v3 candidate.
That is a decision outside this milestone's protocol.

### Closure (2026-10-06)

**TG-M5.2 is closed as stopped under FR-216**, by the operator's decision of 2026-10-06.
- **Removed:** `classify_v3.md`, its `ModerationPromptVersion` entry, its provisional pin, and the v3-only
  tests in `test_prompt_pinned.py`, `test_prompt_version.py`, `test_model_input.py`, `test_classify_one.py`
  and `test_config_classification.py`. Those five files are back to their committed content.
- **Kept and reusable:**
  - the every-instruction G4 test;
  - `make qualify-moderation`, with its scoring S1–S6 and gate Q1–Q12;
  - the extracted per-fixture judgements;
  - fixture validation and the `label_class`/`tracked` keys, with the shipped annotations;
  - every measurement and decision above.
- **Development runtime:** `ollama-gemma4-e2b-moderation` (id 14) is active again, with `classify_v2`.
  `ollama-gemma4-e4b-moderation` (id 17) stays registered and inactive, and `gemma4:e4b-it-qat` stays
  pulled. Both remain available for later qualification.
- **Not created:** the held-out set (Phase 5), because nothing froze.
- **Next:** a separate needs-response judgement (plan §15 Option B), planned as TG-M5.3 in
  `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`.
