# Phase 0 Research: TG-M0 — Moderation Intelligence Domain Foundation

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09
**Source plan**: `docs/plan/telegram/telegram-moderation-intelligence.md`
(§6 boundary, §15.4 normalisation, §15.5 redaction, §19 privacy/security, §21 observability,
§25 TG-M0, §27 risks, §30 spec-kit breakdown)
**Operator runbook**: `docs/runbooks/tg-operator-prerequisites.md` (§A, §C TG-M0 row, §F)

12 decisions, **D-TG-17 … D-TG-28**, continuing the source plan's `D-TG-NN` namespace (it ends at
D-TG-16) so a decision id stays unique across the project — the convention §30 requires.

Every "measured" line below was run on this machine on 2026-09-09 with CPython 3.12. The probe
scripts are reproduced in `quickstart.md` §6 so the operator can re-run them. Nothing here required
Ollama, Postgres, Redis, a network call or a Telegram credential — which is itself the point of this
milestone.

---

## 0. Ground truth measured this session

Eight probes, all pure-Python, against the exact transformations this milestone specifies.

| # | Probe | Result | Consequence |
|---|---|---|---|
| 1 | Does `NFKC` fold Arabic-Indic (`٠-٩`) and Eastern (`۰-۹`) digits to ASCII? | **No** — `changed=False`, codepoints unchanged | Digit folding must be an explicit translation table, not a side effect of NFKC → D-TG-20 |
| 2 | Does `NFKC` strip tatweel (`ـ` U+0640)? | **No** — `مـتـى` survives intact | Tatweel must be stripped explicitly → D-TG-20 |
| 3 | Does `NFKC` fold ligatures and presentation forms? | **Yes** — `ﻻ`→`لا`, `ﺑ`(U+FE91)→`ب`, NBSP→space; and `ﷺ`(U+FDFA) **expands to the 18-character phrase** `صلى الله عليه وسلم` | NFKC earns its place as step one; the honorific expansion is harmless and slightly helpful for rule matching → D-TG-20 |
| 4 | Does `NFKC` remove bidi marks (RLM U+200F / LRM U+200E)? | **No** — both survive | Invisible characters that break literal matching must be stripped explicitly, **excluding ZWJ U+200D** which emoji sequences need → D-TG-20 |
| 5 | **Repeated-character collapse on a phone number** — `(.)\1{2,}` → `\1` applied to `0555555555` | ⚠ **`05`** | **A naive collapse silently destroys the very phone number the redactor exists to replace.** → **D-TG-21** |
| 6 | Same collapse restricted to letters — `([^\W\d_])\1{2,}` | `0555555555` **unchanged**; `تمااااام`→`تمام`; `شششكرا`→`شكرا`; `الله` unchanged; `😂😂😂😂` unchanged — where the naive rule collapses it to a single emoji | Letters-only collapse satisfies FR-018 and FR-019 simultaneously → D-TG-21 |
| 7 | Redaction applied twice to 9 mixed Arabic/Latin fixtures | Identical output on **9/9**; `https://x.com/@someone` → one `«رابط»`, not a nested substitution | Idempotence and overlap-determinism come free from the ordering, with no guard code → D-TG-22 |
| 8 | Stdlib `logging` `extra=` with each of the six proposed correlation keys | All six **accepted**; `message`, `asctime`, `args`, `name`, `levelname` raise `KeyError: Attempt to overwrite ... in LogRecord` | The key must be `message_id`, never `message` — the natural name is impossible → D-TG-24 |

⚠ **A trap inside probe 8, worth carrying into the test design.** The reserved-name `KeyError` is
raised by `Logger.makeRecord`, which a disabled call never reaches: with the logger below its
effective level, `log.info(..., extra={"message": "v"})` returns silently and the probe reports
"accepted". Written the obvious way, the probe measures the exact opposite of the truth. Any test of
FR-027 or FR-028 must set the logger's level, or it passes vacuously without ever building a record.

Then the full pipeline, end to end:

