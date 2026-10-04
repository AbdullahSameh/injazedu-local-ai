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
