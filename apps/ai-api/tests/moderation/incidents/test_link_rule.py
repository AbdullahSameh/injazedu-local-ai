"""`link_rule_opens` — the no-links rule, pure (`docs/plan/telegram/tg-day-one-investigation-and-
link-rule-plan.md` Step 1). Table-driven over fixed, named cases: a regular member's message
carrying a Telegram `url`/`text_link` entity opens a rule incident; a declared moderator, the group
itself (an anonymous administrator) and the linked channel's automatic forward never do.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from app.domain.moderation.incident import LINK_RULE_VERSION, LinkRuleFacts, link_rule_opens

_GROUP = -1001234567890

_MEMBER_LINK = LinkRuleFacts(
    has_url=True,
    is_service=False,
    is_from_moderator=False,
    sender_chat_id=None,
    group_chat_id=_GROUP,
    is_automatic_forward=False,
)


def test_the_rule_is_versioned_from_one() -> None:
    assert LINK_RULE_VERSION == 1


@pytest.mark.parametrize(
    ("name", "facts", "expected"),
    [
        # A member's link opens — a person or a bot alike: neither is a declared moderator.
        ("member link", _MEMBER_LINK, True),
        # A member posting as another channel's identity is a member too (FR-003's reading).
        ("another channel's identity", replace(_MEMBER_LINK, sender_chat_id=-1009999), True),
        # Exempt: the people the group's rule allows to post links.
        ("declared moderator", replace(_MEMBER_LINK, is_from_moderator=True), False),
        ("anonymous administrator", replace(_MEMBER_LINK, sender_chat_id=_GROUP), False),
        ("linked channel", replace(_MEMBER_LINK, is_automatic_forward=True), False),
        # Nothing to judge.
        ("no link", replace(_MEMBER_LINK, has_url=False), False),
        ("service message", replace(_MEMBER_LINK, is_service=True), False),
    ],
)
def test_link_rule_opens(name: str, facts: LinkRuleFacts, expected: bool) -> None:
    assert link_rule_opens(facts) is expected, name