| Check | Result |
|---|---|
| Idempotence over 11 fixtures incl. empty, whitespace-only, emoji-only | **11/11** identical on the second pass |
| `متى تبدأ المحاضرة` written 4 ways (diacritics · tatweel · dialect spelling · plain) | collapse to **1** normalised form |
| `الدرس 3` / `الدرس ٣` / `الدرس ۳` | collapse to **1** form |
| `تمام` / `تمااااام` / `تمـــام` | collapse to **1** form |
| `الـ zoom link مش شغال STEP` | → `ال zoom link مش شغال STEP` — Latin and code-switching survive |
| `ابعت على 0555555555 او ahmed@x.com` | → digits and address intact, so the redactor can still see them |

**One of these changes the design rather than confirming it: probe 5 (D-TG-21).** It is a correction
to the source plan's §15.4 wording, which says "collapse whitespace and repeated characters"
without qualifying which characters.

**Two further findings that change *scope* rather than design**, both recorded in full below:
D-TG-25 (the existing secret scan already covers the `.env` case, so the new rule's real job is
narrower and different from what §19.3 implies) and D-TG-19 (the Telegram provider needs no new
dependency and no new quality-gate allowlist entry).

---

## 1. The domain boundary

### D-TG-17 — Four package areas mirroring the existing layering, no new layer

**Decision.** The moderation domain occupies four directories inside `apps/ai-api/app`, each a peer
of what already exists at that layer:

```
app/domain/moderation/          frozen dataclasses, zero deps, mypy strict
app/application/moderation/     text.py (normaliser + redactor) — mypy strict
app/providers/telegram/         skeleton only in TG-M0; the only place a Telegram call may live
app/workers/tasks/moderation/   skeleton only in TG-M0
```

Tests get one new top-level package, `apps/ai-api/tests/moderation/`, mirroring how
`tests/gateway/` was added for M1.

**Rationale.** The plan's §25 TG-M0 "Repo areas" row names exactly these. Reusing the existing four
layers rather than inventing a `app/moderation/` top-level tree means the mypy strict overrides
(`app.domain.*`, `app.application.*` in `pyproject.toml`) apply to moderation code automatically,
with no configuration change, and a reviewer reads moderation modules with the same layering
expectations as assessment ones.

**Alternatives rejected.** A single top-level `app/moderation/` package containing its own domain,
application and provider sub-layers — self-documenting, but it would sit outside both mypy strict
overrides and would make the "which layer is this?" question answerable two different ways in one
codebase. A separate installable package or service — the plan is explicit that infrastructure is
shared and only the *domain* is separate; a second service would need its own config, health, broker
and deployment for zero benefit.

### D-TG-18 — The forward boundary rule is an import **allowlist**, not a denylist

**Decision.** Two checks, added to `scripts/check.sh` next to the existing `httpx` rule.

**Forward** — a moderation module may import from `app.` only these, and nothing else:

```
app.domain.moderation      app.application.moderation
app.providers.telegram     app.workers.tasks.moderation
app.application.gateway    app.infrastructure     app.domain.model_profile
```

**Reverse** — no module under `app/domain/`, `app/application/`, `app/providers/` or `app/api/`,
outside the moderation and telegram subdirectories, may import anything matching
`app.*moderation*` or `app.providers.telegram`.

**Rationale.** There is no `app/assessment/` directory today — assessment code is simply the
un-namespaced modules (`app/application/gateway/`, `app/application/probes/`, `health_service.py`,
`app/domain/model_profile.py`). A denylist would therefore have to enumerate modules that mostly do
not exist yet, and would silently pass the day M2 adds `app/application/chunking/`. An allowlist
fails closed: anything new is a violation until someone deliberately widens the list, which is
exactly the review moment the boundary exists to create. The allowlist is also, verbatim, the source
plan's §6 sentence — "the only permitted shared imports are `app.application.gateway`,
`app.infrastructure.*`, and `app.domain.model_profile`" — plus the domain's own four areas.

