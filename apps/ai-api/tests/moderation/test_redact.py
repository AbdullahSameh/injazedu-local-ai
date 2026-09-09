"""Tests for `redact()` against contracts/moderation-text.md §3's worked-examples table.

FR-022, FR-026, SC-010.
"""

from __future__ import annotations

import pytest
from app.application.moderation.text import redact

from tests.moderation.fixtures.arabic_messages import REDACTION_CASES

# Measured, not illustrative (contracts/moderation-text.md §3).
WORKED_EXAMPLES: list[tuple[str, str]] = [
    ("تواصل معي 0501234567 من فضلك", "تواصل معي «رقم» من فضلك"),
    ("رقمي +966 50 123 4567", "رقمي «رقم»"),
    ("ابعت على ahmed.ali@example.com بسرعة", "ابعت على «بريد» بسرعة"),
    ("الرابط https://t.me/joinchat/AbCd?x=1 اتفضل", "الرابط «رابط» اتفضل"),
    ("كلمني @InjazSupport او على www.injaz.sa", "كلمني «مستخدم» او على «رابط»"),
    ("https://x.com/@someone", "«رابط»"),
    ("الدورة تبدأ 2026 والمحاضرة 3", "الدورة تبدأ 2026 والمحاضرة 3"),
    ("المحاضرة الساعة 7", "المحاضرة الساعة 7"),
    ("لا يوجد شيء هنا", "لا يوجد شيء هنا"),
]


@pytest.mark.parametrize(("raw", "expected"), WORKED_EXAMPLES)
def test_worked_examples(raw: str, expected: str) -> None:
    assert redact(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), REDACTION_CASES)
def test_fixture_redaction_cases(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_url_containing_at_and_digits_yields_one_placeholder_not_nested() -> None:
    # https://x.com/@someone contains both "@" and could be mistaken for a handle or digit run —
    # the URL rule must consume it whole, first (D-TG-22).
    assert redact("https://x.com/@someone") == "«رابط»"


def test_idempotent() -> None:
    for raw, _ in WORKED_EXAMPLES + REDACTION_CASES:
        once = redact(raw)
        assert redact(once) == once


def test_no_op_on_clean_text() -> None:
    clean = "لا يوجد شيء هنا يستحق الإخفاء"
    assert redact(clean) == clean


def test_surrounding_text_untouched() -> None:
    result = redact("تواصل معي 0501234567 من فضلك")
    assert result.startswith("تواصل معي ")
    assert result.endswith(" من فضلك")


def test_short_numbers_survive() -> None:
    # A year and a lecture number are not "long" digit runs.
    assert redact("الدورة تبدأ 2026") == "الدورة تبدأ 2026"
    assert redact("المحاضرة 3") == "المحاضرة 3"
