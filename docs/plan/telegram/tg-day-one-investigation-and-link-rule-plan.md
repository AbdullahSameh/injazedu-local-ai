# Moderation investigation (2026-10-18): false incidents, live attention, backlog

> **Execution scope (operator, 2026-10-18).**
> 1. Save this plan as `docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md`.
> 2. Do **Step 0** (production backlog dismissal) and **Step 1** (link rule + AI advert guard) only.
>
> Steps 2–3 stay documented and are not implemented. Git actions (commit, push, deploy) remain the operator's.
> Step 1 ends with `make check` passing on the Mac and the deploy command handed over.

> **Status (2026-10-18).**
> - **Step 0 done.** At 2026-10-17 22:06 UTC, 15 open items were dismissed `before_pilot` (user 1). A dump came
>   first: `dumps/injaz_ai-20261017T220609Z-before-backlog-dismissal.dump`. The queue was empty afterwards.
> - **Step 1 implemented, not deployed:**
>   - migration `0010`;
>   - `link_rule_opens` and `has_contact_signal`/R4b;
>   - derive and edit wiring;
>   - panel labels;
>   - dated amendments to the 005, 007 and 008 contracts;
>   - a runbook §11 note.
> - **Edit semantics as built:** the guard reads the row's recorded (sticky) `entity_flags` plus the redacted
>   words. The rule on an edit reads the edit's own entities, and the first-posted event's `is_automatic_forward`.

## Context

On day one (2026-10-17, one monitored group, 92 messages), production opened legitimate student requests as
policy incidents. It also kept Attention Items open after members had already replied. Two more needs:
- a new rule: a link from a regular member always opens a policy incident;
- today's open queue cleared without being judged, so measurement starts 2026-10-18.

All production access was read-only: `PGOPTIONS=default_transaction_read_only=on`, plus `grep` of named non-secret
`.env` keys. Production runs **5661dcd, the same commit as local `main`**, with `classify_v2` and both attention
settings blank. Message texts below are only the three you supplied.

---

## 1. Confirmed findings

### 1a. The three false incidents were opened by the AI, not by rules
- **Incidents #1 (165521), #6 (165563) and #7 (165594).**
  - Every one is `source='ai'`, `classify_v2`, `SPAM_OR_AD`, `needs_moderation=true`, self-reported 0.95,
    `route='incident'`, live path.
  - None carries a link, phone, mention or forward (`entity_flags`).
  - You already closed all three as false positives.
- **The only incident writers** are `classify_one`, with `source='ai'`
  (`apps/ai-api/app/application/moderation/classification.py:456-469`), and the panel's `openOn`, with
  `source='operator'`. The schema allows only `('operator','ai')`, and **no rule ever opens an incident.**
- **Prompt cause** (`apps/ai-api/app/prompts/moderation/classify_v2.md:12`):
  - SPAM_OR_AD lists *topics*: "files, summaries, **collections** … another **group or channel**".
  - The carve-out covers only "whether anyone has a **file or summary**".
  - Requests *for* collections or a group therefore match the advert list.
  - This is the same topic-versus-function failure that stopped TG-M5.2.
  - Confidence (0.95–1.00 on everything) gives no signal, so thresholds cannot fix it.
- **Day-one tally:** 7 AI incidents, of which **4 were false positives** (57%; the pilot gate is this rate):
  - your 3 examples;
  - #2, a moderator's own post at 14:55, before moderators were declared at 16:15. `is_from_moderator` is fixed
    when a message is stored, so it stays false.
- **Only #5 of the 4 AI incidents on link-less messages was real** (an investment referral). The 2 survey-link
  incidents were real too.
- **#8 (a bare bot link) was missed by the AI** (`OTHER/none`). You opened it by hand.

### 1b. Link detection exists but nothing enforces it
- `_entity_flags` (`apps/ai-api/app/application/moderation/messages.py:112-120`) reads Telegram `url`/`text_link`
  entities from text **or caption**, plus phone, mention and forward fields.
  - It flagged hidden text links correctly (165529, 165531).
  - It is computed only on first insert; `apply_edit` (`:341`) never re-reads it.
