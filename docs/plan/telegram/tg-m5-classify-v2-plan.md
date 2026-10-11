# TG-M5 follow-up: classify_v2 (opt-in) and a needs_moderation benchmark

**Status:** implemented 2026-10-02 — see `specs/008-tg-m5-ai-classification/tasks.md` Phase 11 and research §6.

## Context

On real moderator-deleted messages, TG-M5 misses violations. The model returns `needs_moderation=false` at
confidence 0.90–1.00: 3/12 in the operator's real benchmark, plus the live Al-Faheem incident. The goal is
fewer false negatives without changing any approved TG-M5 behaviour (thresholds, routing, eligibility,
question ownership, gateway, redaction boundary, immutability, catch-up). `classify_v1.md` stays
byte-identical. The smoke tool also needs to report category, needs_moderation, FN and FP separately,
because "n/total matched" is not enough to decide.

**Decided by the operator (2026-10-01):** v2 goes in as an **opt-in setting**, default `classify_v1`. The
wording is **v2D (conservative)**.

## 1. Root cause: measured, not guessed

I reproduced the failures with the real provider against local Ollama, using the same profile params. The
input went through `normalize` → `redact` exactly as in P1–P2, and v1 was byte-for-byte. The probe gave the
same 9/12 and the same three failures, at the same confidences. The model also behaved deterministically
across repeated rounds.

| # | What the model sees (redacted) | v1 output | Why v1 allows it (prompt evidence) | Type |
|---|---|---|---|---|
| 1 | Ministry programme details, `«بريد»`, bare `moe.gov.sa` | OTHER/false 0.95 | v1 states no group rule. `needs_moderation` is defined only as "a moderator should act against the message itself (SPAM_OR_AD and ABUSE usually do)". Informational content with no offer is legitimately OTHER/false under v1. The redactor misses bare domains, so the model never sees `«رابط»`. | **Deterministic policy gap** (no-link rule) |
| 3 | `🩺✅️عذر طبي \| اجازه مرضيه✅️ نطلع عدر … وتساب📱: «رقم»` | CHITCHAT/false 0.95 | v1's CHITCHAT is defined by surface features: "greetings, thanks, **emoji**, social talk". SPAM_OR_AD names "service" only generically. Nothing says a "contact on WhatsApp" call to action is an offer. Obfuscation is not the cause: NFKC, the Cf-strip and tashkeel removal already undo the presentation forms, the ZWNJ and the sukun. | **Prompt gap** |
| 12 | `اعذار طبيه «رقم»: … نطلع … من مستشفي … تنزل بتطبيق صحتي رسمي … وتساب «رقم»` | OTHER/false 0.90 | #10 comes from the same advertiser and opens the same way, but it says **يتوفر** ("available"). It passes. #12 describes the service without any sale verb. v1 never says that an offer needs no price or "sale" word. | **Prompt gap**, plus a model limitation (a 2B model leans on lexical sale cues) |
| live | `اهلا بك … نورت … معهد … التسجيل بدوراتنا … المنسقات «رابط»` | CHITCHAT/false **1.0** | The message opens with a greeting, and v1 puts "greetings" under CHITCHAT. v1 never says to judge the message's purpose over its opener. | **Prompt gap** |

**The pattern.** v1 catches promotions that carry an explicit commerce word (للبيع, يتوفر, سعر, قروب + join).
It misses two kinds of promotion: those wrapped in a greeting or emoji, and those phrased as a service with
a private-contact call to action. The held-out set repeated this: v1's two misses there were a survey
ending 🙏 and "صباح الخير 🌸 … قروبنا" (both → CHITCHAT).

- **Not message length.** Ads of 1,698 and 604 characters pass; the failing ones are 102 and 144 characters.
- **Not the taxonomy.** All 13 examples are expressible, and OTHER + true is consistent under R8.
- **Not the pipeline.** Ingestion, normalisation, redaction, routing and first-posted text all behave as
  designed.
- **Model limitation, secondary.** The same model under v2 gets 13/13 on the real set. Small wording changes
  still flip borderline cases, though: the v2 variants B, C and E each fixed one case and broke another. The
  "request vs offer" distinction stays fragile. Confidence was 0.80–1.00 on wrong answers in every variant,
  so confidence cannot be the fix.

## 2. Benchmark (v1 vs chosen v2D, same model and params; needs_moderation is the primary metric)

