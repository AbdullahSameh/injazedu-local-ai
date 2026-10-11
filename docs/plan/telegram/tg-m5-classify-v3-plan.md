# TG-M5 follow-up: `needs_response` quality — root cause and a `classify_v3` plan

**Status:** analysis and plan only, 2026-10-04. Nothing is implemented and nothing is committed.
Implementation, and decisions D1 and D2 (§5), wait for the operator's go-ahead.
**Update, same day:** the operator chose Policy S and approved the plan. Tuning reached the stop condition after
3 rounds, and no `classify_v3` was frozen. See §14 for the evidence and §15 for the options.

## Context

TG-M5.1 (AI-assisted Attention Opening) works as designed. On the operator's new paired benchmark, `classify_v2`
opens an item for 10 of 12 statements that inform rather than ask. Every such item is new moderator work. If
nobody dismisses it, it expires and counts as **unanswered against the responsible moderator, permanently**
(TG-M3 G3). The task is to find why, separate prompt faults from label ambiguity and model limits, and propose a
fix that leaves TG-M5.1, the rules, the taxonomy and v1/v2 untouched.

Text from the fixtures is never quoted here; this file goes into Git. Cases are cited by the smoke's `#N` and
an English gloss. ⚠ Line 13 of `real-attention-extra.jsonl` is blank and the smoke skips it, so from #13 on, the
smoke's `#N` is file line N+1. (A browser-saved folder, `real-attention-extra.jsonl_files/`, sits beside the
fixture. It is harmless and outside the repo.)

## 0. How this was measured

- **Reproduced first.** I ran `make smoke-attention --prompt classify_v2` on both sets: 21/24 and 12/24, the
  same line numbers as reported.
- **The model.** `gemma4:e2b-it-qat` at temperature 0, deterministic. It is the only chat model installed.
- **v1 on both sets**, for comparison.
- **Two diagnostic probes, P1 and P2.** The v2 text is swapped *in memory* inside the tools container, through
  the same `normalize → redact → gateway → route_prediction → proposes_attention` path. No file in the repo, no
  pinned prompt and no DB row changed. They are probes, not a frozen v3.
  - **P1** is v2 plus three things: an "asking vs informing" paragraph; QUESTION_* defined by what the writer
    *wants*, with "still has" a problem; and OTHER described as the place for informing.
  - **P2** is P1 plus an explicit tie-break: a member's bare statement of a course arrangement counts as a check.
- **The advert side** (`smoke-moderation`), for v2 against P2, on the real 12 and the 64 synthetic policy cases.

## 1. Root cause in one paragraph

`classify_v2` decides `needs_response` by **topic**, never by **function**. Each QUESTION_* category is
described by a list of topics: lecture times, links, content, materials, exams; course or book, log in.
`needs_response` follows from the category: "true only if the writer asks a question…", and the schema emits
`category` first. The only explicit path to `false` is "Always false for … CHITCHAT", and CHITCHAT is "only
social". So an on-topic statement with no social marker has nowhere to go except QUESTION_*, and comes back
`true`.

Measured across all 48 rows (v1 and v2): **`needs_response` is a pure function of the category.**
QUESTION_* and COMPLAINT give true; CHITCHAT and OTHER give false. **Every correct `false` on an on-topic message
came from miscalling it CHITCHAT** because it carried praise, thanks or a prayer; that is 8 of 8. **Every
neutral statement that informs came back `true`**; that is 0 of 12 correct. The QUESTION_* and `needs_response`
lines are **byte-identical in v1 and v2**, and v1 produces the **same 13 false positives**. v2's advert changes
neither caused this gap nor touched it.

## 2. The v2 wording that produces it (exact quotes from `classify_v2.md`)