**Composition roots are exempt from the reverse rule**: `app/main.py`, the TG-M1
`app/telegram_main.py`, `app/workers/main.py` and `app/scripts/`. These *must* import from both
domains — `app/workers/main.py` already imports `app.workers.tasks.diagnostics` purely to register
the actor. Wiring two domains together is what a composition root is for; forbidding it there would
make the application unrunnable. The exemption is by directory, so it is visible and finite.

**Measured** (probe 5a/5b, dry-run against the current tree): both rules produce zero output today,
so they are additive and cannot fail the gate on unmodified code.

**Alternatives rejected.** An import-graph tool (`import-linter`, `grimp`) — a new dev dependency,
a second configuration language, and a second place the rule lives, to enforce something a five-line
grep enforces; the repository already established the grep pattern in M1 and CLAUDE.md advertises it
as *the* architecture rule. Enforcement by code review alone — the plan's stated reason for TG-M0
existing is that convention does not survive ten milestones.

### D-TG-19 — The Telegram provider speaks HTTP through the existing `httpx`; no SDK

**Decision.** No `python-telegram-bot`, `aiogram`, `telethon` or `pyrogram` dependency is added,
now or in TG-M1. The provider will call the Bot API over `httpx`, which M0 already installs. A third
gate check forbids importing any of those libraries outside `app/providers/telegram/`.

**Rationale.** Two consequences, both measured. First, `app/providers/telegram/` sits *inside*
`apps/ai-api/app/providers/`, which the existing httpx rule already exempts — so the Telegram
provider needs **no new entry in the architecture allowlist**, and the milestone's rule set stays
three greps rather than three greps plus an exception. Second, the Bot API surface this domain uses
is small (`getUpdates`, `getMe`, `getChat`, `getChatMember`, `sendMessage`) and long-polling is a
loop around one endpoint; an SDK would bring its own event loop, its own retry policy and its own
update model, each of which would then need to be reconciled with the gateway's existing lane, retry
and error conventions. This is the same argument M1's D-24 made against the `openai` SDK, and it is
recorded here so TG-M1 does not have to re-litigate it.

The grep is therefore a **guard against a future dependency**, not a description of today's tree
(probe 5c: zero matches).

**Alternatives rejected.** `python-telegram-bot` — mature and well documented, but it owns the poll
loop, which is precisely the part D-TG-01 needs to control (single-consumer semantics, offset
commit ordering, gap detection). Adopting it would put the correctness-critical loop inside a
dependency.

---

## 2. Arabic text

### D-TG-20 — A fixed seven-step normalisation pipeline, in this order

**Decision.**

| # | Step | Why it is here, and why at this position |
|---|---|---|
| 1 | `unicodedata.normalize("NFKC", s)` | Folds ligatures, presentation forms and NBSP (**measured**, probe 3), and composes `ا`+combining-hamza into `أ` so step 5 sees one codepoint instead of two |
| 2 | Strip bidi/format marks — RLM, LRM, the isolates and the embedding controls, **and BOM** — but **never ZWJ U+200D** | NFKC leaves them (**measured**, probe 4); they are invisible and break literal matching. ZWJ is excluded because emoji sequences are built from it, and FR-019 requires emoji to survive |
| 3 | Remove tatweel `ـ` | NFKC leaves it (**measured**, probe 2). Before step 4 so a tatweel between a letter and its diacritic does not block the strip |
| 4 | Strip tashkeel and Quranic marks | After NFKC so that combining hamza/maddah have already composed into letters that step 5 folds, rather than being deleted as marks |
| 5 | Fold letter variants — `أ إ آ ٱ → ا`, `ة → ه`, `ى → ي` | The source plan's §15.4 list, unchanged |
| 6 | Fold Arabic-Indic and Eastern digits to ASCII | NFKC does **not** do this (**measured**, probe 1) |
| 7 | Collapse repeated **letters** (3+ → 1), then collapse whitespace runs to one space, then strip | See D-TG-21 for why "letters" and not "characters" |

`original_text` is never touched; the normalised form is a separate value.