- **Captioned media never reach the model:** `media` exclusion E3, 9 messages on day one.
- **The admin concept is the `moderators` table only** (`is_from_moderator`, `identities.moderator_id_for`):
  - anonymous admins (`sender_chat` = the group) are excluded from classification (E6);
  - linked-channel automatic forwards are excluded (E7);
  - nothing reads Telegram's administrator list.
- **The link rule is already planned but unbuilt:**
  - `docs/plan/telegram/tg-m5-classify-v2-plan.md` §3;
  - `specs/008-tg-m5-ai-classification/spec.md:98-102, 726-729` ("its own milestone": `source='rule'`, new
    revision, metrics exclusion, panel label).

### 1c. Live attention
- **All 42 items are `source='rule'`**, and there are 0 attention judgements: AI attention is off.
- **The queue's "Model's view" is `classify_v2`'s per-message category**, e.g. QUESTION_COURSE, "سؤال عن الدورة"
  (`LiveAttentionQueue.php:160-165, 261-274`). It is *not* the attention judgement, and it never sees replies.
- **Only three things close an item:**
  - a declared moderator's message, either (a) a direct reply or (b) the next group message, which closes the
    oldest open item with **no time window**;
  - a dismissal;
  - expiry after 24 h.
- **Member replies never close an item**, by design (`messages.py:279-288`, `test_matching.py:208`).
- **Day one: 18 of 42 items were dismissed as noise** (16 Member discussion, 2 Not a real question). Lexical traps
  seen:
  - "إيه" (yes) matched as "ايه" (what);
  - member answers containing "متى", "من" or "؟" opened items.
- **5 of the 8 "answered" items were closed by moderator broadcasts** through rule (b): promo posts, a "closing the
  group" announcement and a sticker, 4–7 h later. Only 3 items (22, 26, 27) were genuinely answered (direct
  replies), so the day's first-response-time figures are not meaningful.
- **7 of the 15 open items have member replies.** On the 4 where the asker replied back:
  - one acknowledgement;
  - one follow-up that shows an unresolved problem (item 17);
  - two moves to private chat.

  Reply facts alone cannot tell "answered" from "discussion" from "still stuck".
- **How dismissed and expired items count:** a dismissal is excluded from first response time and from unanswered,
  and an unknown `close_reason` counts as "dismissed (other)" (`ClassificationMetrics.php:377`). An expired item
  counts as unanswered.

### 1d. Existing plans
- `docs/plan/telegram/tg-attention-rule-ai-hybrid-review.md` covers model-assisted filtering. It is in phase A:
  rules only, dismiss with reasons, blind labels. Auto-dismissal there means a non-terminal "parked" state after
  gates F-1…F-3 (≥100 strong positives, 0 dangerous misses).
- **No plan uses replies or conversation context.** The model input forbids neighbours (N7/D8), and the source
  plan defers a `conversations` table.

## 2. Hypotheses (not verified)

| | Hypothesis | How to check |
|---|---|---|
| H1 | Adding "collections/group" to the carve-out would fix the three cases | Only a qualified new wording proves it |
| H2 | Telegram admins exist who are not declared moderators; the link rule would flag them | Compare by hand in Telegram |
| H3 | A 30-minute window on rule (b) loses no real answers | Day one had none to lose |
| H4 | "Member reply + the asker's acknowledgement" signals "answered by a member" | 1 of 15 on day one |

---

## 3. Decisions taken (2026-10-18)

- **Backlog:** dismiss with its own reason.
- **Link rule:** includes forwarded posts, edited-in links and bots. @handles are left to the AI.
- **Admin:** a declared moderator.
- **AI guard:** a SPAM_OR_AD prediction with no contact signal is listed, not opened.

## 4. Implementation, in separately approvable steps

### Step 0: clear today's queue (production data, after approval, about 5 minutes)

On the server:
1. Take a `pg_dump`, as in runbook §9.
2. Run one transaction as `ai_control`, the panel's own role and write, through
   `scripts/prod/dc exec -T postgres psql -U postgres -d injaz_ai` with `SET ROLE ai_control`:

