# Quickstart: TG-M5 — AI Classification

**Audience**: the operator, on this MacBook. Builds on TG-M4's quickstart; everything there still applies.
Runbook: `docs/runbooks/tg-operator-prerequisites.md` §A.1 and §C's TG-M5 row.

---

## 1. What you get

- Every new text message from a student in a measured group is classified by the local model — category,
  needs-an-answer, needs-moderation, severity, and the model's **self-reported** confidence — once, with full
  provenance, never edited.
- A **confident, coherent** violation opens an incident on its own, dated from the platform's posting time and
  from the moment the model flagged it, charged to whoever owned the group at the flag. It then lives exactly
  like one you flagged: ✅ acknowledges, a ban resolves, *Not a violation* closes it.
- An **uncertain or self-contradicting** violation opens nothing. It is listed on **Possible Violations**, where
  you can flag it yourself.
- The model's view appears on the Live Attention Queue and on every incident. **The model opens no question and
  closes nothing** — the rule set stays in charge of questions.
- **Classification Accuracy** compares the model with your own labels — dismissals, hand-added questions, flags,
  false positives — beside the rule set's own figures.
- Still silent: no alert, no message, no bot action.

---

## 2. Before you start

1. **Ollama running**, with the runbook §A.1 launch variables set (`make doctor` says so). The model is the one
   already installed: `gemma4:e2b-it-qat`.
2. **Your fixtures**: 5–10 real Arabic messages whose correct label you already know, one JSON object per line,
   in a file **outside this repository** — real student words are personal data:
   ```json
   {"text": "الكتاب مش ظاهر عندي", "category": "QUESTION_ACCESS", "needs_moderation": false}
   {"text": "عرض خاص دورة STEP كاملة ب 99 ريال تواصل واتساب", "category": "SPAM_OR_AD", "needs_moderation": true}
   ```
   Write them as students write — dialect, missing question marks, emoji. Include at least one advert and one
   question.
3. **`.env`** — add, if you want other than the defaults (every key is optional; blank means default):
   ```
   MODERATION_CONFIDENCE_FLOOR=0.60
   MODERATION_INCIDENT_CONFIDENCE=0.85
   MODERATION_CLASSIFY_MAX_ATTEMPTS=5
   MODERATION_CLASSIFY_RETRY_BASE_S=30
   ```
   While you are there, TG-M4's two panel keys are still missing from this machine's `.env`
   (`MODERATION_PERCENTILE_MIN_SAMPLES=10`, `MODERATION_INCIDENT_MAX_AGE_S=86400`). Compose defaults them now, but
   writing them down makes them yours.
4. **The baseline.** The plan gates this milestone on the rule set's precision having been read over real pilot
   traffic — a week, not an afternoon (TG-M3 quickstart §5). This database has development traffic only (research
   probe 8). Everything below works without it; the comparison in §8 means little until it exists.

---

## 3. Migrate, seed, restart

```bash
make migrate                 # 0006 → 0007
make seed-profiles           # adds ollama-gemma4-e2b-moderation — INACTIVE
make up                      # rebuilds; starts the new ai-classifier service
docker compose -f infra/docker-compose.yml --env-file .env ps   # ai-classifier: Up
```

Nothing is classified yet: no classification model is active. The Live Attention Queue and every incident page
say *"No classification model is active."*

---

## 4. Smoke-test the model before switching it on — runbook §C, as written

```bash
FIXTURES=~/injaz-moderation-fixtures.jsonl \
  make smoke-moderation ARGS="--profile ollama-gemma4-e2b-moderation"
```

One line per fixture — expected against predicted, category and needs-moderation — then `PASS` or `FAIL`, and a
non-zero exit on any mismatch. Without `FIXTURES` it runs the synthetic set shipped with the code. Nothing is
written to the database.

A mismatch is information, not a bug: read which way it went. If the model is wrong on your real messages in a
way that matters, stop here — the instruction version or the model is the thing to change, and both are
decisions, not settings.

---

## 5. Switch it on

Panel → **Platform → Model Profiles** → edit `ollama-gemma4-e2b-moderation` → **Active** → save. It becomes the
only active classification model; the assessment model is untouched. Every message recorded from then on is
classified. Messages recorded while no classification model was active are not — the catch-up command (§7)
reaches them, for measurement only.

