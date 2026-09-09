# Quickstart: TG-M0 — Moderation Intelligence Domain Foundation

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09
**Audience**: the operator, on this MacBook. Companion to
`docs/runbooks/tg-operator-prerequisites.md` §A and §C (TG-M0 row).

TG-M0 has **nothing to click and nothing to watch**. It makes no Telegram call, creates no table and
adds no screen. Its entire acceptance is: the quality gate passes with no credential, and it *fails*
when any of five rules is broken. This page is how you confirm both.

---

## 1. Before you start

```bash
make doctor        # must be green
```

`make doctor` will still flag the one item carried from M0/M1: the four Ollama launch variables.
They are not needed until TG-M5, but the runbook says set them now:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_FLASH_ATTENTION 1
# quit Ollama from the menu bar and relaunch — it reads these only at launch
make doctor
```

**No bot is created in this milestone.** BotFather work is runbook §B and belongs to TG-M1. Nothing
here needs a credential, a group, or Telegram at all.

The seven decisions in runbook §A.2 are worth making now, but none of them blocks TG-M0 — four block
TG-M3 and TG-M6.

---

## 2. The smoke test

This is the whole of it:

```bash
make check
```

> ⚠ **Before you rely on this: `make check` is red on the committed tree as of 2026-09-09.**
> `scripts/scan_secrets.sh` reports six findings, all false positives, all pre-existing — local
> variables ending `_token` in `test_lanes.py`, a `MIGRATOR_PASSWORD="$(grep …)"` line in
> `test_db_reset.sh`, and `scan_secrets.sh` detecting its own three pattern definitions. None is a
> real credential. The fix is a decision about what the scanner should consider a secret, which is
> yours to make — see `plan.md` § Blocking Prerequisite. TG-M0 cannot be accepted until it is green.

It must pass **offline**, with Ollama quit, with no network, and with **no `TELEGRAM_BOT_TOKEN`
set** (SC-003). Then prove the credential really is optional rather than merely absent from your
`.env`:

```bash
TELEGRAM_BOT_TOKEN= make check      # explicitly empty — must also pass
```

You should see three new lines in the architecture section, beside the existing httpx rule:

```
== architecture ==
  OK: no httpx/ollama/openai import and no task-prefix string outside app/providers/
  OK: moderation imports only the 7 permitted prefixes
  OK: no assessment-side module imports moderation
  OK: no Telegram SDK imported outside app/providers/telegram/
```

---

## 3. Prove the gate actually bites

A grep that matches nothing passes silently forever, so verify each rule fires. Plant one violation
at a time, run `make check`, confirm it fails and names the file, then revert.

```bash
# 1 — moderation reaching into assessment (forward rule)
echo 'from app.application.health_service import build_report' \
  >> apps/ai-api/app/application/moderation/text.py
make check          # must FAIL, naming text.py
git checkout -- apps/ai-api/app/application/moderation/text.py

# 2 — assessment reaching into moderation (reverse rule)
echo 'from app.application.moderation.text import normalize' \
  >> apps/ai-api/app/application/health_service.py
make check          # must FAIL, naming health_service.py
git checkout -- apps/ai-api/app/application/health_service.py

# 3 — a Telegram SDK outside the provider
echo 'import telegram' >> apps/ai-api/app/application/moderation/text.py
make check          # must FAIL
git checkout -- apps/ai-api/app/application/moderation/text.py

# 4 — message text in a log line
echo 'logger.info("msg %s", normalized_text)' \
  >> apps/ai-api/app/application/moderation/text.py
make check          # must FAIL
git checkout -- apps/ai-api/app/application/moderation/text.py

# 5 — a credential-shaped value in a tracked prose file
# built at runtime so this page never itself contains a token-shaped literal — see note below
printf 'token 8123456789:%s\n' "$(printf 'A%.0s' {1..35})" >> README.md
git add README.md && bash scripts/scan_secrets.sh   # must FAIL, naming README.md
git restore --staged README.md && git checkout -- README.md
```

Row 5 is the one worth doing by hand at least once: it is the case the *existing* scan does not
cover, and it is the exact shape of the risk (a token pasted into a spec or runbook) that this
documentation-heavy track will actually hit.

Note the shape of that command. The first draft of this page wrote the sample token as a literal —
and would then have failed its own rule the moment check 5 shipped, because this file is tracked.
Building it at runtime keeps the page scannable. Any future doc showing a sample token must do the
same, or truncate it below 35 characters after the colon. The rule's *regex*, written out, is always
safe: it does not match itself.

> The `git` commands above are yours, not the agent's — Constitution Principle IV. The agent's own
> verification uses the same plants without staging anything.

---

## 4. Prove the settings refuse bad values

```bash
MODERATION_TEXT_RETENTION_DAYS=0 make check
# Configuration error: moderation_text_retention_days: MODERATION_TEXT_RETENTION_DAYS must be positive (got 0)

