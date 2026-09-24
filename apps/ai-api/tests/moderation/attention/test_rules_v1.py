"""Rule set v1 against the labelled Arabic fixture corpus (T016, contract §2.2).

Each `arabic_corpus` entry is one message's text and the verdict `evaluate()` must return for a
single-message burst carrying it — no sender, service or reply signal in play, since the corpus
varies only the text. Includes the token-boundary requirement: `من` and `كم` are substrings of
many words, and must not fire when embedded, only when they appear as their own token.
"""

from __future__ import annotations

import pytest
from app.application.moderation.text import normalize
from app.domain.moderation.attention import evaluate

from tests.moderation.attention.fixtures.arabic_corpus import ARABIC_CORPUS


@pytest.mark.parametrize(
    "label,text,expected", ARABIC_CORPUS, ids=[entry[0] for entry in ARABIC_CORPUS]
)
def test_rule_set_v1_matches_the_labelled_verdict(label: str, text: str, expected: bool) -> None:
    assert evaluate([normalize(text)]) is expected, label