| # | Wording | Effect |
|---|---|---|
| W1 | `QUESTION_COURSE: a question about the course itself — lecture times, links, content, materials, exams.` | "A question" is never defined. The dash list is a topic list, so a *statement* about a lecture time, a link or an exam matches it. |
| W2 | `QUESTION_ACCESS: a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.` | Topic list again. Nothing requires the problem to be **still** happening, so "the platform works again", "content now shows complete" and "the book is available on the platform" all landed here. |
| W3 | `CHITCHAT: a message that is only social — greetings, thanks, congratulations, prayers, emoji — with nothing offered or promoted.` | The only category with a forced `false`. "Only social" excludes a neutral on-topic statement. |
| W4 | `OTHER: none of the above.` | A residual category is never reached when W1 or W2 already matches on topic. |
| W5 | `needs_response: true only if the writer asks a question or reports a problem that a moderator should answer. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.` | "Asks" is not defined, and nothing says questions often lack `؟`. Informing, confirming and reporting a resolution are never named as `false`. "Reports a problem" covers reporting that a problem has been *solved*. Once QUESTION_* is emitted, "asks a question" confirms itself. |
| W6 | `Judge what the whole message is for, not how it opens: … around an offer does not make it chitchat.` | The "function over form" principle exists, but it is scoped to offers only. The question side has no counterpart. |
| W7 | `confidence: … how sure you are of the category.` | Confidence speaks to the category, not to `needs_response`. It cannot gate attention even in principle. |

## 3. The 12 paired-benchmark mismatches (v2)

Label classes: **CP** = clear_positive, **CN** = clear_negative, **AMB** = ambiguous. A label is CN when the
message supplies the answer itself (a time, day, place, deadline or where to find it), passes on an
announcement, or reports a resolved state, *and* carries no request or tag (such as "right?"). A bare
subject-plus-predicate with none of those is AMB: without intonation, a yes/no check and the same statement are
identical text.

| # | Gloss | Label | v2 output | P2 output | Causes |
|---|---|---|---|---|---|
| 2 | "the meeting today" | true → **AMB** | CHITCHAT/F 0.95 | OTHER/F | Label ambiguity; model limitation (lexical: "meeting" reads as social). The parallel "exam today" in set A was answered true. |
| 5 | "the link got updated" | true → **AMB** | OTHER/F 0.80 | OTHER/F | Label ambiguity; model limitation. **Inverted** against its pair #17: v2 says this bare form is false but the detailed one is true, so v2 is not reading informativeness at all. |
| 13 | "live session tonight at 8" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |
| 15 | "registration still open until end of week" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |
| 16 | "appointment changed, now Thursday" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |
| 17 | "link updated and posted in the group" | false → **CN** | QA/T 0.90 | OTHER/F ✓ | Prompt gap (W2, W5) |
| 19 | "book available now on the platform" | false → **AMB** | QA/T 0.95 | OTHER/F ✓ | Prompt gap; **benchmark-label problem**: "on the platform" is the obvious location, not the answer, so a yes/no check reads the same. Pair #7/#19 is weak. |
| 20 | "content shows complete for me now" | false → **CN** | QA/T 0.95 | OTHER/F ✓ | Prompt gap (W2: no "still"; W5) |
| 21 | "platform works normally again for me" | false → **CN** | QA/T 0.90 | OTHER/F ✓ | Prompt gap (W2, W5) |
| 22 | "course still available until end of month" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |
| 23 | "recording exists and is on the platform" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |
| 24 | "exam next week, on Tuesday" | false → **CN** | QC/T 0.95 | OTHER/F ✓ | Prompt gap (W1, W5) |

**Taxonomy limitation, partial, in all 10 false positives.** No category *names* the on-topic informing
statement; OTHER is only a residual. P1 and P2 show that a sentence in OTHER's *description* is enough, so no
new category is needed.

**Set A's 3 false positives** are #18 "link posted in the group", #21 "class cancelled today as the teacher
said" and #22 "platform works again for me now". By the same criteria all three are **CN**, with the same
causes: W1, W2 and W5. Set B shows they were not label noise but the same systematic gap.

## 4. Is it actually a prompt problem? Yes for the clear cases; the model limits the ambiguous ones

Label counts over both sets (n=48): 8 CP, 20 CN, 20 AMB (19 labelled true, 1 labelled false).

| Instruction | CP missed (of 8) | CN model-opened (of 20) | AMB answered true (of 20) | Pairs separated (B 12 + A 7) | Set A agreement / FN / FP | Set B agreement / FN / FP |
|---|---|---|---|---|---|---|
| v1 | 0 | **12** | 18 | — | 20/24 · 1 · 3 | 13/24 · 1 · 10 |
| **v2** | 0 | **12** | 18 | 5/19 (4 of them only through the CHITCHAT marker) | 21/24 · 0 · 3 | 12/24 · 2 · 10 |
| P1 (probe) | 0 | **0** | 6 | — | 17/24 · 7 · 0 | 18/24 · 6 · 0 |
| P2 (probe) | 0 | **0** | 10 | 11/19 | 18/24 · 6 · 0 | 21/24 · 3 · 0 |