```sql
BEGIN;
SET LOCAL ROLE ai_control;
SELECT pg_advisory_xact_lock(hashtext('attention:chat:1'));   -- same key as locks.py chat_lock
SELECT id FROM attention_items WHERE status='open' AND opened_at < '2026-10-17 21:00+00';  -- expect 15
UPDATE attention_items SET status='dismissed', close_reason='before_pilot', closed_at=now(), closed_by_user_id=1
 WHERE status='open' AND opened_at < '2026-10-17 21:00+00';                                -- = 2026-10-18 00:00 Riyadh
COMMIT;
```

- Abort if the count is not as listed.
- From then on, read figures with the period starting **2026-10-18**. That also drops day one's broadcast-closed
  "answers".

### Step 1: link rule + AI advert guard (one PR; migration `0010`; its own small milestone, e.g. TG-M4.1)

**Pure rule.** `link_rule_opens(facts)` in `apps/ai-api/app/domain/moderation/incident.py`, with
`LINK_RULE_VERSION = 1`. It opens when:
- the message has a `has_url` entity, in text or caption;
- the sender is a person or a bot;
- the sender is not a declared moderator;
- `sender_chat` ≠ the group itself;
- it is not `is_automatic_forward`;
- it is not a service message.

Forwarded posts by members count.

**Opening.** Change `derive_message` (`messages.py:175-299`):
- Only when `schedule_classification` is true (the live path; re-derivation opens nothing).
- Insert through `insert_incident` (`incidents.py:35`, extended for `source='rule'` and `rule_version`) **in the
  same transaction as the message**.
- The rule runs before `classify_message` is sent, so it always wins. The AI's later insert hits
  `uq_incident_anchor` and opens nothing; its prediction is still recorded (R12 is already there).
- The incident is `category='OTHER'`, `severity='low'`, and the panel labels it "Link rule".

**Edits.** `apply_edit` (`messages.py:341`):
- reads the edited body's entities;
- stores `entity_flags` as an OR ("ever carried"), a dated amendment to the message-derivation contract;
- applies the same rule on the live path only.

**AI guard.** `has_contact_signal` (pure, in `apps/ai-api/app/domain/moderation/classification.py`) is true for any
of these:
- `has_url`, `has_phone`, `has_mention` or `forwarded` on the first-posted captured event;
- one of `«رابط» «رقم» «بريد» «مستخدم»` in the redacted text.

Words such as "خاص" are rejected: "خاصة" (special) appears in false positive #6. `route_prediction` gains rule
**R4b**:
- SPAM_OR_AD with no signal routes to `possible_violation / no_contact_signal`;
- ABUSE and everything else are unchanged.

`classify_one` computes the signal and passes it in.

**Migration `0010`** (head is `0009`):
- `ck_incident_source` gains `'rule'`;
- `moderation_incidents.rule_version smallint` is added, with CHECK `(source='rule') = (rule_version IS NOT NULL)`;
- `ck_classification_route_reason` gains `'no_contact_signal'`;
- there is no GRANT.

**Figures:**
- C3 (model false positives) already filters `source='ai'`, so it is unchanged.
- Add the new route reason and the "rule" source to the breakdowns in both `app/application/moderation/metrics.py`
  and `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php`.

**Panel:**
- the source label in `IncidentsTable.php` and `IncidentInfolist.php`;
- the reason label in `PossibleViolations.php`;
- `lang/ar.json` entries, with the English byte-identical.

**Contracts (dated amendments):**
- 007 incident source vocabulary;
- 008 `classification-pipeline.md` R4b and route reasons;
- 004 derivation (sticky flags on edit);
- `docs/runbooks/production-deployment.md`: declare every Telegram admin as a moderator **before** go-live of the
  rule (H2).

### Step 2: reply tracking and queue context (one PR)

> **Decisions (operator, 2026-10-18):**
> - **Answer window:** 30 minutes (`MODERATION_GROUP_ANSWER_WINDOW_S=1800`).
> - **Never an answer, whatever the timing:** forwarded posts and media- or sticker-only messages. A post with a
>   link can still answer.
> - **Fourth dismiss reason:** "Answered by a member" (`member_answered`, Arabic "أجاب عنه عضو").
> - **The Live Attention Queue's row actions move into one dropdown menu** (a Filament `ActionGroup`): the four
>   dismiss reasons and Open incident. This keeps the table narrow. There is still one shared confirmation (K2) and
>   no bulk action.