**Rationale.** Each step is either required by §15.4 or required to make a later step correct. The
ordering was validated end to end: **11/11 fixtures idempotent**, and the three equivalence classes
in §0 each collapse to exactly one form.

**Alternatives rejected.** `NFD` + mark-category stripping — deletes the hamza that distinguishes
`أ` from `ا` *before* the fold decides what to do with it, giving the same answer here but by
accident rather than by rule, and it would silently mangle any future letter that must be preserved.
`camel-tools` or `pyarabic` — heavyweight NLP dependencies for what measured out as seven lines;
`camel-tools` also pulls a scientific stack this project does not otherwise carry. Waiting for the
assessment milestone's normaliser (M4) — the plan explicitly forbids blocking on it (§15.4), M4's is
designed for book prose, and TG-M3's rules ship first.

### D-TG-21 — ⚠ Repeated-character collapse applies to **letters only** *(corrects source plan §15.4)*

**Decision.** The collapse pattern is `([^\W\d_])\1{2,}` → `\1` — three or more of the same
**letter** become one. Digits, punctuation and emoji are never collapsed.

**Rationale — measured, probe 5.** The source plan says "collapse whitespace and repeated
characters (`تماااام → تمام`)". Applied literally, `(.)\1{2,}` turns the Saudi mobile number
`0555555555` into **`05`**. That is not a cosmetic bug:

- Normalisation runs **before** redaction (D-TG-22), so the redactor would then see `05` and find
  nothing to replace. The `«رقم»` placeholder never appears and a mangled fragment goes to the model
  instead — a silent failure of FR-022 that no test of the redactor alone would catch.
- It is *inconsistent*: `0501234567` has no three-in-a-row, survives collapse, and **is** redacted.
  So the same rule redacts one phone number and mangles another, which is the worst of both.
- The same applies to Arabic-Indic input: `٠٥٥٥٥٥٥٥٥٥` collapses to `٠٥` identically.

Restricting to letters fixes all three at once and, measured, costs nothing: `تمااااام → تمام` and
`شششكرا → شكرا` still work, `الله` (two adjacent lams, below the threshold) is untouched, and
`😂😂😂😂` survives — which FR-019 requires and a character-wise rule would have destroyed.

Threshold **3**, not 2, because genuine Arabic doubling is common and a 2+ rule would corrupt real
words. Idempotent by construction: the output of a 3+→1 collapse contains no run of 3.

**Alternatives rejected.** Redact first, then normalise — would mean the placeholders go through
NFKC and letter folding, and `«رقم»` would normalise to `«رقم»` harmlessly today but couples two
independent transforms; more importantly the plan is explicit that the classifier receives *redacted
normalized_text*, in that order. Collapsing everything and accepting the loss — over-collapsing
digits destroys signal *and* privacy protection simultaneously.

### D-TG-22 — Redaction: four patterns, one fixed order, idempotent by construction

**Decision.** Applied to the normalised text, in this order, with the source plan's Arabic
placeholders:

| Order | Pattern | Placeholder |
|---|---|---|
| 1 | URL — scheme-prefixed or `www.`-prefixed | `«رابط»` |
| 2 | Email address | `«بريد»` |
| 3 | `@handle` | `«مستخدم»` |
| 4 | Long digit run, optionally `+`-prefixed and containing spaces, hyphens or parentheses | `«رقم»` |

**Rationale.** The order is forced by containment, not preference: an email contains `@`, so the
handle rule must not run first; a URL may contain both `@` and a digit run, so it must run before
both. **Measured, probe 7**: `https://x.com/@someone` yields one `«رابط»` rather than a nested
substitution, and all 9 fixtures are byte-identical on a second pass.

Idempotence needs no guard code: none of the four placeholders matches any of the four patterns —
`«رقم»` contains no digits, `«رابط»` no scheme, `«مستخدم»` no `@`. That is a property worth stating
because it is what lets redaction be called defensively at more than one point later without
double-substituting.

