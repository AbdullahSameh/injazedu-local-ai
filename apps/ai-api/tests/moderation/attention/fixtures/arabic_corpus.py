"""Labelled Arabic fixture corpus for TG-M3's rule set v1
(`contracts/attention-rules.md` §2, T016).

Each entry is one message's text paired with the verdict `evaluate()` must return for a
single-message burst carrying it. Sourced from the contract's §2.1 literal lists, the dialect
forms and support phrasings named in `tasks.md` T005, and the token-boundary requirement (`من`
and `كم` are substrings of many words, not just the standalone question words). This is also
TG-M5's accuracy baseline (`contracts/attention-rules.md` §5).

`expected=True` means the rule set opens an item for that text alone; `expected=False` means it
declines. The label documents *why* — several entries look alike but decide differently once
`normalize()` and the stoplist/token-boundary rules apply.
"""

from __future__ import annotations

ARABIC_CORPUS: list[tuple[str, str, bool]] = [
    # --- Real questions, with `؟` ---
    ("question mark, standard form", "متى تبدأ المحاضرة؟", True),
    ("question mark, support phrasing", "ليش الفيديو مش شغال؟", True),
    ("question mark, English", "why is the app not working?", True),
    # --- Real questions, no trailing `؟` at all (R2 — most real questions carry none) ---
    ("no punctuation, وين", "وين الفصل التاني", True),
    ("no punctuation, ايش", "ايش السبب يا جماعة", True),
    ("no punctuation, ليش", "ليش ما وصلني رابط الزوم", True),
    ("no punctuation, ازاي", "ازاي احل الواجب ده", True),
    ("no punctuation, English how", "how do i submit the assignment", True),
    # --- Support phrasings (multi-word QUESTION_PATTERNS entries) ---
    ("support phrase, مش ظاهر", "الدرجات مش ظاهر عندي", True),
    ("support phrase, ما وصل", "التسجيل ما وصل لي لسه", True),
    ("support phrase, دفعت", "دفعت من امبارح والحساب لسه ماتفعلش", True),
    # --- Pure acknowledgement — the stoplist wins outright, before any question signal (R1) ---
    ("ack, شكرا", "شكرا", False),
    ("ack, تمام", "تمام", False),
    ("ack, جزاك الله خير", "جزاك الله خير", False),
    ("ack, تسلم", "تسلم", False),
    ("ack, ok", "ok", False),
    ("ack, okay", "okay", False),
    # --- Emoji-only and emoji runs (R5 — normalize() collapses repeated letters, not emoji) ---
    ("emoji, single thumbs up", "👍", False),
    ("emoji, run of four", "👍👍👍👍", False),
    ("emoji, heart", "❤️", False),
    ("emoji, rose", "🌹", False),
    # --- ≤2-character messages, regardless of content ---
    ("short, single char", "a", False),
    ("short, two chars", "لا", False),
    ("short, lone question mark", "؟", False),
    # --- Token-boundary requirement: `من`/`كم` embedded inside a longer word must not fire ---
    ("substring, من inside زمن", "زمن الاختبار قريب جدا", False),
    ("substring, كم inside حكم", "حكم القاضي غير عادل", False),
    # --- `من` as a standalone token: the accepted false-positive cost (contract §2.1, "remains
    #     in v1 deliberately") — it opens, and the accuracy figure (§5) is where that cost shows.
    ("token, من as bare preposition — known over-firing case", "الكتاب من المكتبة", True),
]