To pause classification: the panel refuses to leave a role with no active profile (M1's guard), so stop the
service — `docker compose -f infra/docker-compose.yml --env-file .env stop ai-classifier`. Nothing else changes;
new messages queue for it. Be aware that when you start it again, the queued ones are classified then, and a
confident advert among them opens an incident whose detection moment is *then* — the delay shows as the model's
latency, never against a moderator.

---

## 6. The live check — in the development group

1. **An advert.** From the disposable account, post an obvious advert. Within a minute (model idle):
   **Incidents** shows it, *Opened by: Model*; its detail shows the prediction, the model, `classify_v1`, the
   posting moment and the flagging moment; the responsible moderator is whoever owned the group then. React ✅ →
   acknowledged. Restrict the account → resolved. Exactly TG-M4's lifecycle (SC-002).
2. **A question.** Post a question as a student. The Live Attention Queue row shows the model's view beside it.
   Nothing about the row changes because of it.
3. **The model down.** Quit Ollama. Post a question and answer it as a moderator: the item opens and closes, and
   the response time is exactly what TG-M3 would show. Relaunch Ollama: within a few minutes the message is
   classified — once (SC-003).
4. **The bot said nothing.** Read the group: no message from the bot, ever (SC-021).

Worth trying while you are there: something ambiguous — a student selling a used book. See where it lands.

---

## 7. Catching a group up

Only if you want history classified — for the comparison, since your existing dismissals, hand-added questions and
flags are on old messages:

```bash
docker compose -f infra/docker-compose.yml --env-file .env --profile tools run --rm migrate \
  python -m app.scripts.classify_chat --chat -100XXXXXXXXXX --since 2026-09-01
# classified=… excluded=moderator:…,acknowledgement:… failed=…
```

Every prediction it makes is **for measurement only**: it opens no incident and lists nothing, however confident
— an incident flagged weeks after the fact would be charged to whoever owns the group today. Run it again and it
does nothing. Messages older than the text retention window cannot be classified at all.

---

## 8. Reading the figures — after a week, not an afternoon

**Moderation Intelligence → Classification Accuracy**, period and group of your choice.

- **Rule set baseline** first: that is the number the model has to beat on questions.
- **Questions**: of your dismissals, how many the model would also have got wrong; of your hand-added questions,
  how many it caught. The model opens no question in this milestone, so this is the whole case for or against
  letting it do so later.
- **Violations**: read **independent** flags, not list-prompted ones — a flag you made because the model listed it
  is not you agreeing with the model. Then the one figure that matters most: **model-opened incidents closed as
  false positive**, with its denominator.

**That last figure is the gate.** Decided with the operator (plan, item 3): model-reported confidence is not a
safety signal, and the thresholds are not what makes automatic opening trustworthy. The real pilot false-positive
rate is — model-opened incidents you closed as *not a violation*, over model-opened incidents, with its
denominator. Decide whether to keep the model opening incidents, and later whether TG-M6 may alert on them, from
that figure and nothing else.

**Why confidence cannot do this job** (research Finding 2): this model reports 0.90–1.00 on
nearly everything, including messages it gets wrong. So nearly every coherent violation it sees opens an incident,
and the possible-violations list mostly catches the ones where it contradicted itself. Your false-positive
closures are the control. If they are too many:

- raise `MODERATION_INCIDENT_CONFIDENCE` to `1.0` — only the model's maximum self-report still opens an
  incident; everything else it thinks is a violation moves to Possible Violations for you to judge — then
  `make up`;
- or stop `ai-classifier` while you decide.

Neither changes a past prediction, route or incident.

---

## 9. Verify

```bash
make check                          # offline: Ollama quit, no token set — must pass
make test-llm                       # the one real-model test, if you want it
```

---

## 10. Known limitations

1. **Confidence barely moves** (Finding 2). It routes, but with this model it cannot be relied on to separate
   right from wrong. The false-positive figure in §8 is the real measure.
2. **Edits are not re-classified.** The model judges the words as first posted. A message edited into an advert
   afterwards is not caught by the model; flag it yourself.
3. **Media and captions are not classified**, nor is anything the model would need to see or hear.
4. **One message at a time, no context.** A question spread over three messages is three judgements; the queue
   and the comparison use whichever of them the model said needs an answer.
5. **History is measurement only.** A message that failed live classification, or arrived before the model was
   switched on, can be classified only by the catch-up command — and then opens nothing, even if it is spam.
6. **The labels you see influence the labels you make.** Only flags made from the possible-violations list are
   separated out; everything else you do after seeing the model's view is counted as independent.
7. **A silently deleted advert still gets a model-opened incident** that no evidence will ever resolve —
   TG-M4's attribution gap, now reachable by the model. Confirm it, or close it as not a violation.
8. **The model shares the machine's one-at-a-time lane** with assessment generation. When a long generation holds
   it, classification waits; the wait shows up as the model's detection latency, never against a moderator.
9. **The linked-channel exclusion is unverified live.** It keys off the platform's `is_automatic_forward` field;
   no such post has been captured in development.
10. **Only one generation model is installed.** `qwen3:8b` is in the roster but not pulled; a larger classifier
    needs `ollama pull`, a roster row with the classification params (including `reasoning_effort: none`), a smoke
    run, and activation.
11. **The assessment model thinks too.** The `llm` profile pays the same reasoning cost (Finding 1); fixing it is
    assessment work, not this milestone's.
12. **The comparison is an estimate.** The labels are few, chosen by people rather than at random, and TG-M3's
    recall is a floor. The page says so.

---

## 11. Next

TG-M6 — Alerts: configurable thresholds, a private moderators' group, and the ✅ / 🚫 buttons — including for
the incidents the model opens.
