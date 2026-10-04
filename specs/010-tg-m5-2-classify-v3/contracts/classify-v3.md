# Contract: the `classify_v3` instruction

**Feature**: `specs/010-tg-m5-2-classify-v3` · **Status**: durable once frozen. The frozen bytes are copied into
`specs/008-tg-m5-ai-classification/contracts/classification-pipeline.md` §2b (D-TG-181). Until then, this
contract states what the file must satisfy and how it is frozen.

## §1 — What `classify_v3` must satisfy

- **V1.** The file is `apps/ai-api/app/prompts/moderation/classify_v3.md`. It is selected by
  `MODERATION_PROMPT_VERSION=classify_v3`. The default stays `classify_v1`, and v1 and v2 stay byte-identical
  (FR-201).
- **V2.** It keeps v2's schema, the seven categories, the five values and `taxonomy_version = 1` (FR-203). The
  request is still exactly `system` = this text and `user` = the redacted text (pipeline P3).
- **V3.** These v2 lines and paragraphs are **byte-identical** (FR-204):
  - the intro;
  - the group rule;
  - the "Judge what the whole message is for…" paragraph;
  - `COMPLAINT`, `CHITCHAT`, `SPAM_OR_AD` and `ABUSE`;
  - `needs_moderation`, `severity` and `confidence`;
  - the final line.
- **V4.** The `needs_response` line ends with the sentence `Always false for SPAM_OR_AD, ABUSE and CHITCHAT.`,
  verbatim. TG-M5.1's G4 rests on it, and a test checks it in **every** pinned instruction.
- **V5.** It decides needs-response by what the writer wants (FR-202): asking, informing and mixed, with Policy S
  stated once. A question mark decides nothing.
- **V6.** It quotes no benchmark text and lists no fixture-shaped nouns. It is at most v2 + 1,200 characters
  (FR-205, D-TG-172).
- **V7.** Once frozen, its SHA-256 is pinned beside v1's and v2's. A later change is a new file and a new
  version (D-TG-136).

## §2 — Starting draft (F1). Not frozen

This is the measured P2 with its noun lists made generic and one "mixed" sentence added: 3,729 characters, v2 +
1,084. These are the only differences from `classify_v2.md`. Every other line is v2's, byte for byte.

**Inserted after the "Judge what the whole message is for…" paragraph,** followed by a blank line:

```text
Asking or informing: members often ask without a question mark, as a short statement. Decide first whether the writer still needs something from a moderator.
- Asking: a question or request; a problem the writer still has; or a bare statement of a course arrangement with nothing added — that something exists, is today, has changed or has happened. The writer is a member, not a moderator, and members rarely announce arrangements: such a bare statement is a check and needs an answer.
- Informing: the message adds what a person asking would not know — the time, day, place, deadline or where to find it — passes on what was announced, confirms that something arrived, appeared or works for the writer, or says a problem is solved. Telling the group something is not asking, even when it is about the course. A message that informs and also asks is asking.
```

**Replaced lines** (v2 first, then v3):

```text
- QUESTION_COURSE: a question about the course itself — lecture times, links, content, materials, exams.
- QUESTION_COURSE: the writer asks about the course itself — lecture times, links, content, materials, exams.

- QUESTION_ACCESS: a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.
- QUESTION_ACCESS: the writer still has a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.

- OTHER: none of the above.
- OTHER: none of the above, including a message that only informs: it gives course information, confirms something arrived or works, or says a problem is solved.

- needs_response: true only if the writer asks a question or reports a problem that a moderator should answer. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.
- needs_response: true only if the writer is asking: a question, a request, or a problem they still have, that a moderator should answer. False when the message only informs. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.
```

**About the sentence "The writer is a member, not a moderator…".** It states a constant fact: moderators'
messages never reach the model (eligibility E5). It is the same for every message and says nothing about any
sender, so pipeline P1–P5 ("the model sees words, never people") hold.

## §3 — Freeze protocol (D-TG-172)

1. **F1.** Place the starting draft as `classify_v3.md`. Add `classify_v3` to the allowlist with its current
   hash pinned **provisionally**, so `make check` stays green. No deployment is set to it, and nothing is
   committed until the freeze. Run the qualification (`contracts/qualification.md`) on the e4b reference
   profile and on the e2b development profile.
2. **The F1 gate.** On e4b, the **tuning** gates Q1, Q3, Q5–Q8, Q10 and Q11 must pass.
   - The held-out (Q2, Q4) and fresh-sample (Q9) gates are not run yet; the held-out set does not exist before
     the freeze.
   - e2b is recorded for information only.
3. **F2, only if F1 fails a tuning gate that P2 passed.** One edit, which may only move the failing sentence
   back toward P2's measured text. Re-run.
4. **Freeze.** The provisional pin becomes final; under F2 it is re-pinned once. Copy the bytes into 008 §2b
   and record the counts in `research.md` §2.
5. **Stop, if F2 also fails.** The milestone stops (FR-216) and reports. There are no further rounds.
6. **After the freeze:** write the held-out set (data-model §3), run it once on e4b, and record the result.
   It is never tuned against.

## §4 — What may never happen

- **X1.** Editing `classify_v1.md` or `classify_v2.md`, or changing a pinned hash.
- **X2.** Editing `classify_v3.md` after its hash is pinned.
- **X3.** A deployment (development or production) running an unpinned `classify_v3`.
- **X4.** Tuning against the held-out set or the operator's fresh sample.
- **X5.** A benchmark label changed by the implementer.
