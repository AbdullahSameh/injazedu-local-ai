# Contract: The Domain Boundary and the Quality Gate

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09
**Status**: the rule ten later milestones lean on. Widening any list here is a deliberate,
reviewable act — that is the whole mechanism.

Everything below is enforced by `scripts/check.sh` and `scripts/scan_secrets.sh`, which `make check`
runs. All checks are static: no network, no database, no model runtime, no Telegram credential.

---

## 1. The boundary, stated

```
InjazEdu Local AI
├── Assessment Intelligence          existing — the un-namespaced modules
│     app/domain/model_profile.py · app/application/gateway/ · app/application/probes/
│     app/application/health_service.py · app/providers/{llm,embeddings}/ · app/api/
│
└── Moderation Intelligence          new — TG-M0 … TG-M10
      app/domain/moderation/ · app/application/moderation/
      app/providers/telegram/ · app/workers/tasks/moderation/
```

**No module in either domain may import the other.** The only shared dependencies are the model
gateway, the shared infrastructure, and the shared model-profile type.

Shared *deliberately*: the Postgres instance and schema, Redis, the Dramatiq broker, the model
gateway with its lane, breaker and accounting, `model_profiles` / `model_runs`, the Filament panel
shell, `.env` and `Settings`, `make check`, and the `_test` guard.

Not shared, and not to be reached for: pgvector, chunking, retrieval, `document_version_id` scoping,
prompt evidence and citation machinery, the human-approval-before-publish workflow (moderation has no
publish step), and the InjazEdu client (moderation needs nothing from InjazEdu in v1).

---

## 2. Check 1 — the forward rule (allowlist)

**Scope**: every `*.py` under `app/domain/moderation/`, `app/application/moderation/`,
`app/providers/telegram/`, `app/workers/tasks/moderation/`.

**Rule**: an `import app.X` or `from app.X import …` is permitted **only** when `app.X` starts with
one of:

```
app.domain.moderation        app.application.moderation
app.providers.telegram       app.workers.tasks.moderation
app.application.gateway      app.infrastructure        app.domain.model_profile
```

Anything else fails. Imports of the standard library and third-party packages are not this check's
business — the existing `httpx`/`ollama`/`openai` rule and check 3 cover those.

**Failure message**: names the file, the line, the offending import, and states that moderation
modules may import only the seven prefixes above.

**Why an allowlist.** There is no `app/assessment/` directory to deny — assessment code is simply the
un-namespaced modules. A denylist would have to enumerate modules that mostly do not exist yet, and
would pass silently the day M2 adds `app/application/chunking/`. The allowlist fails closed: anything
new is a violation until someone widens the list on purpose (D-TG-18).

**Widening it** is permitted but is a review event. Add the prefix, and add one line saying which
requirement made it necessary — the same discipline the existing `_ARCH_IMPORT_ALLOWLIST` uses for
its three entries.

---

## 3. Check 2 — the reverse rule

**Scope**: every `*.py` under `app/domain/`, `app/application/`, `app/providers/`, `app/api/`,
**excluding** the four moderation directories above.

**Rule**: no import matching `app.*moderation*` or `app.providers.telegram`.

**Failure message**: names the file and states that assessment-side modules may not import
moderation.

### Composition roots are exempt, by directory

`app/main.py` · `app/telegram_main.py` (TG-M1) · `app/workers/` · `app/scripts/`

These *must* import from both domains — `app/workers/main.py` already imports
`app.workers.tasks.diagnostics` purely to register the actor, and TG-M1's entrypoint will import the
moderation poller the same way. Wiring two domains together is what a composition root is for;
forbidding it there would make the application unrunnable.

The exemption is expressed as a directory scope rather than a file allowlist, so it is finite,
visible, and cannot grow by accident. Note that `app/workers/tasks/moderation/` is still governed by
check 1 — being under `app/workers/` exempts a module from the *reverse* rule only.

---

## 4. Check 3 — no Telegram SDK

**Scope**: every `*.py` under `app/`, excluding `app/providers/telegram/`.

**Rule**: no `import` or `from` of `telegram`, `aiogram`, `telebot`, `pyrogram`, `telethon`.

**Why this exists when no such dependency is installed.** It is a guard against a future one. The
Telegram provider will speak the Bot API over `httpx`, which M0 already installs (D-TG-19), and
because `app/providers/telegram/` sits *inside* `apps/ai-api/app/providers/`, the existing
`httpx`/`ollama`/`openai` rule already exempts it — **no new entry in `_ARCH_IMPORT_ALLOWLIST` is
needed**. Adding an SDK later would put the poll loop, its retry policy and its update model inside a
dependency, when single-consumer semantics, offset-commit ordering and gap detection are exactly what
this domain must control.

---

## 5. Check 4 — no message text in logs

**Scope**: the four moderation directories.

**Rule**: a logging call (`logger.debug|info|warning|error|exception|critical`) on a line that also
references `original_text`, `normalized_text`, `redacted_text`, `message_text` or `caption` fails.

