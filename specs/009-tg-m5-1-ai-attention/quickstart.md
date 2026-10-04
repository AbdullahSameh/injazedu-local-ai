# Quickstart: TG-M5.1 — AI-assisted Attention Opening

## 1. Smoke first, with the switch blank

`make check` passes with Ollama quit. With `MODERATION_AI_ATTENTION_FROM` blank, everything behaves exactly
as TG-M5 left it: the model's needs-response judgement is measured and never acted on.

## 2. Benchmark on your own labelled messages

1. Keep 20–30 real or sanitised messages **outside the repo**, one per line, in
   `~/Projects/injaz-m5-fixtures/real-attention.jsonl`:
   `{"text": "…", "needs_response": true|false, "category": "QUESTION_COURSE"?}`.
   - Include implicit questions or support requests (expected true).
   - Include near-miss statements (expected false), such as «… كان الشرح ممتاز» or «الرابط نزل في المجموعة».
   - Include a few acknowledgements.
2. Rebuild the tools image if the code changed: `docker compose -f infra/docker-compose.yml --env-file .env
   --profile tools build migrate`.
3. Run with Ollama up: `FIXTURES=~/Projects/injaz-m5-fixtures/real-attention.jsonl make smoke-attention
   ARGS="--prompt classify_v2"`.
4. Read these lines:
   - `false positives`: the model said a statement needs an answer;
   - `model-opened on expected-false (new moderator work)`: the false positives the rules would not already
     have opened;
   - `false negatives`: questions the model missed;
   - `opener, expected true`: how many of your questions anyone would open.
5. Record the counts (never text) in `research.md` §2. The decision to switch on is yours.

## 3. Switch on in development

1. In `.env`, set `MODERATION_PROMPT_VERSION=classify_v2` and `MODERATION_AI_ATTENTION_FROM=<now, with an
   offset>`, e.g. `2026-10-04T09:00:00+03:00`.
2. Recreate the services that read the switch: `docker compose -f infra/docker-compose.yml --env-file .env up
   -d --build ai-worker ai-classifier`.
3. From the student account, post «في محاضرة اليوم». After about 90 s:

   ```sql
   SELECT c.id, c.category, c.needs_response, c.path, c.route, c.prompt_version, c.confidence
   FROM message_classifications c JOIN telegram_messages m
     ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
   WHERE m.id = (SELECT max(id) FROM telegram_messages WHERE NOT is_from_moderator);

   SELECT id, source, status, rule_version, message_classification_id, opened_at,
          responsible_moderator_id, first_response_at, first_response_kind,
          first_response_moderator_id,
          extract(epoch FROM first_response_at - opened_at) AS frt_s
   FROM attention_items ORDER BY id DESC LIMIT 1;
   ```

   Expect `needs_response = t`, `path = live`, `source = ai`, `status = open`, `rule_version` NULL,
   `opened_at` = the message's `sent_at`. The queue shows "Opened by: Model".
4. Reply as a moderator. Expect `status = answered`, the `first_response_*` fields set, and
   `frt_s` = reply − question.

## 4. Roll back

Blank `MODERATION_AI_ATTENTION_FROM` and recreate `ai-worker` and `ai-classifier`. Items already opened stay
(TG-M3 E4: nothing retracts an item), and nothing new opens.

## 5. Read the pilot

On Classification Accuracy, under "Questions the model opened", the **dismissed as not a real question** ratio
is the operational gate. Read it after a week, with its denominator. "Model-opened and kept", beside the rule
baseline, is the count of rule misses the model caught.

## 6. Known limitations

These are in `contracts/attention-opening.md` §9:
- growing bursts can be credited to the model;
- questions only the model can see go untracked while the classifier is down;
- hand-opening takes no lock (pre-existing);
- the rule-recall floor reads higher while the switch is on.