**Narrow rule (b)** (`apps/ai-api/app/application/moderation/attention.py:710-720`, `_oldest_open_item_before`).
A moderator's non-reply message answers the oldest open item only if:
- it is not forwarded;
- it is not media-only;
- it is sent within `MODERATION_GROUP_ANSWER_WINDOW_S` (default 1800) of that item's last burst message.

Direct replies are unchanged. This is a dated amendment to
`specs/006-tg-m3-response-tracking/contracts/attention-rules.md` §4(b), plus a runbook note: moderators answer with
Telegram's **Reply**.

**"Replies" column on the Live Attention Queue.** It is display-only (Q1–Q2: it never filters, sorts or hides):
- the number of member direct replies;
- whether the asker replied back.

It takes one query per page, like `classificationLabelsForItems`.

**Fourth dismiss reason, "Answered by a member"** (`member_answered`):
- In `LiveAttentionQueue.php`, add the row action and extend the shared K2 confirmation text.
- Add the reason to the per-reason SQL in `metrics.py:97-104` and `ClassificationMetrics.php:371-450`.
- Amend the `dismissal-reasons.md` contract.
- The three outcomes, needs the team / member discussion / answered by members, then become separately counted
  human labels. Still no bulk action, and a member reply still never closes anything.

### Step 3: needs real-world evaluation (no code now)

- **2–4 weeks of reasoned dismissals.** Then:
  - rule set v2 lexical fixes (e.g. "ايه", "من") from the per-reason figures (hybrid review, phase R);
  - a shadow-only, deterministic "member-answered candidate" signal: a member direct reply, then the asker's
    `is_acknowledgement` reply, and no further question from the asker. Measure it against the outcomes before
    showing anything (H4).
- **Auto-dismissal or auto-resolution only per the hybrid review §9:**
  - a non-terminal, reversible "parked" state;
  - never `dismissed` or `answered`;
  - after F-1…F-3.
  - A conversation-aware model would also need a new contract (lift N7) and a D′ qualification. `e4b` cannot run
    on this host.
- **A classify wording with a request carve-out.** Add the closed-false-positive incidents to the real fixtures
  outside the repo, and qualify on the production host before it replaces `classify_v2`. Until then, the R4b guard
  holds.

## 5. Verification

**Step 0:** the before and after `SELECT`s show 15 rows moved, and the queue shows no item opened before the
cutoff.

**Step 1 tests:**
- **Pure tables:**
  - `link_rule_opens` covers: member link, caption link, `text_link`, forwarded member link, and bot link (all
    open); moderator link, anonymous admin, linked channel, service message and no link (none open).
  - `has_contact_signal` covers each token and flag.
  - `route_prediction` R4b covers the three day-one false-positive shapes, which route to possible violation;
    phone or forward, which routes to incident; and ABUSE, which is unchanged.
- **Application, on the test DB:**
  - `derive_message` live opens exactly one rule incident;
  - a duplicate delivery and re-derivation open nothing;
  - an edit adding a link opens one;
  - a later AI incident route records the prediction with no second incident;
  - `classify_one` routes to `no_contact_signal`;
  - migration `0010` upgrades and downgrades cleanly.
- **PHP:** source and reason labels, `PanelTranslationCoverageTest`, `IncidentWordingArabicTest`, and the existing
  suites.

**Step 2 tests:**
- `test_matching.py`: a late broadcast, a forward and a sticker close nothing; a group answer within the window
  closes the oldest item; a direct reply is unchanged.
- `AttentionDismissTest.php`: `member_answered`.
- `LiveAttentionQueueTest.php`: the Replies column is display-only.

**Release:**
1. Run `make check` on the Mac only.
2. Deploy with `scripts/prod/deploy.sh <sha>`, reading `0010` before confirming.
3. Live check: a non-moderator test account posts a link and a "Link rule" incident opens; a moderator posts one and
   nothing opens.
4. Watch Possible Violations for `no_contact_signal` rows.
