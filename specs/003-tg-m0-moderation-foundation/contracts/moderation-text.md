# Contract: Moderation Text Pipeline

**Feature**: `specs/003-tg-m0-moderation-foundation/` · **Date**: 2026-09-09
**Status**: the durable contract of this milestone. TG-M3 codes its rules against §2; TG-M5 codes
its classifier against §3 and §4. Changing anything here after TG-M3 ships changes stored
`normalized_text` and therefore changes measured history — see §6.

Module: `apps/ai-api/app/application/moderation/text.py`. Pure functions, no I/O, no dependency
outside `re` and `unicodedata`, mypy strict.

---

## 1. Surface

```python
def normalize(text: str) -> str: ...
def redact(text: str) -> str: ...
```

Two free functions. No class, no configuration, no injected state — the transformations are fixed by
this contract, not by settings, so that a stored `normalized_text` means the same thing in TG-M3 and
in TG-M10.

Both accept any `str`, including empty and whitespace-only, and both return a `str`. Neither raises.
Neither logs. Neither touches its input.

---

## 2. `normalize` — the seven steps, in order

| # | Step | Detail |
|---|---|---|
| 1 | Unicode NFKC | Folds ligatures (`ﻻ`→`لا`), presentation forms (`ﺑ`→`ب`), NBSP→space, and composes combining hamza/maddah onto alef so step 5 sees one codepoint |
| 2 | Strip bidi and format marks | RLM, LRM, the directional isolates and embeddings, and the BOM. **ZWJ (U+200D) is explicitly preserved** — emoji sequences are built from it |
| 3 | Strip tatweel | `ـ` U+0640. NFKC does not remove it |
| 4 | Strip tashkeel and Quranic marks | The Arabic combining-mark ranges, after NFKC so composed letters survive as letters |
| 5 | Fold letter variants | `أ إ آ ٱ → ا` · `ة → ه` · `ى → ي` |
| 6 | Fold digits to ASCII | Arabic-Indic `٠-٩` (U+0660–0669) and Eastern `۰-۹` (U+06F0–06F9). NFKC does not do this |
| 7 | Collapse, then trim | Three or more of the same **letter** → one · runs of whitespace → one space · strip leading and trailing whitespace |

### Guarantees

| # | Guarantee | Why it matters downstream |
|---|---|---|
| N1 | **Idempotent** — `normalize(normalize(s)) == normalize(s)` | TG-M10's replay must converge byte-identically from the raw update log (D-TG-02) |
| N2 | **Deterministic** — no locale, no clock, no randomness | Two machines replaying the same updates must agree |
| N3 | **Non-destructive to the source** — the caller's string is never mutated | `original_text` is the evidence an operator sees in the panel |
| N4 | **Emoji preserved**, including ZWJ sequences and repeated emoji | Emoji are signal: a ✅ is how a moderator acknowledges (TG-M4) |
| N5 | **Latin script and code-switching preserved** — "STEP", "zoom link", `الـ link` | These are the groups that use them most; damaging them breaks TG-M3's recall exactly where it is already weakest |
| N6 | ⚠ **Digit runs are never collapsed** | Step 7 is letters-only. A character-wise collapse turns `0555555555` into `05`, and `redact` then has nothing to replace (D-TG-21) |

### Worked examples — measured, not illustrative

| Input | Output |
|---|---|
| `مَتَى تَبْدَأُ المُحَاضَرَة؟` | `متي تبدا المحاضره؟` |
| `مـتـى تبدأ المحاضرة ٣` | `متي تبدا المحاضره 3` |
| `متى تبدا المحاضره 3` | `متي تبدا المحاضره 3` |
| `تمااااام شكراً 🙏🙏` | `تمام شكرا 🙏🙏` |
| `الـ zoom link مش شغال STEP` | `ال zoom link مش شغال STEP` |
| `ابعت على 0555555555 او ahmed@x.com` | `ابعت علي 0555555555 او ahmed@x.com` |
| `‏متى‎  تبدأ   المحاضرة` (with RLM/LRM) | `متي تبدا المحاضره` |
| `ﻻ ﺑﺄﺱ ﷺ` | `لا باس صلي الله عليه وسلم` |
| `😂😂😂😂` | `😂😂😂😂` |
| `""` / `"   "` | `""` |

The first four rows of the following collapse to **one** form each — that is the property TG-M3's
rules depend on:

- `متى تبدأ المحاضرة` · `مَتَى تَبْدَأُ المُحَاضَرَةُ` · `مـتـى تبـدأ المحاضـرة` · `متى تبدا المحاضره`
- `الدرس 3` · `الدرس ٣` · `الدرس ۳`
- `تمام` · `تمااااام` · `تمـــام`

### Known behaviours, stated so they are not rediscovered as bugs

- **`ﷺ` (U+FDFA) expands to `صلى الله عليه وسلم`** — 18 characters from one. This is NFKC, it is
  correct, and it slightly helps rule matching.
- **`الـ` becomes `ال`** — a tatweel between the article and a Latin word leaves the article stranded.
  Harmless: the Latin word, which carries the meaning, survives.
- **Collapse threshold is 3, not 2.** Genuine Arabic doubling (`الله`) is common; a 2+ rule would
  corrupt real words.
- **Punctuation is not collapsed.** `؟؟؟؟` survives, which TG-M3 may want as a question signal.

---

## 3. `redact` — four patterns, one fixed order

Applied to the output of `normalize`, never to `original_text`.

