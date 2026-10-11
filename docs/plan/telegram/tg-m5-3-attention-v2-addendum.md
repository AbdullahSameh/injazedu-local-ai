# TG-M5.3 addendum: Policy D′ and `attention_v2`

**Status:** drafted 2026-10-08. **Approved by the operator on 2026-10-09, with every recommended option** (§10
items 1–6 as recommended). It is implemented from T083 (tasks.md, Phase 9b). No model run comes before T090.
**Outcome (2026-10-09): stopped under W-7′.** No V2 candidate passed W-3′, nor V2-AR after the one revision.
`attention_v2` was not created, and opening stays rules-only. The evidence is in
`specs/011-tg-m5-3-attention-judgement/research.md` §2.

**Decided by the operator so far (2026-10-08):**
- **Option (a).** General guidance about outside institutions is not the moderation team's responsibility.
  This covers universities, Qiyas and other national testing bodies, licensing bodies, ministries, government
  portals and the like. Such questions create no moderator-response obligation unless they are specifically
  about the course's own service.
- **The Policy D′ direction is approved.** The exact wording is §3 below, still for approval.
- **What is not changing:**
  - `attention_v1` stays frozen, pinned and allowlisted, as history.
  - `MODERATION_AI_ATTENTION_FROM` stays blank.
  - The T071–T077 evidence is kept as recorded. It is evidence under Policy D (2026-10-07).

**What it amends:**
- `tg-m5-3-attention-judgement-plan.md` §5a, §8.3, §8.4 and §9;
- `specs/011-tg-m5-3-attention-judgement/` (§8 lists each file).

**What it supersedes:** nothing. Every amended passage keeps its earlier text, with a dated note.

---

## 1. Why

The operator reviewed the real fresh sample (T077) and found a problem with Policy D:
- D2, D5 and D7 make **peer questions and problem reports about outside institutions** `asking`. Examples are
  admissions, national-exam registration, appointments and results, licence eligibility, and outside sites that
  hang.
- Operationally, none of these needs the team.

The fault is in the policy, not the model: `attention_v1` did what Policy D told it to. The business meaning of
`asking` is therefore narrowed to **the team's responsibility**. A message is `asking` only when the team is
expected to give the useful answer. A question mark, a described problem, an education topic, or an address to
the group ("does anyone know?") is not enough on its own.

## 2. What this can and cannot fix

**Most of these messages never reach the attention model.** Rule set v1 opens them first: a question mark, or
a trap token such as `من`, `هل` or `مشكله`. Under AE2 they are excluded before any call, and TG-M3 opens them
as rule items.
- **The operator's eight examples:** 7 open by rule. Only fresh #9 (30-line numbering) is rule-declined.
- **The fresh sample as a whole:** 21 of the 30 lines open by rule, and 27 of the 37.

So Policy D′ and `attention_v2` change two things:
- the labels;
- the model's answer on **rule-declined** messages: bare statements, complaints, and questions with no rule
  signal.

They **cannot** stop a rule-opened item about an outside institution. Those stay what TG-M5.3 already makes
them:
- **In the panel:** a "Member discussion" dismissal (§13a). The dismissal-reason wording, "a real question or
  discussion between members; no moderator was needed", already covers them, so K1–K12 need no change.
- **In the figures:** C7 and C9's `member_discussion` counts.
- **Later:** the evidence for any future change to rule set v1. That is TG-M3 territory and a separate
  milestone, not part of this addendum.

## 3. Policy D′ (exact text, for approval)

D0 is new. D1, D2, D3, D5 and D7 are amended. D4, D6 and D8 are unchanged.

| # | Case | Label |
|---|---|---|
| **D0** *(new)* | **The team's responsibility.** The team answers for the course's own service and for course content. The course's own service is its schedule and sessions, its tests and their arrangements, access, links, the platform, materials, recordings, registration and payment with the course, its certificates, and the group's rules. An outside institution's service or process is not the team's: a university, a national testing or licensing body, a ministry or another government portal. This holds even for the exams the course prepares students for. Their registration, appointments, results and licences belong to the outside body; what they test is course content. | — |
| **D1** *(amended)* | **The expected answerer decides, not the addressee or the form.** A message is `asking` only when the team is reasonably expected to give the useful answer, action, clarification or authoritative guidance. A question, a described problem, an education topic, or an address to the group ("does anyone know?") does not by itself make a message `asking`. | — |
| **D2** *(narrowed)* | A peer-addressed question about the course's own service (D0) | `asking` |
| **D3** *(widened)* | A question between members whose useful answer comes from the members' own experience, work, answers or opinions, **or from what members know of an outside institution**, including help with an outside institution's site or system | `discussion` |
| D4 | A member answering another member | `informing` |
| **D5** *(narrowed)* | A peer-addressed problem check **about the course's own service** | `asking` |
| D6 | A course-content question with no addressee | `asking`, `label_class: ambiguous` |
| **D7** *(amended)* | When it is unclear whether the team is needed, **including whether the subject is the course's own service or an outside institution's**, choose `asking` | `asking` |
| D8 | Reply context is not visible to the model | D7 applies; a stated limitation |