| Set | n | v1 cat | v1 mod | v1 FN | v1 FP | v2D cat | v2D mod | v2D FN | v2D FP |
|---|---|---|---|---|---|---|---|---|---|
| Operator's real 12 | 12 | 10 | 9 | 3 | 0 | 11 | **12** | **0** | 0 |
| + Al-Faheem live | 1 | 0 | 0 | 1 | 0 | 1 | 1 | 0 | 0 |
| Shipped synthetic | 12 | 10 | 12 | 0 | 0 | 11 | 12 | 0 | 0 |
| Synthetic policy | 20 | 15 | 17 | 3 | 0 | 18 | 19 | 1 | 0 |
| Hard near-misses | 20 | 18 | 18 | 2 | 0 | 18 | 20 | 0 | 0 |
| Held-out (written after freezing) | 24 | 20 | 22 | 2 | 0 | 23 | 24 | 0 | 0 |
| **Total** | 89 | | | **11** | 0 | | | **1** | **0** |

- **Routes under v2D.** Every caught violation routes to `incident`. One legitimate message ("how do I get a
  sick note from Sehhaty?") came back SPAM/false: it is inconsistent, so it is *listed*, not opened.
- **v2D's one miss** is a terse synthetic survey. The real survey (#5) and the held-out survey both pass.
- **Cost.** About +250 prompt tokens, with no latency cost (median ≈0.85 s).
- **Caveat.** I wrote the synthetic sets myself and n is small. The pilot false-positive rate of model-opened
  incidents remains the gate (operator item 3).

## 3. The no-link rule: surfaced, not implemented

- **What happens now:** there is no link rule anywhere.
  - TG-M2 stores `telegram_messages.entity_flags.has_url` (Telegram `url`/`text_link` entities) and the
    incident page shows it.
  - The model sees `«رابط»` only for links with a scheme or `www.`.
  - `@handles` become `«مستخدم»`; Telegram types them as mentions, not URLs.
  - Moderators' messages (E5), the group itself (E6) and the linked channel (E7) never reach classification.
- **What would change:** an eligible student message with `has_url` would open an incident with
  `source='rule'` and a `rule_version`. That needs all of the following:
  - **TG-M4 schema and contract.** `ck_incident_source` is `('operator','ai')` today. The plan of record
    §10.8 anticipated `'rule'`.
  - **A new Alembic revision.** 0007 is consumed and 0008/0009 are reserved, so the plan needs renumbering.
  - **Metrics.** Rule-opened incidents must be kept out of the model's C3 false-positive figures.
  - **Panel.** A source label for rule-opened incidents.
- **Policy questions for you:**
  - Do @mentions, emails and phone numbers count as links?
  - Do forwarded posts count?
  - Do captions on media count? E3 excludes media from the model today, and many real ads are image plus
    caption.
  - Who counts as an admin? Telegram admins who are not declared moderators are not known to TG-M2.
- **Where it belongs:** its own small milestone before TG-M6, so that alerts cover it. **No TG-M5 contract
  change is needed:** A3 and R12 already let whichever incident exists first win.

## 4. Implementation (fits TG-M5; documentation amendments listed in §5)

1. **New file: `apps/ai-api/app/prompts/moderation/classify_v2.md`** (text below). v1 is untouched.
2. **`apps/ai-api/app/infrastructure/config.py`:** add `moderation_prompt_version: Literal["classify_v1","classify_v2"]`.
   - Alias `MODERATION_PROMPT_VERSION`, default `"classify_v1"`.
   - Add the field to `_empty_classification_setting_is_default`, so blank means the default.
   - An unknown value is refused at startup.
3. **`apps/ai-api/app/application/moderation/classification.py`:**
   - Replace `_PROMPT_VERSION`/`_INSTRUCTION` with an `_INSTRUCTIONS` map loaded at import for each allowed
     version.
   - `build_model_input(text, *, prompt_version)` keeps the same two messages; the variable stays
     `redacted_text` (check 4).
   - `classify_one` passes `settings.moderation_prompt_version` both to `build_model_input` and to
     `_insert_prediction(prompt_version=…)`.
   - Catch-up (`classify_chat.py`) inherits the setting through `classify_one`. Nothing else changes: no
     routing, eligibility, threshold or transaction change.
4. **`apps/ai-api/app/scripts/smoke_moderation.py`** (an additive change to C4; it still writes nothing and
   prints no text):
   - Add `--prompt {classify_v1,classify_v2}`, defaulting to the configured version, and print a header with
     the prompt and the profile.
   - Each output line gains the fixture line number and the **route**, computed by calling the domain's
     `route_prediction` with the configured floor and threshold and `path="live"` (N7: call it, never
     re-derive it).
   - The summary keeps the existing `n/total matched` line and exit code, and adds:
     - category exact;
     - needs_moderation agreed;
     - false negatives and false positives, with their line numbers;
     - a route tally for violations and for legitimate messages.
   - The scoring lives in a small pure function so it can be unit-tested.
5. **New file: `apps/ai-api/app/scripts/moderation_smoke_policy_fixtures.jsonl`.** It holds the 64 synthetic
   cases from §2: synthetic policy, hard near-misses and held-out. They use fake numbers and handles and
   `example.com` domains, and include **no real student text**. The default shipped set stays unchanged for
   comparability with research probe 4.
6. **`.env.example`:** add `MODERATION_PROMPT_VERSION=classify_v1`, with a comment saying to smoke first and
   that a switch revisits nothing.
7. **Not touched:**
   - `classify_v1.md`, thresholds, `route_prediction`/`eligibility`, migrations, PHP (the panel already
     splits by `prompt_version` under K3 and shows it on Possible Violations and the incident page), the
     gateway and profiles;
   - the uncommitted worker and connection-leak files currently in `git status`.

### classify_v2.md (v2D, as measured)
```text
You classify ONE message posted in a student group of an online exam-preparation course. Students write in Arabic (Modern Standard, Saudi or Egyptian dialect), English, or a mix. The text has been normalised (for example ة is written ه and أ is written ا). Personal details were replaced before you see the message: «رابط» is a link, «رقم» is a phone number or long number, «بريد» is an email address, «مستخدم» is a username.

The group's rule: it is only for this course. Members may not advertise, sell or promote anything from outside it, paid or free, and may not ask others to contact them or anyone else outside the group to get something.

Judge what the whole message is for, not how it opens: a greeting, a welcome, emoji or a prayer around an offer does not make it chitchat.

Choose exactly one category:
- QUESTION_COURSE: a question about the course itself — lecture times, links, content, materials, exams.
- QUESTION_ACCESS: a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.
- COMPLAINT: dissatisfaction or criticism of the course, the service or the team.
- CHITCHAT: a message that is only social — greetings, thanks, congratulations, prayers, emoji — with nothing offered or promoted.
- SPAM_OR_AD: offering, selling or promoting anything from outside the course, with or without a price, a link or the word sale: other courses, classes or tutors; files, summaries, collections, designs or other study material; services of any kind, including medical excuses, sick notes, sick leave and reports; another group or channel on Telegram, WhatsApp or elsewhere; surveys or outside projects asking for participation; investment, trading, income or money offers; or asking readers to contact someone privately, on WhatsApp, at «رقم», «مستخدم» or «رابط» to get something. A question asking whether anyone has a file or summary is a question, not SPAM_OR_AD.
- ABUSE: insults, harassment, threats or inappropriate content.
- OTHER: none of the above.

Then decide:
- needs_response: true only if the writer asks a question or reports a problem that a moderator should answer. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.
- needs_moderation: true if a moderator should act against the message itself — always for SPAM_OR_AD and ABUSE, and for any other message that breaks the group's rule. False for an ordinary question, complaint, greeting or comment.
- severity: none, low, medium or high — how much harm or urgency the message carries.
- confidence: a number from 0.0 to 1.0 for how sure you are of the category.

Answer with the JSON object only.
```
The schema, the seven categories and the output format are unchanged, so `taxonomy_version` stays 1. The
wording describes concepts and quotes none of the benchmark strings.

## 5. Spec and contract amendments (documentation; anticipated by D-TG-136, FR-009 and K3)

- **`contracts/classification-pipeline.md`:**
  - §2 gains "§2a classify_v2", byte for byte, plus the selection rule: the setting, default v1, allowlist
    = the pinned files.
  - P3: `system` = the configured instruction.
  - O5: `prompt_version` = the configured stem.
  - C4: `--prompt` and the summary block.
- **`data-model.md`:** the `prompt_version` note now reads "`classify_v1` or `classify_v2`".
- **`research.md`:**
  - Finding 7: the prompt policy gap, with the table in §1.
  - Finding 8: `num_ctx` is not in force. The Ollama log shows `n_ctx_slot = 8192` for all 645 slots
    (`OLLAMA_CONTEXT_LENGTH=8192`). An emoji-heavy 4,000-character message takes 1,937 prompt tokens under
    v1, so the "4,096 chars fits 2048" claim holds only for plain text.
  - Probe 11: the v1/v2 benchmark.
  - D-TG-162: the v2D wording and its measured trade-off against v2A.
  - D-TG-163: the prompt version is an opt-in setting.
- **`spec.md`:** add Clarification 3 (2026-10-01), recording three decisions:
  - v2 is opt-in;
  - the link rule is out of TG-M5 scope;
  - FN/FP is reported in the smoke summary.
- **`quickstart.md`:**
  - §4: smoke both prompts and read the new summary.
  - §5: how to switch `MODERATION_PROMPT_VERSION` and restart `ai-classifier`.
  - §10 gains limitations 13–16:
    - the link rule is not enforced;
    - scheme-less links (`t.me/…`, `wa.me/…`, bare domains) are not redacted, which is a TG-M0
      `moderation-text.md` §3 gap since FR-007 says handles and links must be replaced;
    - `num_ctx` is not applied;
    - media and captions carry links the model never sees.
- **`CLAUDE.md`:** one line saying classify_v2 is opt-in through `MODERATION_PROMPT_VERSION`.

**Also surfaced, needing your decision (not implemented):**
- the link rule (§3);
- the TG-M0 redaction gap for scheme-less links, which is a TG-M0 contract amendment;
- `num_ctx` not being applied, which is M1 or profile territory.

⚠ `docs/real_messages.md` is untracked inside the repo and contains real phone numbers and student messages.
Move it next to `~/Projects/injaz-m5-fixtures/` before any commit.

## 6. Tests (all with the model scripted; `make check` needs no Ollama)

- **`tests/moderation/classification/test_prompt_pinned.py`:**
  - v1's hash is unchanged and v2 gets its own pinned SHA-256;
  - every `*.md` in `prompts/moderation/` is both pinned and allowed;
  - every allowed version has a file.
- **`test_config_classification.py`:** the default is `classify_v1`; blank means the default; `classify_v2`
  is accepted; an unknown value is refused.
- **`test_model_input.py`:** with v2 configured, the system message equals `classify_v2.md`'s bytes, the user
  message is the redacted text, and nothing else is sent. The existing v1 assertions stay unchanged.
- **`test_classify_one.py`** (new cases): v2 configured → the row stores `prompt_version="classify_v2"`;
  under the default, the existing `"classify_v1"` assertion still passes. A catch-up under v2 is still
  `measurement_only`.
- **New `test_smoke_scoring.py`:** a pure summary built from scripted rows checks category exact,
  needs_moderation agreement, the FN/FP line lists, the route tally (via `route_prediction`), the unchanged
  `n/total matched` line, and the non-zero exit on any mismatch.
- **`test_real_model.py`** (`-m llm`): update the call site to pass `prompt_version`.
- **TG-M3 and TG-M4 suites:** must pass untouched. There is no migration and no PHP change.

## 7. Verification (end to end)

1. `make check`. Tests are scripted; quit Ollama first to demonstrate they are independent of it.
2. `FIXTURES=~/Projects/injaz-m5-fixtures/real-moderation.jsonl make smoke-moderation ARGS="--profile ollama-gemma4-e2b-moderation --prompt classify_v1"`
   should give 9/12 matched, mod 9/12, FN 3 (#1, #3, #12), FP 0.
3. The same command with `--prompt classify_v2` should give 11/12 matched (#1 comes back SPAM_OR_AD instead
   of OTHER, an adjacent category), mod 12/12, FN 0, FP 0.
4. `FIXTURES=apps/ai-api/app/scripts/moderation_smoke_policy_fixtures.jsonl make smoke-moderation ARGS="… --prompt classify_v2"`
   should give FN ≤ 1 and FP 0. Run the default shipped set with both prompts as well.
5. Operator switch:
   - set `MODERATION_PROMPT_VERSION=classify_v2` and restart `ai-classifier`;
   - post a synthetic greeting-wrapped ad in the dev group;
   - check that the Model's view shows `classify_v2` and an `ai` incident opens;
   - check that Classification Accuracy shows separate v1 and v2 blocks.
   Rollback is the env flip.
