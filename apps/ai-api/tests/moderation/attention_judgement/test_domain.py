"""The attention judgement's pure domain values (`data-model.md` §9;
`contracts/attention-judgement.md` §2, §4, §6; `tasks.md` T016). Every case is named and every
expectation is written out, never computed: these functions are the only definitions (N2), so a
test that re-derived them would be a second one.
"""

from __future__ import annotations

import pytest
from app.application.moderation.text import normalize
from app.domain.moderation.attention_judgement import (
    INTENTS,
    attention_exclusion,
    judgement_proposes,
    needs_response_for,
    vetoed,
)
from app.domain.moderation.classification import MessageFacts

_GROUP_CHAT_ID = -1_001_234_567_890


def _facts(**overrides: object) -> MessageFacts:
    """An eligible member's message whose own words open nothing; each case overrides one fact."""
    values: dict[str, object] = {
        "is_service": False,
        "media_kind": None,
        "text": normalize("حد خلص الواجب"),
        "text_removed": False,
        "is_from_moderator": False,
        "sender_chat_id": None,
        "group_chat_id": _GROUP_CHAT_ID,
        "is_automatic_forward": False,
    }
    values.update(overrides)
    return MessageFacts(**values)  # type: ignore[arg-type]


def test_intents_are_exactly_the_six() -> None:
    assert INTENTS == ("asking", "discussion", "informing", "social", "offering", "other")


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("asking", True),
        ("discussion", False),
        ("informing", False),
        ("social", False),
        ("offering", False),
        ("other", False),
    ],
)
def test_needs_response_is_true_only_for_asking(intent: str, expected: bool) -> None:
    assert needs_response_for(intent) is expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"text_removed": True, "text": None}, "text_removed", id="E1-text_removed"),
        pytest.param({"is_service": True}, "service", id="E2-service"),
        pytest.param({"media_kind": "photo"}, "media", id="E3-media"),
        pytest.param({"text": None}, "no_text", id="E4-no_text"),
        pytest.param({"is_from_moderator": True}, "moderator", id="E5-moderator"),
        pytest.param({"sender_chat_id": _GROUP_CHAT_ID}, "group_itself", id="E6-group_itself"),
        pytest.param({"is_automatic_forward": True}, "linked_channel", id="E7-linked_channel"),
        pytest.param({"text": normalize("شكرا")}, "acknowledgement", id="E8-acknowledgement"),
    ],
)
def test_ae1_returns_each_eligibility_reason(overrides: dict[str, object], expected: str) -> None:
    assert attention_exclusion(_facts(**overrides)) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(normalize("متى موعد الاختبار؟"), id="question-mark"),
        pytest.param(normalize("بس الرابط مش شغال"), id="question-pattern"),
    ],
)
def test_ae2_excludes_a_message_whose_own_words_open_the_rules(text: str) -> None:
    assert attention_exclusion(_facts(text=text)) == "rule_opens"


def test_a_message_whose_own_words_open_nothing_is_judged() -> None:
    assert attention_exclusion(_facts(text=normalize("حد خلص الواجب"))) is None


def test_an_acknowledgement_is_excluded_as_such_before_the_rule_skip() -> None:
    """E8 precedes AE2: an acknowledgement is reported as one, never as `rule_opens`."""
    assert attention_exclusion(_facts(text=normalize("شكرا"))) == "acknowledgement"


def test_an_ineligible_message_whose_words_would_open_reports_its_eligibility_reason() -> None:
    """AE1 precedes AE2: a moderator's question is excluded as `moderator`."""
    facts = _facts(is_from_moderator=True, text=normalize("متى موعد الاختبار؟"))
    assert attention_exclusion(facts) == "moderator"


@pytest.mark.parametrize(
    ("path", "needs_response", "expected"),
    [
        ("live", True, True),
        ("live", False, False),
        ("catch_up", True, False),
        ("catch_up", False, False),
    ],
)
def test_a_judgement_proposes_only_when_live_and_needing_a_response(
    path: str, needs_response: bool, expected: bool
) -> None:
    assert judgement_proposes(path=path, needs_response=needs_response) is expected


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("QUESTION_COURSE", False),
        ("QUESTION_ACCESS", False),
        ("COMPLAINT", False),
        ("CHITCHAT", False),
        ("SPAM_OR_AD", True),
        ("ABUSE", True),
        ("OTHER", False),
        # V: a member with no current classification is not vetoed — the judgements are
        # independent, and a missing classification is not evidence of an advert.
        (None, False),
    ],
)
def test_only_an_advert_or_abuse_vetoes(category: str | None, expected: bool) -> None:
    assert vetoed(category) is expected