**Two dependent sentences change with it.** They are part of the policy, and every candidate carries them
verbatim:
- **The `asking` and `discussion` definitions** (contract §4 S3; `attention_v1.md` lines 6–7):
  - `asking`: "…a question or request about **the course's own** service, a problem the writer still has **with
    it**, or a member's bare statement of a course arrangement."
  - `discussion`: "a genuine question or prompt between members, about their own experience, work, answers or
    opinions, **or about an outside institution**, that needs no moderator."
- **Policy S's scope.** A bare statement is a request for confirmation only when it is about **the course's
  own** arrangement. A bare statement or complaint about an outside institution is `informing`.

**Why D7 still leans to `asking`.** If a message does not say whose registration, test or results it means, the
course's own service is still possible. A missed own-service question costs a member left unanswered, while a
wrong opening costs one dismissal. The D′ direction removes obligations only where an outside institution is
named or plain.

**D1's illustrations** (2026-10-07) still hold. «يا شباب التسجيل فتح؟» → `asking` under D7, since it does not
say whose registration. **Two illustrations are added**, synthetic, each with `؟` so that rule set v1 opens it
first:
- «يا شباب نتائج الجامعة طلعت؟» → `discussion`: an outside institution.
- «يا شباب نتائج الاختبار التجريبي طلعت؟» → `asking`: the course's own test.

## 4. Impact on existing evidence and fixtures