| Order | Pattern | Placeholder |
|---|---|---|
| 1 | URL — `http://`, `https://`, or `www.`-prefixed | `«رابط»` |
| 2 | Email address | `«بريد»` |
| 3 | `@handle` | `«مستخدم»` |
| 4 | Long digit run, optionally `+`-prefixed, may contain spaces, hyphens, parentheses | `«رقم»` |

**The order is forced by containment, not preference.** An email contains `@`, so the handle rule
must not precede it. A URL may contain both an `@` and a digit run, so it must precede both.
Measured: `https://x.com/@someone` → a single `«رابط»`, not a nested substitution.

### Guarantees

| # | Guarantee |
|---|---|
| R1 | **Idempotent** — and by construction, not by a guard: no placeholder matches any of the four patterns. `«رقم»` has no digits, `«رابط»` no scheme, `«مستخدم»` no `@` |
| R2 | **Deterministic on overlap** — the fixed order above, always |
| R3 | **No-op on clean text** — a message with none of the four patterns is returned unchanged |
| R4 | **Surrounding text untouched** — Arabic and Latin either side of a replacement are unchanged |

### Worked examples — measured

| Input | Output |
|---|---|
| `تواصل معي 0501234567 من فضلك` | `تواصل معي «رقم» من فضلك` |
| `رقمي +966 50 123 4567` | `رقمي «رقم»` |
| `ابعت على ahmed.ali@example.com بسرعة` | `ابعت على «بريد» بسرعة` |
| `الرابط https://t.me/joinchat/AbCd?x=1 اتفضل` | `الرابط «رابط» اتفضل` |
| `كلمني @InjazSupport او على www.injaz.sa` | `كلمني «مستخدم» او على «رابط»` |
| `https://x.com/@someone` | `«رابط»` |
| `الدورة تبدأ 2026 والمحاضرة 3` | *(unchanged)* |
| `المحاضرة الساعة 7` | *(unchanged)* |
| `لا يوجد شيء هنا` | *(unchanged)* |

### Accepted direction of error

The digit rule is **length-based and will over-redact**. A long course code, a national ID, a
bank-transfer reference will each become `«رقم»`. Measured, short numbers are safe — years and
lecture numbers survive — so ordinary course talk is unaffected.

This is documented, not tuned. Tuning the threshold downward trades a certain privacy guarantee for
an uncertain recall gain, and the recall it would buy is on a signal (exact digit strings) that no
moderation rule in the plan uses.

**What redaction does not do:** it does not remove personal names written as free text. No pattern
can. The guarantee that identity does not reach the model comes from §4, not from §3.

---

## 4. The redact-before-gateway rule — for TG-M5

**TG-M0 ships the functions and this rule. TG-M5 ships the caller that obeys it.** There is no model
call in this milestone, so this section is a contract to code against, not a behaviour to test.

1. The **only** text a moderation module may pass toward the model gateway is the return value of
   `redact(normalize(original_text))`.
2. A model request carries **redacted text and instruction content only**. It must not carry a sender
   name, a handle, a Telegram user id, a chat id, a chat title, a course name, a moderator name, or
   any other identifying attribute — not in a field, not in a system prompt, not as context.
3. Redaction happens **before** the gateway call, never after.

**Why clause 3 is a contract clause and not a comment.** The gateway's `GATEWAY_CAPTURE_PAYLOADS`
debug flag writes `request_payload` into `model_runs`. If redaction happened after the gateway, that
flag would be a privacy regression waiting for someone to toggle it during an incident. Redacting
before means it can be switched on safely — which is the whole reason the ordering is fixed.

**Why there is no runtime guard.** A payload inspector searching outgoing requests for un-redacted
text would approximate a property that is trivially true if TG-M5's request builder has no other
input. The structural answer — one input, already redacted — is stronger than the check, and the
check would create false confidence in the paths it does not cover.

The classification input therefore has exactly two planes, and only the right-hand one moves:

```
Operational identity                      Classification input
─────────────────────                     ────────────────────
tg_user_id, username, display_name        redacted normalized text ONLY
chat title, course mapping         ──✗──▶ (no name, no id, no chat, no course)
moderator names, assignments
```

---

## 5. What this contract does not cover

- **Persistence.** `normalized_text` gets its column in TG-M1/TG-M2; `redacted_text` never gets one
  (`data-model.md` §2).
- **The taxonomy, the prompt and its versioning** — TG-M5.
- **Rule matching itself.** TG-M3 defines what a normalised string is matched *against*; this
  contract defines only what the string is.
- **Language detection.** The pipeline is Arabic-first and script-agnostic; it does not classify
  language and does not need to.

---

## 6. Changing this contract later

`normalized_text` is **stored**. Changing any step in §2 after TG-M1 ships means stored values no
longer equal `normalize(original_text)`, and rule matches computed before and after the change are
not comparable — which silently changes measured history, the thing this whole domain exists to
produce.

So a change to §2 requires: a new revision that re-derives `normalized_text` for every row still
inside the retention window, an explicit note that rows outside it cannot be re-derived, and the
diff-for-operator-approval treatment the source plan gives reclassification (D-TG-15). A change to
§3 is cheaper — `redacted_text` is never stored — but still changes what the model saw historically,
so it belongs with a `taxonomy_version` bump.

Adding a *new* pattern to §3 is always safe in the privacy direction and never safe in the
comparability direction. Treat it as a versioned change, not a bug fix.