Openers (rule / model / none):

| Set | Instruction | Expected true | Expected false |
|---|---|---|---|
| A | v2 | 6 / 9 / 0 | 0 / **3** / 6 |
| A | P2 | 6 / 3 / 6 | 0 / **0** / 9 |
| B | v2 | 1 / 9 / 2 | 0 / **10** / 2 |
| B | P2 | 1 / 8 / 3 | 0 / **0** / 12 |

Category exact (secondary):

| Instruction | Set A | Set B |
|---|---|---|
| v2 | 13/15 | 9/12 |
| P2 | 8/15 | 7/12 |

The probes drop category agreement because AMB positives become OTHER.

- **Prompt-policy gap, confirmed.** Defining "informing" removes **all 12 clear-negative false positives**,
  with **0 clear-positive misses**. The model *can* draw the distinction once it is asked for.
- **Model limitation and label ambiguity on bare declaratives.** P2 states the operator's labelling policy
  outright, yet the model follows it on only about half the AMB cases. It reads a complete
  subject-plus-predicate ("X is today", "X arrived", "X is cancelled") as informing. All 9 of P2's misses are
  AMB. No wording can recover what the text does not contain; a larger model would follow a stated tie-break
  more consistently, but would not resolve the ambiguity.
- **Shared-prompt cross-effect: a real risk, measured.** One prompt produces both `needs_response` and
  `needs_moderation`, and P2 regressed the advert side:

  | Instruction | Real moderation (12): needs_moderation / FN | Synthetic policy (64): FN / FP | Legitimate → incident |
  |---|---|---|---|
  | v2 | 12/12 · 0 | 1 / 0 | 0 |
  | P2 | 11/12 · **1** (#1, an outside announcement) | 0 / **1** (#21, a "does anyone have the file?" question) | **1** |

  The "informing" frame leaks into the violation side, and small wording changes flip borderline adverts, as
  the v2 work also found.
- **Confidence.** Wrong answers came back at 0.80–1.00 under every instruction. It is no signal, as Finding 2
  already says.
- **The benchmarks barely test the model's real job.** Only **one** clear positive in either set is one that
  the rules decline (B#8, "content shows incomplete for me"); the rest are rule-opened or AMB. The held-out set
  must fix this (§9).

**Verdict:** `classify_v3` is justified. It removes a measured, deterministic, high-volume fault (60% of clear
negatives model-opened) with a wording change the model demonstrably follows. **Stop condition:** if no v3
draft holds the advert side within 3 tuning rounds, the 2B model is carrying two policies in one prompt beyond
its capacity. The recommendation then becomes a model or profile change (M1 territory), not a longer prompt.

## 5. Decisions needed from the operator

- **D1. The labelling policy for a bare statement (AMB).** This is not a linguistic fact; it is a product
  choice.
  - **S, recommended.** A member's bare statement of a course arrangement or material, with no detail,
    attribution or social marker, counts as a check, so `true`. This matches the labels in both sets and in
    the shipped synthetic set. Moderators' messages never reach the model (E5), and members rarely announce
    arrangements.
  - **M.** `true` only when the message leaves out something the writer needs, such as "changed — to when?".
    Under M, "the exam is today" or "the class is cancelled" is `false`.

  Either way, **AMB cases are reported and never gated**. Under TG-M5.1 a model miss on an AMB case costs no
  more than the rules-only baseline: the rules decline it either way. A model false positive is net new work
  plus a permanent "unanswered" if nobody dismisses it. That asymmetry is why the gate (§10) is strict on clear
  negatives and lenient on AMB.
- **D2.** The fixture labels to review (§13). I change none.

## 6. Design principles for `classify_v3`

1. **Function over topic** on the question side, mirroring v2's "function over opener" for adverts.
   - QUESTION_COURSE: "the writer **asks** about the course itself — …" (the topic list stays, as scope).
   - QUESTION_ACCESS: "the writer **still has** a problem reaching what was paid for — …".
2. **One asking-vs-informing test, scoped to `needs_response` only**, with an explicit firewall: "This decides
   needs_response only. Informing never makes an offer or promotion acceptable: judge needs_moderation by the
   group's rule as before." This answers P2's cross-effect.
   - **Asking:** a question or request; a problem the writer still has; [D1's sentence]. Say once that
     members often ask without a question mark.
   - **Informing:** the message supplies what an asker would need (time, day, place, deadline, where to find
     it); passes on what was announced; confirms that something arrived, appeared or works for the writer; or
     says a problem is solved.
   - **Mixed:** informing *plus* a request or a remaining problem is asking. This guards against
     overcorrection.
3. **A home for informing inside the existing taxonomy.** OTHER's description becomes "none of the above,
   including a message that only informs about the course". No new category, field or schema change.
4. **The ambiguity is handled within the schema**, by D1's single stated tie-break. There is no uncertainty
   field, and confidence is not used.
5. **Kept byte-identical from v2:** the intro, the group rule, the function-over-opener paragraph, CHITCHAT,
   SPAM_OR_AD, ABUSE, needs_moderation, severity, confidence, the output line, and **"Always false for
   SPAM_OR_AD, ABUSE and CHITCHAT."**, which G4 rests on.
6. **No examples and no benchmark strings.** Concepts only, in English, as v2 did. The fixture-shaped noun list
   in P2 ("session, test, recording, link, book, change, registration") becomes "a course arrangement or
   material".
7. **A length cap.** At most v2 + about 1,000 characters (≈ +250 tokens; v2 is 2,645 characters, P2 about
   3,800). If the gate needs more than that, the model is the limit (§4's stop condition).
8. **The static sentence "Moderators' messages are never sent to you."** It is a constant fact (E5), so not
   per-message sender data, and P1–P5 ("the model sees words, never people") hold. Surfaced here rather than
   slipped in.

The starting draft is P2, with principles 2, 6 and 7 applied. It is not frozen.

## 7. What does not change

- **TG-M5.1:** architecture, `source='ai'`, `request_rejudgement`, `open_item`, bursts, the 90 s settle,
  `opened_at`, attribution, response matching, FRT, catch-up as measurement only, `MODERATION_AI_ATTENTION_FROM`,
  idempotency, dual-purpose.
- **TG-M3:** rule set v1, the QUESTION_PATTERNS and ACK_STOPLIST literals, `RULE_VERSION`.
- **TG-M5 core:**
  - `taxonomy_version` (stays **1**) and the seven categories;
  - the schema and its field order;
  - eligibility, routing and thresholds (0.60 / 0.85);
  - the gateway and profiles;
  - the `ai-classifier` queue;
  - the redaction boundary and first-posted text;
  - immutable predictions.
- **Instructions:** `classify_v1.md` and `classify_v2.md` stay byte-identical. The default
  `MODERATION_PROMPT_VERSION` stays `classify_v1`, and v3 is opt-in like v2.
- **Other:** `smoke_attention.py` and `smoke_moderation.py`, whose `--prompt` choices derive from
  `PROMPT_VERSIONS`; no migration; no PHP, since the panel already splits every figure by `prompt_version`
  (K3); the fixture files outside the repo.
- **Rejected:**
  - reordering the schema so that `needs_response` comes first (a contract change);
  - a separate call or prompt for each purpose (an architecture change);
  - adding rule phrases (product decision).

## 8. Files that would change (after go-ahead)

- **New: `apps/ai-api/app/prompts/moderation/classify_v3.md`.** The frozen wording.
- **`apps/ai-api/app/infrastructure/config.py`:** `ModerationPromptVersion` gains `"classify_v3"`. The default
  is unchanged. `PROMPT_VERSIONS`, `_INSTRUCTIONS` in `app/application/moderation/classification.py` and the
  smoke `--prompt` choices all follow from it.
- **Tests (model scripted):**
  - `tests/moderation/classification/test_prompt_pinned.py`: the v3 SHA-256; v1 and v2 unchanged.
  - `test_prompt_version.py` and `test_config_classification.py`: v3 is accepted, the default is still v1,
    and an unknown version is refused.
  - `test_model_input.py`: v3's bytes are sent as `system`.
  - New: every pinned instruction contains the G4 sentence verbatim.
  - The `test_classify_one` case stores `prompt_version='classify_v3'`.
- **New, written after freezing: `apps/ai-api/app/scripts/attention_smoke_heldout_clear.jsonl` and
  `attention_smoke_heldout_ambiguous.jsonl`.** Synthetic only. Two files, so the tool needs no change to score
  clear and AMB separately.
- **`.env.example`:** the comment lists `classify_v3`.
- **`specs/008-tg-m5-ai-classification/`:**
  - `contracts/classification-pipeline.md`: a new §2b `classify_v3`, byte for byte; "Which one is sent"; the
    P3 and O5 mentions; and the measured table.
  - `data-model.md`: the `prompt_version` note.
- **`specs/009-tg-m5-1-ai-attention/`:**
  - `research.md`:
    - Finding 10, the root cause (§1–§4, counts only);
    - Run 2, with v1, v2, P1, P2 and v3 on every set;
    - D-TG-172, the v3 wording;
    - D-TG-173, the D1 policy;
    - D-TG-174, the gate.
  - `spec.md`: a clarification for the 2026-10 session.
  - `contracts/attention-opening.md`: G4's "both instructions" becomes "every instruction" (wording only).
  - `quickstart.md` §2–§3: run the benchmark on v3 and the held-out files; switch both settings.
  - `tasks.md`: a new phase.
- **`docs/runbooks/tg-operator-prerequisites.md` §C:** the operator's fresh real sample for the v3 gate.
- **`CLAUDE.md`:** one line saying `classify_v3` is opt-in.
- **`docs/plan/telegram/tg-m5-classify-v3-plan.md`:** this plan.

## 9. Benchmark plan

Every run uses the real model at the same profile, reports the smoke's own lines, and is run twice to confirm
it is deterministic.

1. **The v2 baseline, recorded:** §4's tables, plus the shipped attention set, plus both moderation sets.
2. **Tuning, at most 3 rounds.**
   - Allowed sets: the two real attention sets, the real moderation set, and the shipped attention,
     moderation and policy sets.
   - Each draft is swapped in memory; nothing is written.
   - **Every round's counts are recorded, failed ones included.** Then freeze and pin the SHA-256.
3. **Held-out, written only after the freeze**, from this grid (fixed now, before v3 exists). About 50
   synthetic, sanitised cases.
   - **Topics kept apart from tuning:** certificate, grades/results, homework submission, payment receipt,
     group link, exam hall/seat, meeting app, timetable file.
   - **Dialect and form:** at least 40% Saudi and 30% Egyptian, at least 80% without `؟`, and at least 8
     near-pairs.
   - **Clear file, about 40 cases:**
     - 10 clear positives that rule set v1 *declines*, checked with `evaluate` before any model run:
       - 4 requests;
       - 4 unresolved problems;
       - 2 detail-plus-tag confirmations ("…, right").
     - 4 rule-caught sanity positives.
     - 3 mixed messages: informing plus a request or a remaining problem.
     - 1 relapse: it worked, then stopped.
     - 1 question wrapped in a social opener.
     - Negatives:
       - 8 informing with detail;
       - 5 resolved status;
       - 3 passing on an announcement;
       - 3 social comments on a past event;
       - 2 acknowledgements.
   - **AMB file, about 10 cases:** bare declaratives labelled per D1, with their detailed twins in the clear
     file.
   - Run **once**. If it fails, it is never tuned against; see §10.
4. **The real held-out (the non-circular check).** The operator labels 20–30 fresh messages from the dev or
   pilot group, kept outside Git, that nobody looked at while writing v3. I wrote both v3 and the synthetic
   held-out, so the synthetic held-out alone is partly circular.
5. **Reporting.** For each set, v2 against v3 side by side:
   - needs_response agreement, FN, FP, model-opened on expected-false and category exact, with rule / model /
     none openers by label;
   - split by CP, CN and AMB, by line list;
   - the moderation-side numbers.

## 10. Production acceptance gate (recommended)

Before `MODERATION_AI_ATTENTION_FROM` is set on any production group, with `classify_v3`:

| Gate | Requirement |
|---|---|
| G-A, clear negatives | Model-opened **0 of 20** on the tuning sets, and **≤ 1** on the held-out clear negatives (≤ 5%) |
| G-B, clear positives | 0 missed on the tuning sets. On the held-out, **≤ 1 of 10** rule-declined positives missed, and 0 rule-caught |
| G-C, AMB | Reported (how many answered true), not gated |
| G-D, advert side | No regression from v2: real 12 at 12/12 needs_moderation, FP 0. Synthetic policy at FN ≤ 1, FP 0, and **no legitimate message routed to `incident`** |
| G-E | Two runs identical |
| G-F, operator's fresh real sample | Model-opened on CN ≤ 1; rule-declined CP missed ≤ 1 |
| Pilot | One real group. Moderators dismiss daily, because an undismissed false positive expires as permanently unanswered. Weekly review of C9: **dismissed ÷ model-opened ≤ 10%** over the first ≥ 30 model-opened items. Above that, blank the switch (rollback, nothing revisited) |

If G-D fails after 3 rounds, or the pilot's C9 stays above 10%, the recommendation becomes the model (§4).

## 11. Development and production while this is evaluated

- **Development.** Keep AI Attention on: `.env` sets the switch with v2 today. It is how live behaviour is
  observed. Expect about one unnecessary item per neutral statement. Switch development's
  `MODERATION_PROMPT_VERSION` to v3 only after G-A through G-E pass, because it also changes the advert side.
- **Production.** Keep `MODERATION_AI_ATTENTION_FROM` **blank** until the full gate passes.

## 12. Risks of overfitting

- **Mirrored phrasing.** The tuning sets are about 5 templates: schedule, registration, link, book, platform.
  "Has a time or day → informing" would miss detail-bearing confirmations; the held-out includes them.
  - Fixture-shaped nouns are banned from the wording (principle 6).
- **Resolution cue learned too broadly.** The held-out includes relapse and mixed messages.
- **Circularity.** The policy (D1), the labels and the synthetic held-out share one author. The operator's
  fresh real sample (G-F) is the only independent check.
- **Prompt creep.** The length cap (principle 7) and the stop condition (§4).
- **Advert side.** It is guarded by G-D on every round, not only at the end.

## 13. Fixture labels to reconsider (operator review; I change none)

- **Paired set (`real-attention-extra`):**
  - **#19** (labelled false): AMB. Pair #7/#19 does not separate a check from a statement.
  - **#2 and #5** (labelled true): AMB under either policy.
  - **#1, #3, #4, #6, #7, #10, #11, #12** (labelled true): AMB. They are right only under policy S. #6
    "registration opened again" reads most like news.
- **Original set (`real-attention`):**
  - **#5–#13** (labelled true): AMB.
  - **#11** "lecture today is online" and **#13** "class cancelled today" carry a complete informative
    predicate. Under policy M they are false, and they are the most likely to be mislabelled under S as well.
  - Research §2 Run 1 records that this set's labels were the implementer's first draft, still pending operator
    review.
- **#18, #21 and #22** in the original set, previously called debatable, I classify as **CN**. Their failure is
  the systematic gap, not label noise.
- **Missing coverage:** both sets need rule-declined clear positives: requests and unresolved problems that use
  no rule token.

## Verification (when implemented)

1. `make check` with Ollama quit. The pin, config and model-input tests pass; the TG-M3, TG-M4 and TG-M5.1
   suites pass untouched.
2. Rebuild the tools image: `docker compose -f infra/docker-compose.yml --env-file .env --profile tools build
   migrate`.
3. Benchmark the attention side, comparing v2 and v3:
   - `FIXTURES=~/Projects/injaz-m5-fixtures/real-attention.jsonl make smoke-attention ARGS="--prompt classify_v3"`
   - the same for `real-attention-extra.jsonl`
   - `FIXTURES=apps/ai-api/app/scripts/attention_smoke_heldout_clear.jsonl …`
   - `FIXTURES=…_ambiguous.jsonl …`
4. Benchmark the advert side:
   - `FIXTURES=~/Projects/injaz-m5-fixtures/real-moderation.jsonl make smoke-moderation ARGS="--prompt classify_v3"`
   - the same for `apps/ai-api/app/scripts/moderation_smoke_policy_fixtures.jsonl`
5. Check the gate (§10). Record the counts only, never text, in `specs/009…/research.md`.
6. Live check in development: set `MODERATION_PROMPT_VERSION=classify_v3` and recreate `ai-worker` and
   `ai-classifier`.
   - Post a near-pair: the bare form should open `source='ai'` and the detailed form should not.
   - The Model's view shows `classify_v3`.
   - Rollback is the env flip.

## 14. Tuning outcome (2026-10-04): the stop condition was reached

**Operator decisions applied:** D1 = Policy S. Ambiguous cases are reported separately and never gated. No
fixture was relabelled. There is no new spec unless the evidence requires one.

Three rounds, as the plan allowed. Each draft was swapped in memory; nothing in the repo changed. Every round
was scored on all six sets with the same model and profile (`gemma4:e2b-it-qat`, temperature 0). Counts only.
CN = clear negatives the model opened; CP = clear positives no one opened; AMB = ambiguous cases answered
true. Label classes are as in §3–§4; the shipped synthetic set (SH) has 5 CP, 3 AMB and 7 CN.

| Draft | Size vs v2 | A: CN opened /9 | B: CN opened /11 | SH: CN opened /7 | CP missed /13 | AMB answered true /23 | Real moderation: needs_mod /12 | Policy set FN / FP | Legitimate → incident |
|---|---|---|---|---|---|---|---|---|---|
| v2, baseline | — | 3 | 9 | 1 | 0 | 21 | **12** | 1 / 0 | **0** |
| P2, diagnostic probe | ≈ +1,150 | **0** | **0** | (not run) | 0 | 10/20 | 11 (#1) | 0 / 1 (#21) | 1 |
| R1: separate paragraph before the categories, plus a firewall sentence | +908 | **0** | 5 | 0 | 0 | 16 | 11 (#1) | 0 / 1 (#21) | 1 |
| R2: test written into the QUESTION_* / OTHER / needs_response lines | +676 | **0** | 5 | 0 | 0 | 9 | 11 (#1) | 1 (#50) / 1 (#21) | 1 |
| R3: only the needs_response line changed | +507 | 1 | 5 | 0 | 0 | 15 | 11 (#1) | 1 / 0 (= v2) | **0** |

**No draft meets both G-A (0 of 20 clear negatives opened on the tuning sets) and G-D (advert side unchanged
from v2).**

- **The question-side fix works only through the category.** The clear false positives disappear only when
  OTHER takes in informing statements and QUESTION_* is defined by function (P2, and R1 on set A). With the
  categories left byte-identical (R3), 6 of 20 clear negatives are still opened.
- **Changing the categories moves the advert boundary.**
  - Synthetic #21, a legitimate "does anyone have the file?" question, becomes an **incident** in every
    variant that rewords QUESTION_COURSE: P2, R1 and R2.
  - In R2, synthetic #50, an advert, is missed as well.
- **Real moderation #1 regresses in every variant, including the minimal R3.**
  - It is an outside programme announcement that the group rule forbids. Any "informing needs no response"
    wording leads the model to treat it as harmless, even when the wording is scoped to "this course".
  - v2 caught it only partly: it was `SPAM_OR_AD`, not the labelled `OTHER`. The v2 plan already classed it as
    the deterministic no-link rule's territory.
- **Reading.** One prompt yields both judgements, and this 2B model cannot hold "informing is not a question"
  and "informing about outside things is forbidden" apart. Every edit that fixes one moves the other. This is
  the capacity limit §4 anticipated. The wording is not the bottleneck: P2 shows the model can learn the
  question-side distinction on its own.

**Stopped as instructed.** No `classify_v3.md` was frozen, and no code, test, spec, contract or config changed.
What happens next needs the operator's choice (§15).

## 15. Options after the stop

| Option | What it is | New spec? | Cost / risk |
|---|---|---|---|
| **A. A larger moderation model (recommended first step)** | Measure a larger local instruction model under v2, P2 and R1 on all six sets. Pulling it is a download, so it needs the operator's consent, and it registers a new moderation profile (M1 territory). | Yes, if adopted: a moderation-model change, plus v3 with it. | 16 GB M1 Pro with Docker resident: a 4B-class model at Q4 fits, larger ones likely don't. It may also improve the advert side. Latency must be measured. |
| B. A separate `needs_response` judgement | A second focused instruction and call, only for live messages the rules declined, so the advert prompt stays exactly v2. | Yes: two calls per message, and a prediction-shape or schema change (new revision; `0008` is reserved). | The cleanest separation, at the price of the largest change: pipeline contract, immutability model, metrics. |
| C. Prompt-only, with the advert regression accepted | One more round (beyond the plan's cap): P2's question-side wording with v2's QUESTION_COURSE line kept byte-identical (R3 shows that keeps #21). Real moderation #1 is accepted as lost and left to the deterministic no-link rule milestone. | No. | Breaks "preserve advert behaviour" for one real class. Lifting the 3-round cap raises the overfitting risk. Every round shows the advert boundary is fragile. |
| D. Status quo | Keep v2. AI Attention stays on in dev only and blank in production. The rules cover explicit questions. | No. | About 60% of clear informing statements open an item in dev, and nothing is gained in production. |

## 16. Option A, measured (2026-10-04): a larger model, `gemma4:e4b-it-qat`

**Setup, for measurement only.**
- Pulled `gemma4:e4b-it-qat`: 7.5B, Q4_0, 6.15 GB.
- Added one **inactive** dev profile, `ollama-gemma4-e4b-moderation` (id 17), with the e2b moderation profile's
  params (`num_ctx 2048`, `num_predict 128`, `temperature 0`, `reasoning_effort none`). The active profile, the
  prompts, the schema, TG-M5.1 and `.env` are unchanged.
- v2 and the four drafts were replayed on the same six sets through `--profile`.
- The 12B variant (7.15 GB) was not tried, because Docker holds 7.8 GiB of the 16 GB.

Pooled over sets A, B and SH, with label classes as in §3–§4: 27 CN, 13 CP, 23 AMB.

| Model | Prompt | CN opened /27 | CP missed /13 | AMB answered true /23 | Real moderation /12 | Policy set (64): FN / FP · legitimate → incident | Shipped moderation set /12 |
|---|---|---|---|---|---|---|---|
| e2b | v2 | 13 | 0 | 21 | **12** | 1 / 0 · 0 | 12 |
| e2b | P2 | **0** | 0 | 11 | 11 (#1) | 0 / 1 · **1** | 12 |
| e2b | R3 | 6 | 0 | 15 | 11 (#1) | 1 / 0 · 0 | 12 |
| e4b | v2 | 9 | 0 | 21 | **12** | 0 / 1 · **1** | 10 (#11 missed, #12 → incident) |
| **e4b** | **P2** | **0** | **0** | **15** | 11 (#1) | **0 / 0 · 0 (64/64)** | 11 (#11) |
| e4b | R1 | 1 | 0 | 11 | 11 (#1) | 0 / 0 · 0 | 11 (#11) |
| e4b | R2 | 2 | 0 | 15 | 11 (#1) | 0 / 3 · 3 | 10 |
| e4b | R3 | 3 | 0 | 16 | 11 (#1) | 0 / 2 · 2 | 11 (#11) |

**Repeat run:** e4b with P2, run twice, gives identical lines on all six sets.

**Latency** (median / p90): e4b with P2 takes 1.36 s / 1.46 s, against 0.85 s / 0.97 s for e2b with v2.

**Memory:** with e4b loaded, macOS swap rose from 6.6 GB to 10.3 GB on this 16 GB machine.

**Reading.**
- **Attention side: e4b with P2 passes.** It opens 0 of 27 clear negatives, misses 0 clear positives, and
  answers more AMB true than e2b with P2 (15 against 11; on sets A+B, 13/20 against 10/20).
- **Policy advert set: better than v2 on e2b.** 64/64, and no legitimate message becomes an incident. The
  e2b-specific flips (#21, #50) are gone.
- **Two advert-side cases still fail G-D, and neither is a random flip:**
  - **Real moderation #1**, an outside programme announcement, is lost under every informing-aware prompt on
    **both** models. Its conflict is structural ("informing" against "promoting from outside"). v2 caught it
    only as `SPAM_OR_AD`, not the labelled `OTHER`, and the v2 plan assigned it to the deterministic no-link
    rule.
  - **Shipped synthetic #11**, an insulting accusation of fraud labelled ABUSE, comes back COMPLAINT/false
    under **every** e4b prompt, including v2. This is e4b's reading of the ABUSE/COMPLAINT boundary, not
    something P2 causes. The real attention set labels a similar message (#15) COMPLAINT, so this label needs
    operator review.
- **Verdict:** the larger model satisfies the attention side and the synthetic advert side. As written, it does
  **not** satisfy G-D, because of those two boundary cases. Whether that is acceptable is the operator's call.
- **If adopted:**
  - **New spec:** a moderation-model change, carrying a v3 frozen from P2.
  - **Wording:** P2 needs principle 6's de-listing of fixture-shaped nouns and is about 120 characters over
    the length cap (+1,118 characters; an earlier count used bytes). Any new wording must be re-measured.
  - **Gate before production:** the held-out set (§9) and the operator's fresh real sample (G-F).
  - **Machine headroom:** swap pressure is a real operating risk.
