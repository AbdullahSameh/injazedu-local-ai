"""Tests for `normalize()` against contracts/moderation-text.md §2's worked-examples table.

FR-015-FR-020, SC-007, SC-008, SC-009.
"""

from __future__ import annotations

import pytest
from app.application.moderation.text import normalize

from tests.moderation.fixtures.arabic_messages import EDGE_CASES, EQUIVALENCE_CLASSES

# Measured, not illustrative (contracts/moderation-text.md §2).
WORKED_EXAMPLES: list[tuple[str, str]] = [
    ("مَتَى تَبْدَأُ المُحَاضَرَة؟", "متي تبدا المحاضره؟"),
    ("مـتـى تبدأ المحاضرة ٣", "متي تبدا المحاضره 3"),
    ("متى تبدا المحاضره 3", "متي تبدا المحاضره 3"),
    ("تمااااام شكراً 🙏🙏", "تمام شكرا 🙏🙏"),
    ("الـ zoom link مش شغال STEP", "ال zoom link مش شغال STEP"),
    ("ابعت على 0555555555 او ahmed@x.com", "ابعت علي 0555555555 او ahmed@x.com"),
    ("ﻻ ﺑﺄﺱ ﷺ", "لا باس صلي الله عليه وسلم"),
    ("😂😂😂😂", "😂😂😂😂"),
    ("", ""),
    ("   ", ""),
]


@pytest.mark.parametrize(("raw", "expected"), WORKED_EXAMPLES)
def test_worked_examples(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_bidi_marks_are_stripped() -> None:
    # RLM (U+200F) and LRM (U+200E) survive NFKC (measured, research.md §0 probe 4) and must be
    # stripped explicitly.
    raw = "‏متى‎  تبدأ   المحاضرة"
    assert normalize(raw) == "متي تبدا المحاضره"


@pytest.mark.parametrize(("expected", "variants"), EQUIVALENCE_CLASSES)
def test_equivalence_classes_collapse_to_one_form(expected: str, variants: list[str]) -> None:
    for variant in variants:
        assert normalize(variant) == expected


@pytest.mark.parametrize("raw", [v for _, variants in EQUIVALENCE_CLASSES for v in variants])
def test_idempotent_over_equivalence_classes(raw: str) -> None:
    once = normalize(raw)
    assert normalize(once) == once


@pytest.mark.parametrize("raw", EDGE_CASES)
def test_idempotent_over_edge_cases(raw: str) -> None:
    once = normalize(raw)
    assert normalize(once) == once


def test_input_is_never_mutated() -> None:
    raw = "مَتَى تَبْدَأُ المُحَاضَرَةُ"
    original = str(raw)
    normalize(raw)
    assert raw == original


def test_emoji_survives_including_repeats() -> None:
    assert normalize("😂😂😂😂") == "😂😂😂😂"


def test_latin_and_code_switching_survive() -> None:
    result = normalize("الـ zoom link مش شغال STEP")
    assert "zoom link" in result
    assert "STEP" in result


def test_digit_runs_survive_unaltered() -> None:
    # ⚠ D-TG-21 regression: a naive (.)\1{2,} collapse turns 0555555555 into 05, which would
    # then leave the redactor nothing to replace. The collapse must be letters-only.
    assert normalize("0555555555") == "0555555555"
    assert normalize("٠٥٥٥٥٥٥٥٥٥") == "0555555555"


def test_arabic_doubling_below_threshold_survives() -> None:
    # Collapse threshold is 3, not 2 — "الله" has two adjacent lams and must not be touched.
    assert normalize("الله") == "الله"
