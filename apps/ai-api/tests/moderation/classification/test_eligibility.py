"""Eligibility (E1-E8), pure (T019, `contracts/classification-pipeline.md` §3, FR-002..FR-004,
SC-016). Calls `eligibility()` directly — no session, no helper recomputes a reason.
"""

from __future__ import annotations

from app.domain.moderation.classification import MessageFacts, eligibility

_GROUP_CHAT_ID = -1001234567890


def _facts(**overrides: object) -> MessageFacts:
    base: dict[str, object] = {
        "is_service": False,
        "media_kind": None,
        "text": "hello",
        "text_removed": False,
        "is_from_moderator": False,
        "sender_chat_id": None,
        "group_chat_id": _GROUP_CHAT_ID,
        "is_automatic_forward": False,
    }
    base.update(overrides)
    return MessageFacts(**base)  # type: ignore[arg-type]


def test_eligible_message_returns_none() -> None:
    assert eligibility(_facts()) is None


def test_eligible_includes_a_bot_accounts_message() -> None:
    # A bot sender carries no special fact here — the bot/human distinction was already resolved
    # by message derivation (is_from_moderator is always false for a bot, FR-003).
    assert eligibility(_facts(is_from_moderator=False)) is None


def test_eligible_includes_another_channels_message() -> None:
    # sender_chat_id set, but not equal to this group's own id (E6 does not fire).
    assert eligibility(_facts(sender_chat_id=-1009999999999)) is None


def test_e1_text_removed() -> None:
    assert eligibility(_facts(text_removed=True)) == "text_removed"


def test_e2_service() -> None:
    assert eligibility(_facts(is_service=True)) == "service"


def test_e3_media() -> None:
    assert eligibility(_facts(media_kind="photo")) == "media"


def test_e4_no_text_when_none() -> None:
    assert eligibility(_facts(text=None)) == "no_text"


def test_e4_no_text_when_blank_after_normalisation() -> None:
    assert eligibility(_facts(text="   ")) == "no_text"


def test_e5_moderator() -> None:
    assert eligibility(_facts(is_from_moderator=True)) == "moderator"


def test_e6_group_itself_anonymous_administrator() -> None:
    assert eligibility(_facts(sender_chat_id=_GROUP_CHAT_ID)) == "group_itself"


def test_e7_linked_channel_automatic_forward() -> None:
    assert eligibility(_facts(is_automatic_forward=True)) == "linked_channel"


def test_e8_acknowledgement_bare_thanks() -> None:
    assert eligibility(_facts(text="شكرا")) == "acknowledgement"


def test_e8_acknowledgement_tamam() -> None:
    assert eligibility(_facts(text="تمام")) == "acknowledgement"


def test_e8_acknowledgement_emoji_only() -> None:
    assert eligibility(_facts(text="👍")) == "acknowledgement"


def test_precedence_text_removed_beats_service() -> None:
    assert eligibility(_facts(text_removed=True, is_service=True)) == "text_removed"


def test_precedence_service_beats_media() -> None:
    assert eligibility(_facts(is_service=True, media_kind="photo")) == "service"


def test_precedence_media_beats_no_text() -> None:
    assert eligibility(_facts(media_kind="photo", text=None)) == "media"


def test_precedence_no_text_beats_moderator() -> None:
    assert eligibility(_facts(text=None, is_from_moderator=True)) == "no_text"


def test_precedence_moderator_beats_group_itself() -> None:
    assert (
        eligibility(_facts(is_from_moderator=True, sender_chat_id=_GROUP_CHAT_ID)) == "moderator"
    )


def test_precedence_group_itself_beats_linked_channel() -> None:
    assert (
        eligibility(_facts(sender_chat_id=_GROUP_CHAT_ID, is_automatic_forward=True))
        == "group_itself"
    )


def test_precedence_linked_channel_beats_acknowledgement() -> None:
    assert eligibility(_facts(is_automatic_forward=True, text="شكرا")) == "linked_channel"