**This check is a backstop, and the contract says so.** The real guarantee is structural: the
formatter reads only six named keys off the log record (§6), so nothing can reach the output through
`extra=`. That leaves exactly one route — interpolating text into the message string,
`logger.info("got %s", text)` — and this grep targets it. It is line-based; a sufficiently creative
multi-line call would evade it. Stating the limit is better than implying the check is total.

---

## 6. The log correlation whitelist

`JsonFormatter` emits, in addition to its existing `timestamp` / `level` / `logger` / `message` and
`exc_info`, exactly these keys when present and non-null:

```
update_id · chat_id · message_id · incident_id · alert_id · actor
```

Read by name off the record, so an unlisted key has **no path** to the output. Existing call sites
produce byte-identical lines.

⚠ **`message_id`, not `message`.** Measured: stdlib `logging` raises
`KeyError: Attempt to overwrite 'message' in LogRecord` for `extra={"message": …}`, and likewise for
`asctime`, `args`, `name`, `levelname`. All six keys above are accepted. The natural name was never
available.

⚠ **Testing note.** That `KeyError` is raised inside `Logger.makeRecord`, which a call below the
logger's effective level never reaches. A test that omits `setLevel` reports every key as accepted —
`message` included — and passes while proving nothing. Set the level.

---

## 7. Check 5 — the Telegram credential shape in the secret scan

**Scope**: **every** git-tracked file, in the same tier as the existing AWS, GitHub, Slack and
private-key signatures — *not* the `KEY=value` heuristic, which is restricted to config-shaped files.

**Rule**: a value matching `\d{8,10}:[A-Za-z0-9_-]{35}` fails, naming the file and line.

**What this actually adds, measured.** The existing `KEY=value` rule *already* catches
`TELEGRAM_BOT_TOKEN=<real value>` — it matches any name ending `_TOKEN`, and treats `CHANGE_ME…` as
safe. But it applies only to `.env*`, `.ya?ml`, `.sh`, `.php`, `.py`, `.ini` and `Makefile`,
deliberately, so that narrative docs showing `SOME_KEY=example` are not flagged. So the real gap is a
token **pasted into a `.md` spec, runbook or commit message** — which is the risk §27 names and the
file type this documentation-heavy track produces most of (D-TG-25).

Verified behaviour:

| Sample | Flagged |
|---|---|
| `TELEGRAM_BOT_TOKEN=8123456789:AAH1…` (35 chars) | yes |
| `the token looks like 8123456789:AAH1…` in a `.md` | **yes** — the case the old rule missed |
| `TELEGRAM_BOT_TOKEN=CHANGE_ME_TELEGRAM_BOT_TOKEN` | no |
| `TELEGRAM_BOT_TOKEN=` | no |
| `12:34:56 log line` | no |
| The regex `\d{8,10}:[A-Za-z0-9_-]{35}` written out in prose | **no** — it does not match itself |

That last row is why this contract, the spec and the runbook can all document the token's shape in
plain text. It was checked, not assumed.

⚠ **But a *sample* token written out in full is not safe, and the first draft of `quickstart.md`
contained one** — which would have failed this very check on a tracked file the moment it shipped.
Docs in this track must build a sample at runtime, truncate it below 35 characters after the colon,
or show the regex instead.

---

## 8. Operating notes for whoever implements these

- **`grep` exits 1 when it matches nothing**, and `check.sh` runs under `set -euo pipefail`. Use the
  existing `if grep …; then echo "violation" >&2; exit 1; fi` form, which is exempt from `set -e`,
  exactly as the current `httpx` check does. A bare `grep` would abort the gate on a *clean* tree.
- **A `grep -r` over a directory that does not exist** exits 2 with stderr noise. TG-M0 creates all
  four moderation directories with `__init__.py`, so this cannot happen — but the checks should not
  assume it, since a future refactor could remove one.
- **All three import checks are silent on today's tree** (dry-run, 2026-09-09). They are additive and
  cannot fail the gate on unmodified code.
- **Each check needs its own message.** Three rules collapsed into one grep produce one unhelpful
  error for three unrelated mistakes.

---

## 9. Acceptance

The milestone is accepted when, and only when:

| # | Planted violation | Expected |
|---|---|---|
| 1 | A moderation module importing `app.application.health_service` | gate fails, names the file, cites the forward rule |
| 2 | `app/application/health_service.py` importing `app.application.moderation.text` | gate fails, names the file, cites the reverse rule |
| 3 | `app/application/moderation/text.py` importing `telegram` | gate fails, names the file, cites the SDK rule |
| 4 | A moderation module logging `normalized_text` | gate fails, names the file |
| 5 | A token-shaped value in a tracked `.md` | secret scan fails, names file and line |
| 6 | The unmodified repository | gate **passes**, offline, with no credential and no model runtime |

Rows 1–5 are the evidence for SC-002, SC-006 and SC-013. Row 6 is the milestone's smoke test.