| Set | Role now | Under D′ | Role in the v2 cycle |
|---|---|---|---|
| `real-attention.jsonl` (24), `real-attention-extra.jsonl` (24) | tuning | **No change found.** Every line concerns the course's own lectures, recordings, links, books, registration, the platform or refunds. The operator confirms. | tuning, unchanged |
| `attention_smoke_fixtures.jsonl` (15) | tuning | no change | tuning, unchanged |
| `attention_validation_fixtures.jsonl` (42) | validation | **No label changes.** Its peer positives (#35–#40) concern the course's own app, attendance, mock test, advisor and stream: still D2/D5. **It has no outside-institution line, so it cannot test D′.** | validation, byte-identical |
| `attention_heldout_fixtures.jsonl` (55) | held-out | **No label changes:** all of it is the course's own service. **But it has been seen:** `attention_v1`'s run on it is recorded, and the implementer wrote it. It cannot be v2's held-out set. | renamed `attention_heldout_v1_fixtures.jsonl`, **byte-identical** (SHA-256 pinned in a test), run as a **validation** set |
| Fresh sample: 37 lines run at T077, now in `backup/`; 30 lines active | fresh | **Labels change.** Seen by every model run. | relabelled under D′ and moved to **tuning** as `real-attention-fresh-v1.jsonl`. The existing `real-attention*.jsonl` file pattern loads it, with no code. The 30-line `fresh-attention.jsonl` leaves the fixtures directory. **Never a fresh sample again.** |
| `attention_burst_fixtures.jsonl` (8) | burst (reported) | no change: every burst is about the course's own test link, registration or study | burst, unchanged |
| `real-moderation.jsonl`, `moderation_smoke*_fixtures.jsonl` | moderation; A6 | no change: these are `needs_moderation` labels, which D′ does not touch | unchanged |

**Fresh lines whose labels change** (30-line numbering; the operator labels):
- **The operator's eight:** #2, #3, #9, #10, #14, #21, #28, #30.
- **The same rule, not in the operator's list:**
  - #1, #5, #8, #20 and #29: outside programmes, outside registration, studying abroad;
  - #6, #15, #16 and #19: outside-exam process guidance, under option (a);
  - probably #11: peers asked for exam question collections.
- **Unchanged:**
  - #12 stays `asking`: the course platform's own certificate;
  - #23 stays D6: the content of the exam the course prepares for;
  - #18 and #25 stay `discussion`.

The 7 lines cut from the active file (in `backup/`) need the same review. Of every line above, only #9 is
rule-declined, so the relabelling barely moves the gates. **The boundary must be tested with synthetic lines
that the rules decline** (§6.2, §6.6).

**What stays valid of `attention_v1`'s evidence:**
- the T071–T077 records and the held-out run's A4 PASS;
- the T077 `QUALIFIED` verdict on the 37-line sample.

All of it is valid **under Policy D, 2026-10-07**. Under D′, `attention_v1` is not qualified, so R1 bars it from
opening. Its shadow judgements, if any are recorded, stay `prompt_version = 'attention_v1'` and are never
rewritten.

## 5. Is `attention_v2` required? Yes

- **Policy D binds every wording verbatim** (contract §5; plan §8.3).
- **`attention_v1.md` states the old rules:** D2, D5 and D7 at lines 19, 22 and 24, the unscoped "a problem the
  writer still has" at lines 6 and 14, and Policy S unscoped at line 14.
- **So it no longer matches the policy,** and editing it is forbidden (P3, N5).

A new wording is a new file, a new version, a new allowlist entry and a new pin:
`ATTENTION_PROMPT_VERSIONS = ("attention_v1", "attention_v2")`.

## 6. The v2 qualification cycle

The integrity rules of 011's §8 apply unchanged:
- the candidates are fixed and hashed before any run;
- one selection round, and at most one revision;
- the held-out set is written only after the freeze, and run once;
- a fresh sample no run has seen;
- a stop condition.

### 6.1 Sets and roles

| Set | Role | Gate |
|---|---|---|
| `real-attention.jsonl`, `real-attention-extra.jsonl`, `real-attention-fresh-v1.jsonl`, `attention_smoke_fixtures.jsonl` | tuning | A1 = 0, A2 = 0 |
| `attention_validation_fixtures.jsonl` (42), `attention_validation_scope_fixtures.jsonl` (new, §6.2), `attention_heldout_v1_fixtures.jsonl` (55) | validation | A3 ≤ 1 / ≤ 1 **per set** (decision 4) |
| `attention_heldout_fixtures.jsonl` (new, written after the v2 freeze, §6.6) | held-out | A4 ≤ 1 / ≤ 1, with at least 10 rule-declined clear positives |
| `fresh-attention.jsonl` (new, §6.7) | fresh | A5 ≤ 1 / ≤ 1 |
| burst; the A6 source | as now | as now |

A6–A9, the reported lines and the verdicts are unchanged. R-discussion ("label `discussion` answered `asking`")
is the new boundary's own reported line.

### 6.2 The new validation lines (written before any v2 candidate)

`attention_validation_scope_fixtures.jsonl`, about 18 synthetic lines:
- **Shape:** every line is rule-declined (`evaluate` false), carries `intent`, and uses Saudi and Egyptian
  phrasing.
- **Topics:**
  - outside institutions that no tuning set names: Jadarah (جدارة), scholarships (ابتعاث), university placement
    (تنسيق) and unified admission (القبول الموحد);
  - the course's own topics already in validation.
- **Forbidden:** any v2 held-out topic word (§6.6).

| Lines | Label |
|---|---|
| ≥ 6 outside-institution questions and complaints: peer and unaddressed questions, and complaints about an outside site | clear `discussion` or `informing` |
| ≥ 4 own-service lines with the **same surface words** (registration, results, appointment, a site that will not open, all of the course), ≥ 2 of them peer-addressed (D2, D5) | clear `asking` |
| ≥ 2 D7 lines: unclear whether the course's or an outside body's | `asking`, ambiguous (reported) |
| ≥ 1 line on the content of the exam the course prepares for (D0's last clause, D6) | `asking`, ambiguous (reported) |

### 6.3 The candidates (W-1, v2)

**Every candidate is `attention_v1.md` with the policy-bound sentences replaced by §3's,** verbatim. Everything
else stays byte-identical, including W2R's Informing nouns: the intents, the injection guard and the output line.
The three candidates differ only in **where the responsibility rule (D0) sits**:

| Candidate | Content |
|---|---|
| **V2-A, in place** | The "Questions between members" list becomes D0–D7, in order. Nothing moves. The smallest change from `attention_v1` |
| **V2-B, scope first** | V2-A, with D0 moved to directly after "The question: …", so that it frames the whole judgement |
| **V2-C, scope first, with a contrast** | V2-B, plus one generic sentence: "The same kind of question can be either: what decides is whose service it is." No nouns and no institution names |

- The three files are written to the fixtures directory, and their SHA-256s are recorded in research §2 **before
  any run**.
- No candidate names Qiyas, a university, a licence, or any institution in §6.2 or §6.6. D0's category words
  ("a university, a national testing or licensing body, a ministry or another government portal") are policy
  text and appear in all three.

### 6.4 Matrix, decision, revision, stop (W-2 to W-4, W-7)

- **The matrix:** {V2-A, V2-B, V2-C} × {e2b, e4b}, six runs in candidate mode (`--repeat 2`; the held-out and
  fresh sets are withheld).
- **The decision rule, written now:**
  - take the smallest model with any candidate passing A1, A2, A3 (every validation set), A6, A7 and A9;
  - among those, prefer **V2-A > V2-B > V2-C**, fewest changes first.
- **The revision:** at most one, limited to the failing sentence of the best candidate. A policy sentence (§3)
  is never revised; only placement and the V2-C sentence may be.
- **The stop condition:** if nothing passes after the revision, the v2 cycle stops and is reported.
  - `attention_v1` stays frozen and unqualified under D′, so AI opening stays off.
  - The opener keeps rule set v1 only, and shadow remains possible for measurement.

### 6.5 The freeze

The chosen text becomes `apps/ai-api/app/prompts/moderation/attention_v2.md`. In one change:
- its SHA-256 goes into `_PINNED_ATTENTION_SHA256`;
- `ATTENTION_PROMPT_VERSIONS` becomes `("attention_v1", "attention_v2")`.

`attention_v1.md`, its pin and its entry stay exactly as they are.

### 6.6 The held-out set, v2 (written only after the freeze)

The topics are fixed **now**, before any v2 candidate exists. Each was checked absent from every current set,
`attention_v1.md` and the 37-line sample:
- **Outside institutions:** embassy or visa (سفارة، تأشيرة), degree equivalency (معادلة), the labour office (مكتب
  العمل), civil service (الخدمة المدنية).
- **The course's own service:** subscription (اشتراك), discount code (كود), question bank (بنك الأسئلة),
  simulated test (الاختبار المحاكي).

What it holds:
- **Positives:** at least 10 rule-declined clear positives on the own-service topics, at least 2 of them
  peer-addressed (D2, D5).
- **Outside-institution negatives:** at least 8 rule-declined clear negatives, at least 4 of them `discussion`
  and at least 2 `informing` complaints.
- **Peer discussion:** at least 3 negatives about members' own experience (D3).
- **Like v1's grid:**
  - own-service `informing` and `social` negatives;
  - D7 and Policy S lines, ambiguous and reported.
- **Question marks:** on at most 20% of lines.
- **Rule:** it is never edited after its one run.

### 6.7 The fresh sample, v2

`fresh-attention.jsonl`: 20–30 real messages.
- **None may be in the 37-line sample.** This is checked by normalised-text overlap, counts only.
- **Labels:** under D′, before any run.
- **Content:** real outside-institution questions and own-service questions, as the groups provide them. Most
  outside-institution questions will open by rule, which is expected.

### 6.8 The moderation suite

Run once more at the end, compared with T002 (SC-305). Nothing in this addendum touches it.

## 7. Schema and code

- **No change to:**
  - the schema, migration, PHP or panel;
  - the domain module, dispatch, `judge_one`, `open_item` or V.
- **What stays the same:**
  - the six intents and `needs_response_for`;
  - AE1–AE2;
  - the record, and its immutability.
- **The panel's figures already keep v1 and v2 apart:** C9′ and C10b split by `prompt_version`.
- **Small code changes:**
  - `qualification/attention.py`:
    - `discover_attention_sets` gains the two new validation files;
    - A3 is judged per validation set, and its gate line lists each set's counts (decision 4).
  - `test_attention_fixture_files.py`:
    - the v1 held-out set's SHA-256 is pinned;
    - the scope file's minimums (§6.2);
    - the v2 held-out set's topics and minimums (§6.6), checked on every validation and tuning file shipped in
      the repo;
    - the peer rule check runs over every validation file.
  - The set-discovery and A3 tests in the qualification test suite.
  - At the freeze: the allowlist, the pin, and the allowlist tests (`test_config_attention.py`,
    `test_qualification_fixtures.py`).

## 8. Documents to amend (dated, earlier text kept)

- **spec.md:**
  - a Clarifications session for 2026-10-08: option (a), D′, and the fresh sample's history;
  - FR-310 (D′);
  - FR-331 and FR-333 (the v2 sets and topics);
  - the Status line.
- **contracts/attention-judgement.md:**
  - §4 S3: the `asking` and `discussion` rows;
  - §5: D′, with the D0 row and two illustrations;
  - P3: the allowlist note.
- **contracts/qualification.md:**
  - §2: the set table;
  - §5: A3 per validation set;
  - §8: a "second cycle" note for W-1 to W-7, with the V2 candidates and the decision rule.
- **The plan of record:** §5a, §8.3, §8.4 and §9, each with a dated note pointing here.
- **The rest:**
  - research.md: a new decision (D-TG-200: Policy D′ and the v2 cycle);
  - data-model §8: the fixture files;
  - quickstart §5–§6: qualify `attention_v2`;
  - tasks.md: the tasks in §9;
  - plan.md Progress and `CLAUDE.md`.

## 9. Tasks (to be added to tasks.md as Phase 9b, after approval)

**Policy and fixtures:**
- **T083** *(agent)* Record D′ and this addendum in the documents of §8. No code.
- **T084** *(operator)*
  - Relabel the 37-line sample under D′ (`intent`, `needs_response`, `label_class`, `peer`), and save it as
    `real-attention-fresh-v1.jsonl` in the fixtures directory.
  - Move the 30-line `fresh-attention.jsonl` out of that directory.
  - Confirm that the two real tuning sets need no D′ change.
- **T085** *(agent)* Validate T084 by counts only: keys, `intent` ⇔ `needs_response`, and rule-declined counts.
- **T086** *(agent)*
  - Rename the held-out set, byte-identical, and pin its SHA-256.
  - Make the two set-discovery entries and A3 per validation set, with their tests.
- **T087** *(agent)* Write `attention_validation_scope_fixtures.jsonl` (§6.2), before any candidate, and the
  fixture-file tests of §7.
- **T088** *(agent)* Run the full check suite with no model (SC-310).

**Selection and freeze:**
- **T089** *(agent)* W-1: the three V2 candidates, with their hashes recorded in research §2 before any run.
- **T090** *(agent, Ollama)* W-2: the six runs, recording counts only.
- **T091** *(agent)* W-3, then W-4 if needed, or W-7.
- **T092** *(agent)* Freeze `attention_v2` (§6.5), then run the pin and config tests.

**Held-out and fresh:**
- **T093** *(agent)* After T092 only: write the v2 held-out set (§6.6) and its minimums test.
- **T094** *(agent, Ollama)* Run it once with `PROMPT=attention_v2`. `INCOMPLETE` is expected until the fresh
  sample exists.
- **T095** *(operator)*
  - Write the new `fresh-attention.jsonl` (§6.7), then re-run for `QUALIFIED`.
  - Run the moderation suite and compare it with T002 (SC-305).

Shadow then follows quickstart §6 with `MODERATION_ATTENTION_PROMPT_VERSION=attention_v2`.

## 10. Decisions for the operator (approved 2026-10-09, each as recommended)

1. **Approve D′'s exact text (§3):** D0, D1, D2, D3, D5 and D7, the two dependent sentences, D7's lean to
   `asking`, and the two added illustrations.
2. **The used fresh sample (§4).** Recommended: relabel all 37 lines and use them as tuning
   (`real-attention-fresh-v1.jsonl`). The alternative is to keep them out of every set.
3. **The v1 held-out set (§4).** Recommended: keep it byte-identical as a validation set, so that it shows
   whether D′ broke own-service questions. The alternative is to keep it as history only, never run.
4. **How A3 is judged (§6.1).** Recommended: per validation set, ≤ 1 / ≤ 1 each. This keeps each set at the bar
   it was designed for. The alternative, pooling all three sets (about 115 lines) under one ≤ 1 / ≤ 1, needs no
   code change, but `attention_v1`'s own miss (validation #4) would use the whole miss budget.
5. **The candidate design and preference order (§6.3–§6.4):** V2-A > V2-B > V2-C.
6. **The topics (§6.2, §6.6),** fixed now.

## 11. Risks

| Risk | Control |
|---|---|
| D′ makes the model drop own-service questions that mention an outside word | Own-service lines sharing surface words in validation (§6.2) and held-out (§6.6); D7's lean; the v1 held-out set kept as a regression set |
| Overfitting to the operator's eight examples | Category words, not names; validation and held-out use institutions no tuning line names; the used fresh sample is tuning only; the held-out topics are fixed before candidates |
| The real tuning lines raise A1 | T077's A5 opened one rule-declined clear negative of the 37. If that label stands under D′, A1 = 0 now requires v2 to get it right |
| Small benefit in volume, because most outside-institution questions open by rule | Stated in §2; the `member_discussion` figures measure them as the evidence for any future rule change |
| e2b fails again, as in the v1 cycle | The decision rule takes the smallest **passing** model; e4b's model swap on the 16 GB Mac is deployment policy |