MODERATION_BURST_GAP_S=-1 make check
# Configuration error: moderation_burst_gap_s: MODERATION_BURST_GAP_S must be positive (got -1)
```

Both must exit 1 with that one line and **no stack trace**.

This is not config pedantry. `MODERATION_TEXT_RETENTION_DAYS=0` reaching TG-M10's purge job would
null every message text on its first run, and `MODERATION_BURST_GAP_S=0` would make every message its
own burst and silently inflate the numbers TG-M3 reports. Both are typos that otherwise produce
plausible-looking output.

---

## 5. Reproduce the two measurements that shaped the design

Both are pure Python, no dependencies, no stack running.

**⚠ Why the repeated-character collapse is letters-only** — the finding that corrects the source
plan's §15.4:

```bash
python3 - <<'PY'
import re
naive   = re.compile(r"(.)\1{2,}")               # "collapse repeated characters", literally
letters = re.compile(r"([^\W\d_])\1{2,}", re.U)  # what TG-M0 implements
for s in ["0555555555", "٠٥٥٥٥٥٥٥٥٥", "تمااااام", "الله", "😂😂😂😂"]:
    print(f"{s:14} naive={naive.sub(r'\1', s):14} letters={letters.sub(r'\1', s)}")
PY
```

`0555555555` becomes `05` under the naive rule. Since normalisation runs *before* redaction, the
redactor would then find nothing to replace: `«رقم»` never appears and a mangled fragment goes to the
model. Worse, it is inconsistent — `0501234567` has no triple digit, survives, and *is* redacted. One
rule, two phone numbers, two different outcomes.

**⚠ Why the log key is `message_id` and not `message`:**

```bash
python3 - <<'PY'
import logging
log = logging.getLogger("probe"); log.addHandler(logging.NullHandler())
log.setLevel("INFO")          # REQUIRED: below the effective level, logging skips makeRecord
                              # entirely and the KeyError never fires — the check lives there
for name in ["update_id","chat_id","message_id","incident_id","alert_id","actor","message"]:
    try:
        log.info("t", extra={name: "v"}); print(f"  {name:12} accepted")
    except KeyError as e:
        print(f"  {name:12} KeyError {e}")
PY
```

All six whitelisted keys are accepted; `message` is rejected outright by stdlib. The suffix is not a
style choice.

The full set of eight probes is in `research.md` §0.

---

## 6. What you now have — and what you deliberately do not

**Have:**

- Four moderation package areas, with the boundary between the two domains checked mechanically.
- An Arabic normaliser and a redactor, both pure, deterministic and idempotent, with the exact
  transformation table written down in `contracts/moderation-text.md`.
- Five settings with safe defaults, and a credential whose absence is a fully supported state.
- Six correlation keys in the logs, and message text structurally unable to reach them.
- A secret scan that catches a token pasted into prose, not just into `.env`.

**Do not have, on purpose:**

- Any Telegram connection. No poller, no `getMe`, no credential validation — TG-M1.
- Any table. Alembic revisions `0003`–`0009` are reserved and untouched.
- Any moderation entry in `/health`. TG-M1 adds `telegram_ingestion`; an always-"not configured"
  component now would be noise.
- Any screen. The Filament panel is unchanged; it has no Moderation Intelligence navigation group
  until TG-M7.
- Any model call, taxonomy or prompt — TG-M5.

---

## 7. Known limitations

**Inherited from Telegram, permanently, and no design here can work around them** (source plan §5,
runbook §F):

1. **No update is emitted when a message is deleted in a group, and no way exists to learn who
   deleted it.** The admin log is an MTProto feature a bot cannot read. Every later milestone measures
   what *is* observable — replies, reactions, bans, restrictions, each with an attributable actor and
   a timestamp — and labels absences as absences. A fast, quiet moderator who silently deletes will
   look worse than a slow, loud one. This is stated wherever the number appears; it is never folded
   into a single score.
2. **There is no history API, and undelivered updates are kept for at most 24 hours.** Nothing before
   the bot joins can ever be recovered, and a poller offline longer than a day loses that window
   permanently — a gap that looks identical to "the moderator was fast".

**Of this milestone:**

3. **The normaliser is validated for correctness, not yet for dialect recall.** The checked-in
   fixtures cover the measured equivalence classes and the edge cases; the risk they exist to reduce —
   poor recall on Saudi and Egyptian dialect — can only be measured against real messages. Supplying
   5–10 real Arabic messages whose correct handling you already know is worth doing before TG-M3, and
   the runbook asks for them at TG-M5 anyway.
4. **Redaction over-redacts long digit runs on purpose.** A course code, a national ID or a transfer
   reference becomes `«رقم»`. Years and lecture numbers are short enough to survive. This is the safe
   direction for a privacy control and it is documented rather than tuned.
5. **Redaction cannot remove personal names written as free text.** No pattern can. The guarantee that
   identity does not reach the model comes from the request never carrying an identity *field* —
   `contracts/moderation-text.md` §4 — not from the redactor.
6. **FR-024 and FR-025 are a contract, not code, in this milestone.** There is no model call yet to
   guard. TG-M5 must follow §4 of that contract; TG-M0 gives it the written rule and the functions,
   not an enforcement mechanism.
7. **The "no text in logs" grep is a backstop, not the guarantee.** The formatter's six-key whitelist
   is what makes text structurally unable to reach the output through `extra=`. The grep covers the
   remaining route — interpolation into the message string — and, being line-based, a multi-line call
   could evade it.

---

## 8. Next

TG-M1 — Telegram event ingestion. Before it starts, runbook §B: create **both** bots (dev and live),
disable privacy mode **before** adding either to any group, create the dev group with two extra
accounts in it, promote the bot to administrator, and put the **dev** token in `.env`. Only the dev
bot is used until the TG-M3 pilot.
