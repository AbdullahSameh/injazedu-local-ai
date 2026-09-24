"""Rule set v1 — the burst's question/acknowledgement judgement
(`contracts/attention-rules.md` §2, tasks T024-T025).

Pure: no I/O, no clock, no session, no import outside the standard library. This is what makes
running the whole `arabic_corpus` fixture cheap enough to run on every change (`plan.md`'s
domain-purity rule). Callers resolve everything this module cannot see for itself — burst
membership, sender identity, service-message status, mention/reply targets — from stored facts,
and pass in already-normalised text plus two precomputed booleans.

**The literals are stored already normalised** (contract §2.1, research Finding 1, D-TG-74).
Seven of the source plan's own §13.1 entries never survive `normalize()` and would match
nothing, ever, with no error: the corrected forms are stored below instead of the originals.
`tests/moderation/attention/test_rule_literals.py` (T014) asserts `normalize(literal) == literal`
for every one of the 45 entries — the self-check is the fix, not the seven corrections.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# rule_version is stored on every item the rules open (contract R3, FR-012, D-TG-76). Changing
# any literal, any pattern or any condition bumps this — a figure produced under version 1 is
# never re-explained by version 2.
RULE_VERSION = 1

# Contract §2.1 (9 entries). Matched as a whole-message equivalence (after trimming edge
# punctuation), never as a substring — "thanks so much for everything" is not this list's
# concern.
ACK_STOPLIST: tuple[str, ...] = (
    'شكرا',
    'تمام',
    'تسلم',
    'جزاك الله خير',
    'ok',
    'okay',
    '👍',
    '❤️',
    '🌹',
)

# Contract §2.1 (36 entries: 30 Arabic + 6 English). Matched on token boundaries only — never
# as a bare substring: the two-letter Arabic interrogatives are also common substrings of longer
# words; substring matching would fire on nearly every message in the corpus (D-TG-74, D-TG-77,
# D-TG-78).
QUESTION_PATTERNS: tuple[str, ...] = (
    'متي',
    'اين',
    'وين',
    'كيف',
    'ازاي',
    'كيفيه',
    'ليش',
    'ليه',
    'لماذا',
    'هل',
    'ايش',
    'ايه',
    'مين',
    'من',
    'كم',
    'ممكن',
    'محتاج',
    'عايز',
    'ابغي',
    'ابي',
    'مشكله',
    'ما ظهر',
    'مش ظاهر',
    'لم تظهر',
    'ما يفتح',
    'مش شغال',
    'دفعت',
    'ما وصل',
    'لم يصل',
    'متاخر',
    'how',
    'when',
    'where',
    'why',
    'can i',
    'not working',
)

# R4: both survive NFKC unchanged (measured, not assumed).
_QUESTION_MARKS = ("\u061f", "?")

# Edge punctuation stripped before comparing a message's full text against ACK_STOPLIST — never
# applied to the QUESTION_PATTERNS token-boundary search, which looks anywhere in the text.
_ACK_EDGE_STRIP = " \t\n\u061f?!.,\u060c\u061b:\u00a1\u00bf"

# A conservative span of the common emoji blocks (pictographs, misc symbols, dingbats, regional
# indicators/flags), plus the two joiners a sequence needs (ZWJ, variation selector-16). Bare-
# emoji detection handles a *run* itself: normalize() collapses repeated letters but not repeated
# emoji (R5, measured), so this check does not care how many characters are present, only that
# every one of them is an emoji or a joiner.
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F1E6, 0x1F1FF),  # regional indicators (flags)
    (0x1F300, 0x1FAFF),  # misc pictographs, emoticons, transport, supplemental symbols
    (0x2190, 0x21FF),  # arrows
    (0x2600, 0x27BF),  # misc symbols + dingbats (covers the heart, U+2764)
    (0x2B00, 0x2BFF),  # misc symbols and arrows (stars, etc.)
)
_EMOJI_JOINERS = frozenset({0xFE0F, 0x200D})


def _token_pattern(literal: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(literal)}(?!\w)", re.UNICODE)


_ACK_TOKEN_PATTERNS = {literal: _token_pattern(literal.lower()) for literal in ACK_STOPLIST}
_QUESTION_TOKEN_PATTERNS = {
    literal: _token_pattern(literal.lower()) for literal in QUESTION_PATTERNS
}


def _is_emoji_char(ch: str) -> bool:
    code_point = ord(ch)
    if code_point in _EMOJI_JOINERS:
        return True
    return any(low <= code_point <= high for low, high in _EMOJI_RANGES)


def _is_bare_emoji(text: str) -> bool:
    """A run of one or more emoji and nothing else, ignoring whitespace (D-TG-78)."""
    stripped = text.replace(" ", "")
    return bool(stripped) and all(_is_emoji_char(ch) for ch in stripped)


def _matches_ack_stoplist(text: str) -> bool:
    """Whether one message, on its own, is the acknowledgement stoplist's territory: a bare
    emoji run, normalised length <= 2, or the whole message (edge punctuation aside) equals one
    of `ACK_STOPLIST`'s nine entries (D-TG-78)."""
    if len(text) <= 2:
        return True
    if _is_bare_emoji(text):
        return True
    bare = text.strip(_ACK_EDGE_STRIP).lower()
    return any(pattern.fullmatch(bare) for pattern in _ACK_TOKEN_PATTERNS.values())


def _has_question_mark(text: str) -> bool:
    return any(mark in text for mark in _QUESTION_MARKS)


def _matches_question_pattern(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.search(lowered) for pattern in _QUESTION_TOKEN_PATTERNS.values())


def evaluate(
    texts: Sequence[str | None],
    *,
    mentions_moderator: bool = False,
    replies_to_moderator: bool = False,
) -> bool:
    """Rule set v1 (contract §2.2): whether a burst carrying `texts` — one already-normalised
    string per member, in any order, `None` for a member with no text at all — opens an item.

    **R1**: the acknowledgement stoplist is evaluated first and wins outright, before any
    question signal — including `mentions_moderator` / `replies_to_moderator` — so a burst
    that is purely acknowledgement never opens, however it was addressed (contract §2.2
    condition 3, D-TG-75). `mentions_moderator` and `replies_to_moderator` are condition 6: both
    are resolved by the caller from stored facts this module has no session to look up itself
    (D-TG-77).
    """
    present_texts = [text for text in texts if text]

    if present_texts and all(_matches_ack_stoplist(text) for text in present_texts):
        return False

    if any(_has_question_mark(text) for text in present_texts):
        return True
    if any(_matches_question_pattern(text) for text in present_texts):
        return True

    return mentions_moderator or replies_to_moderator