**Accepted direction of error (FR-033).** The digit rule is length-based and *will* replace some
legitimate numbers — a long course code, an ID, a bank-transfer reference. Measured on the fixtures,
short numbers survive (`المحاضرة الساعة 7`, `الدورة تبدأ 2026 والمحاضرة 3` are untouched), so
ordinary lecture and year references are safe. Over-redaction is the correct direction for a privacy
control and is documented rather than tuned, because tuning it downward trades a certain privacy
guarantee for an uncertain recall gain.

**Alternatives rejected.** Named-entity recognition to catch personal names — needs a model, which is
what redaction exists to protect; and the design does not require it, because identity never reaches
the model as a *field* (D-TG-23), so a name surviving inside free text is a much smaller exposure
than shipping the sender record. Reversible tokenisation (`«رقم:a1b2»`) — creates a re-identification
map, which is a new PII store, to solve a problem this domain does not have.

### D-TG-23 — "Redacted before the gateway" is a structural guarantee stated as a contract now

**Decision.** `contracts/moderation-text.md` states the rule that the *only* text a moderation module
may pass toward the gateway is the output of `redact()`, and that no identity, chat or course
attribute may appear in a model request at all. TG-M0 ships the functions and the contract; TG-M5
ships the caller that obeys it.

**Rationale.** TG-M0 makes no model call, so there is no call site to test. Being honest about that
matters more than manufacturing a runtime check: a guard that inspects outgoing payloads for
un-redacted text would be an approximation of a property that is trivially true if the request
builder simply has no other input. Writing the contract in this milestone — the one that owns the
text pipeline — is what makes TG-M5's request builder a matter of following a written rule rather
than remembering a conversation. This mirrors `gateway-interface.md`'s role for M1: the durable
document later milestones code against.

The *ordering* claim ("before the gateway, not after") is the one with teeth today, and it is
already load-bearing: because `GATEWAY_CAPTURE_PAYLOADS` writes `request_payload` into `model_runs`,
redacting after the gateway would make that debug flag a privacy regression waiting to be toggled.
Redacting before it means the flag can be turned on safely, which is the source plan's §15.5
argument and is why the ordering is a contract clause rather than a code comment.

---

## 3. Configuration, secrets and logs

### D-TG-24 — The log whitelist is a `getattr` loop over a closed tuple

**Decision.** `JsonFormatter.format` gains:

```python
for key in _EXTRA_KEYS:                 # ("update_id","chat_id","message_id",
    value = getattr(record, key, None)  #  "incident_id","alert_id","actor")
    if value is not None:
        payload[key] = value
```

**Rationale.** This is a whitelist *by construction* rather than by filtering: an unlisted key has no
path into the payload, so no future edit to a call site can leak one. **Measured, probe 8**: all six
names are accepted by stdlib `extra=`; `message`, `asctime`, `args`, `name` and `levelname` raise
`KeyError: Attempt to overwrite ... in LogRecord`. That is why the key is `message_id` — the natural
name `message` is *impossible*, and discovering that at implementation time would have cost a
redesign of the key set. Note the trap recorded in section 0: the check lives in `Logger.makeRecord`,
so a log call below the effective level never reaches it — the tests for FR-027/FR-028 must set the
logger's level or they pass without ever building a record. The existing four output keys and every
existing call site are unchanged, which FR-029 requires.

**Alternatives rejected.** Diffing `record.__dict__` against a snapshot of standard `LogRecord`
attributes to find "the extras" and then filtering — the standard set varies by Python version and by
whether `exc_info`/`stack_info` are present, so the diff is a moving target and it fails *open*: a
new attribute name is emitted unless the filter knows to exclude it. A `logging.Filter` that mutates
records — same fail-open problem, one layer further from the output. A structured-logging dependency
(`structlog`) — a new runtime dependency, and it would replace a formatter the whole system already
shares for a six-key requirement.

### D-TG-25 — The token shape rule covers **prose files**, which the existing scan does not

**Decision.** Add `\d{8,10}:[A-Za-z0-9_-]{35}` to `scripts/scan_secrets.sh` as a **fixed-signature**
rule — the same tier as the AWS, GitHub and Slack patterns, applied to *every* tracked file — not as
another `KEY=value` heuristic.

