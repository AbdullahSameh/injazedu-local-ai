"""The rule set's self-check (T014, contract §2.1, research Finding 1, D-TG-74).

Seven of the source plan's own §13.1 entries do not survive `normalize()` and would match
nothing, ever, with no error, if stored in their unnormalised form. This test is the mechanism
that keeps that fixed for the entry somebody adds next year: every literal in `ACK_STOPLIST` and
`QUESTION_PATTERNS` must already be a fixed point of `normalize()`.
"""

from __future__ import annotations

import pytest
from app.application.moderation.text import normalize
from app.domain.moderation.attention import ACK_STOPLIST, QUESTION_PATTERNS


@pytest.mark.parametrize("literal", ACK_STOPLIST, ids=lambda s: f"ack:{s}")
def test_ack_stoplist_literals_are_already_normalised(literal: str) -> None:
    assert normalize(literal) == literal


@pytest.mark.parametrize("literal", QUESTION_PATTERNS, ids=lambda s: f"pattern:{s}")
def test_question_pattern_literals_are_already_normalised(literal: str) -> None:
    assert normalize(literal) == literal


def test_both_lists_total_forty_five_entries() -> None:
    assert len(ACK_STOPLIST) + len(QUESTION_PATTERNS) == 45


def test_neither_list_has_duplicates_under_normalisation() -> None:
    # Both lists deduplicate under normalisation (contract §2.1): `إيش`/`ايش` collapse to one
    # entry, as do `شكراً`/`شكرا`. Since the literals are stored already normalised, this is
    # simply "no two entries are byte-identical".
    assert len(set(ACK_STOPLIST)) == len(ACK_STOPLIST)
    assert len(set(QUESTION_PATTERNS)) == len(QUESTION_PATTERNS)
