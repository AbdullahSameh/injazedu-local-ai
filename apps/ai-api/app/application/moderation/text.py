"""The moderation text pipeline: `normalize` and `redact`.

Durable contract: `specs/003-tg-m0-moderation-foundation/contracts/moderation-text.md`. Pure
functions, no I/O, no dependency outside `re` and `unicodedata`. Neither raises. Neither logs.
Neither mutates its input. `normalized_text` is stored (TG-M1+), so the seven steps below are
fixed by the contract, not by configuration — see the contract §6 before changing any of them.
"""

from __future__ import annotations

import re
import unicodedata

# Step 2 preserves ZWJ — emoji sequences are built from it (FR-019).
_ZWJ = "‍"

# Step 3 — tatweel. NFKC does not remove it (measured, research.md §0 probe 2).
_TATWEEL = "ـ"

# Step 4 — tashkeel and Quranic annotation marks. Applied after NFKC so that a composed hamza/
# maddah has already folded onto its base letter (step 5) rather than being deleted here as a
# mark (research.md D-TG-20).
_TASHKEEL_RE = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭࣔ-࣡]")

# Step 5 — letter variants folded to one canonical form (contracts/moderation-text.md §2).
_LETTER_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
    }
)

# Step 6 — Arabic-Indic (U+0660-0669) and Eastern (U+06F0-06F9) digits folded to ASCII. NFKC does
# not do this (measured, research.md §0 probe 1).
_DIGIT_FOLD = str.maketrans(
    {chr(0x0660 + i): str(i) for i in range(10)} | {chr(0x06F0 + i): str(i) for i in range(10)}
)

# Step 7 — collapse 3+ of the same *letter* to one. Restricted to letters, not "any character":
# a naive (.)\1{2,} collapse turns the phone number 0555555555 into 05 (D-TG-21, measured probe
# 5). `[^\W\d_]` is "a word character that is neither a digit nor underscore" — i.e. a letter,
# Unicode-aware.
_LETTER_RUN_RE = re.compile(r"([^\W\d_])\1{2,}")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _strip_format_chars(text: str) -> str:
    """Removes Unicode format characters (category Cf) — bidi marks, embeddings, isolates, the
    BOM — except ZWJ, which emoji sequences need (contracts/moderation-text.md §2 step 2)."""
    return "".join(ch for ch in text if ch == _ZWJ or unicodedata.category(ch) != "Cf")


def normalize(text: str) -> str:
    """The seven-step Arabic normaliser (contracts/moderation-text.md §2).

    Idempotent, deterministic, non-destructive to `text`. Never raises.
    """
    step1 = unicodedata.normalize("NFKC", text)
    step2 = _strip_format_chars(step1)
    step3 = step2.replace(_TATWEEL, "")
    step4 = _TASHKEEL_RE.sub("", step3)
    step5 = step4.translate(_LETTER_FOLD)
    step6 = step5.translate(_DIGIT_FOLD)
    collapsed = _LETTER_RUN_RE.sub(r"\1", step6)
    return _WHITESPACE_RUN_RE.sub(" ", collapsed).strip()


# redact()'s four patterns, in the fixed order the containment argument forces: an email
# contains "@", so the handle rule must not precede it; a URL may contain both an "@" and a
# digit run, so it must precede both (contracts/moderation-text.md §3, D-TG-22).
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HANDLE_RE = re.compile(r"@[A-Za-z0-9_]{3,}")
# A "long" digit run: 7+ digits, optionally +-prefixed, tolerating internal spaces, hyphens and
# parentheses. The pattern always starts and ends on a digit — never on a separator — so a
# trailing space before the next word is never absorbed into the match.
_DIGIT_RUN_RE = re.compile(r"\+?\d(?:[\s()\-]*\d){6,}")

_URL_PLACEHOLDER = "«رابط»"
_EMAIL_PLACEHOLDER = "«بريد»"
_HANDLE_PLACEHOLDER = "«مستخدم»"
_DIGIT_PLACEHOLDER = "«رقم»"


def redact(text: str) -> str:
    """Replaces URLs, emails, handles and long digit runs with fixed Arabic placeholders
    (contracts/moderation-text.md §3). Applied to the output of `normalize`, never to
    `original_text`.

    Idempotent by construction — no placeholder matches any of the four patterns. Never raises.
    """
    result = _URL_RE.sub(_URL_PLACEHOLDER, text)
    result = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, result)
    result = _HANDLE_RE.sub(_HANDLE_PLACEHOLDER, result)
    return _DIGIT_RUN_RE.sub(_DIGIT_PLACEHOLDER, result)