**Rationale — measured, probe 4, and this narrows the milestone's scope.** The existing scan already
catches `TELEGRAM_BOT_TOKEN=<real value>`: its `KEY=value` rule matches any name ending `_TOKEN`, and
`CHANGE_ME_...` is on its safe list. So §19.3's framing ("`scan_secrets.sh` … TG-M0 adds the token's
shape") is true but understates what changes and overstates what was missing. The actual gap:

- that rule is restricted to **config-shaped files** (`.env*`, `.ya?ml`, `.sh`, `.php`, `.py`,
  `.ini`, `Makefile`) — deliberately, so narrative docs showing `SOME_KEY=example` are not flagged;
- so a token **pasted into a `.md` spec, runbook or commit message is invisible today** — which is
  exactly the risk §27 names ("Bot token leaked in a spec or log") and exactly the file type this
  track is generating a lot of.

Measured: the shape rule flags a bare token in prose (`the token looks like 8123456789:AAH…`) and
does **not** flag `CHANGE_ME_TELEGRAM_BOT_TOKEN`, an empty assignment, or a `12:34:56` timestamp.

One detail worth keeping: the *regex itself* — `\d{8,10}:[A-Za-z0-9_-]{35}` — does not match itself,
so this specification, the runbook and the contract can all document the token's shape in plain text
without tripping their own scanner. That was checked, not assumed.

⚠ **A sample token written out in full is a different matter, and this bit us.** The first draft of
`quickstart.md` §3 planted a literal `8123456789:AAH1…` (35 characters) in its worked example — a
tracked file, so check 5 would have failed the gate on the very document that specifies check 5. The
example now builds the value at runtime. **Any doc in this track that shows a sample token must build
it, truncate it below 35 characters after the colon, or show the regex instead.** A rule whose own
specification violates it gets disabled, not fixed.

**Alternatives rejected.** Widening the `KEY=value` rule to all file types — reintroduces exactly the
documentation false positives the `CONFIG_SHAPED` restriction was added to avoid. Entropy-based
detection — a generic answer to a specific question, and noisy against base64 fixtures.

### D-TG-26 — Five settings, the credential optional, validators in the established style

**Decision.** `Settings` gains, all optional with defaults:

| Field | Default | Validation |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `None` | none — carried, never validated here (D-TG-27) |
| `TELEGRAM_ALLOWED_UPDATES` | the update kinds this domain subscribes to | non-empty |
| `MODERATION_BURST_GAP_S` | `90` | must be positive |
| `MODERATION_ITEM_MAX_AGE_S` | `86400` | must be positive |
| `MODERATION_TEXT_RETENTION_DAYS` | `90` | must be positive |

Each validator is a `@model_validator(mode="after")` raising a `ValueError` naming the variable and
the offending value — the shape M1 already uses for `GATEWAY_CALL_TIMEOUT_S`, so `load_settings()`
prints `Configuration error: <FIELD>: <msg>` and exits 1 with no stack trace, unchanged.

**Rationale.** Absence of the credential is a *supported operating state*, not a degraded one: the
runbook forbids the dev and live tokens from coexisting on one machine, `make check` must pass with
none set, and the plan requires the health report to treat ingestion as informational. Typing the
field `str | None` with default `None` — rather than `str` with default `""` — makes "not
configured" and "configured as empty" the same state and makes every later `if settings.telegram_bot_token`
read correctly.

Rejecting zero and negative durations matters more than it looks: `MODERATION_TEXT_RETENTION_DAYS=0`
reaching TG-M10's purge job would delete every message text on the first run. Catching it at startup
is the difference between a config typo and data loss.

**Alternatives rejected.** A separate `ModerationSettings` class — the existing `Settings` is a flat,
single, well-understood object; splitting it would mean two load paths and two failure messages.
Making the credential required when a `TELEGRAM_ENABLED` flag is set — a second setting to express
what the credential's presence already expresses.

