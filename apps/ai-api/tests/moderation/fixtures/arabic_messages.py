"""Arabic fixture set for TG-M0's normalize() and redact() (US2, US3).

Sourced from research.md §0 (measured probes) and
specs/003-tg-m0-moderation-foundation/contracts/moderation-text.md's worked-examples
tables — not invented data.
"""

# Each group's variants must all collapse to the same `expected` normalised form
# (contracts/moderation-text.md §2, research.md §0).
EQUIVALENCE_CLASSES: list[tuple[str, list[str]]] = [
    (
        "متي تبدا المحاضره",
        [
            "متى تبدأ المحاضرة",
            "مَتَى تَبْدَأُ المُحَاضَرَةُ",
            "مـتـى تبـدأ المحاضـرة",
            "متى تبدا المحاضره",
        ],
    ),
    (
        "الدرس 3",
        [
            "الدرس 3",
            "الدرس ٣",
            "الدرس ۳",
        ],
    ),
    (
        "تمام",
        [
            "تمام",
            "تمااااام",
            "تمـــام",
        ],
    ),
]

# normalize() and redact() must return a defined result for each, never raise
# (spec.md → Edge Cases).
EDGE_CASES: list[str] = [
    "",
    "   ",
    "😂😂😂😂",
    "https://t.me/joinchat/AbCd?x=1",
    "الـ zoom link مش شغال STEP",
]

# One message per redact() pattern, in the fixed order the contract defines —
# URL, email, handle, digit run (contracts/moderation-text.md §3).
REDACTION_CASES: list[tuple[str, str]] = [
    ("الرابط https://t.me/joinchat/AbCd?x=1 اتفضل", "الرابط «رابط» اتفضل"),
    ("ابعت على ahmed.ali@example.com بسرعة", "ابعت على «بريد» بسرعة"),
    ("كلمني @InjazSupport لو سمحت", "كلمني «مستخدم» لو سمحت"),
    ("تواصل معي 0501234567 من فضلك", "تواصل معي «رقم» من فضلك"),
]