### D-TG-27 — The credential is carried, not validated, in TG-M0

**Decision.** No shape check, no `getMe` call, no format validator on `TELEGRAM_BOT_TOKEN` in this
milestone. Validation belongs to TG-M1's `make tg-doctor`.

**Rationale.** Nothing here contacts Telegram, so a malformed credential has no consequence yet.
Adding a shape validator now would fail startup for a value nothing uses — and, worse, would put the
token's regex into application code, where it becomes a second place the shape is defined and a
candidate for appearing in an error message. Keeping it out of the process entirely is the stronger
privacy position.

### D-TG-28 — The "no text in logs" gate rule guards the format-string path only

**Decision.** A grep over moderation modules that fails on a logging call whose line also references
a text-bearing name (`original_text`, `normalized_text`, `redacted_text`, `caption`, `message_text`),
plus a unit test asserting that `extra={"original_text": …}` produces output without it.

**Rationale — and an honest limit.** After D-TG-24 the formatter is the real guarantee: an unlisted
extra key has no path to the output, so the `extra=` route is closed structurally and the test proves
it. That leaves exactly one way text could still be logged — interpolating it into the message string
itself, `logger.info("got %s", text)` — and that is what the grep targets. The grep is line-based and
a sufficiently creative multi-line call would evade it; it is a second line of defence over a
structural guarantee, not the guarantee itself, and the contract says so rather than implying the
check is total.

**Alternatives rejected.** An AST-based lint rule — correct and complete, but a custom checker to
maintain for one rule whose primary enforcement is already structural. A runtime scrubber in the
formatter that regex-matches Arabic text in the message and redacts it — would silently corrupt
legitimate log messages and gives an illusion of safety that discourages the structural fix.

---

## 4. Testing

Following Principle I, tests here protect the text pipeline's correctness and idempotency, settings
validation, and the fact that each new gate rule actually fires. Package structure itself is not
tested — the gate proves it.

The Arabic fixtures are checked into `tests/moderation/fixtures/`. The set must include, at minimum,
the equivalence classes measured in §0 plus: an empty string, a whitespace-only string, an
emoji-only string, a string that is only a link, a mixed Arabic/Latin code-switched string, and a
message carrying each of the four redaction patterns. The operator supplies real dialect messages to
extend it (spec Dependencies) — without those the normaliser is validated for correctness but not
against the dialect-recall risk it exists to reduce, which is a limitation `quickstart.md` records.

**The three planted-violation tests are the milestone's acceptance evidence** (SC-002, SC-013) and
must not be skipped as "testing the build script": each proves a rule that ten later milestones lean
on, and a grep that matches nothing passes silently forever.

---

## 5. Out-of-scope observations (recorded, not built — Principle V)

1. **`json.dumps` escapes non-ASCII in the log formatter** (`ensure_ascii` defaults to true), so any
   Arabic in a log line is emitted as `\uXXXX`. Since this domain never logs message text, it costs
   nothing here. Changing it is an unrelated edit to shared infrastructure and is not made.
2. **The health report gains no moderation component in TG-M0.** The plan puts the
   `telegram_ingestion` block in TG-M1, where there is something to report. Adding an always-"not
   configured" component now would be noise.
3. **No Dramatiq retry policy is set**, still. The plan assigns it per-actor in TG-M5/TG-M7. TG-M0's
   `app/workers/tasks/moderation/` package is empty of actors, so there is nothing to configure.
4. **The `role='moderation'` widening of `model_profiles`** (D-TG-14) is TG-M5's, not this
   milestone's — TG-M0 has no migration at all, and revisions `0003`–`0009` stay reserved and unused.
5. **Alembic revision collision between the two tracks** is a live risk (§27). TG-M0 consumes no
   revision, so it neither creates nor resolves the risk; the rebase rule belongs in TG-M1's spec,
   which is where the first revision is written.
6. **`pg_dump` encryption** (§28 item 3) is strengthened as a case by this track but has no
   milestone. Flagged, not built.
