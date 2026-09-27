"""`classify_membership_change` and `is_anonymous_performer` — the membership classifier (T037,
T038, lifecycle contract V1-V3, D-TG-108, D-TG-109). Pure: no database, no session, table-driven
over every row of the contract's table, evaluated top to bottom with the first match winning.

T038 is the **Finding 4** proof: no `chat_member` event has ever been captured in dev, so the
only evidence the Bot API 10.3 payload shape is read correctly is a full `ChatMemberUpdated`
dict, shaped exactly as the reference, fed through `evidence._classify_membership_update` — the
payload-reading wrapper — not only the bare classifier.
"""

from __future__ import annotations

import pytest
from app.application.moderation.evidence import _classify_membership_update
from app.domain.moderation.incident import classify_membership_change, is_anonymous_performer

# --- T037: the bare classifier, every row of lifecycle contract V3 plus the extra cases ---

# (old_status, old_is_member, new_status, performed_by_subject) -> expected (kind, strength) | None
_CASES: tuple[tuple[str, bool, str, bool, tuple[str, str | None] | None], ...] = (
    # V3 row 1: any -> kicked => ban, enforcement
    ("member", True, "kicked", False, ("ban", "enforcement")),
    ("administrator", True, "kicked", False, ("ban", "enforcement")),
    ("restricted", True, "kicked", False, ("ban", "enforcement")),
    ("restricted", False, "kicked", False, ("ban", "enforcement")),
    ("left", True, "kicked", False, ("ban", "enforcement")),  # extra: ban after leaving
    ("kicked", True, "kicked", False, ("ban", "enforcement")),
    # V3 row 2: any -> restricted => restriction, enforcement
    ("member", True, "restricted", False, ("restriction", "enforcement")),
    ("administrator", True, "restricted", False, ("restriction", "enforcement")),
    ("left", True, "restricted", False, ("restriction", "enforcement")),
    ("kicked", True, "restricted", False, ("restriction", "enforcement")),
    ("restricted", True, "restricted", False, ("restriction", "enforcement")),  # extra
    # V3 row 3: {member, administrator, restricted(is_member true)} -> left => expulsion
    ("member", True, "left", False, ("expulsion", "enforcement")),
    ("administrator", True, "left", False, ("expulsion", "enforcement")),
    ("restricted", True, "left", False, ("expulsion", "enforcement")),
    # V3 row 4: kicked -> {left, member} => reversal
    ("kicked", True, "left", False, ("reversal", None)),
    ("kicked", True, "member", False, ("reversal", None)),
    # V3 row 5: restricted -> member => reversal
    ("restricted", True, "member", False, ("reversal", None)),
    ("restricted", False, "member", False, ("reversal", None)),
    # V3 row 6: restricted (is_member false) -> left => reversal
    ("restricted", False, "left", False, ("reversal", None)),
    # V3 row 7 / "any other pair": joins, promotions, demotions, creator changes => nothing
    ("left", True, "member", False, None),  # extra: join
    ("member", True, "administrator", False, None),  # extra: promotion
    ("administrator", True, "member", False, None),  # extra: demotion
    ("member", True, "creator", False, None),
    ("creator", True, "member", False, None),
    ("administrator", True, "creator", False, None),
)


@pytest.mark.parametrize(
    ("old_status", "old_is_member", "new_status", "performed_by_subject", "expected"), _CASES
)
def test_classifier_table(
    old_status: str,
    old_is_member: bool,
    new_status: str,
    performed_by_subject: bool,
    expected: tuple[str, str | None] | None,
) -> None:
    old = {"status": old_status, "is_member": old_is_member}
    new = {"status": new_status, "is_member": new_status != "left" and new_status != "kicked"}
    result = classify_membership_change(old, new, performed_by_subject=performed_by_subject)
    assert result == expected


@pytest.mark.parametrize(
    ("old_status", "old_is_member", "new_status"),
    (
        ("member", True, "kicked"),
        ("member", True, "restricted"),
        ("member", True, "left"),
        ("kicked", True, "left"),
        ("restricted", True, "member"),
        ("restricted", False, "left"),
    ),
)
def test_performed_by_the_member_themselves_is_never_evidence(
    old_status: str, old_is_member: bool, new_status: str
) -> None:
    """V2: every pair, performed by the subject, yields nothing — checked before any row of the
    table, so it takes precedence even over an otherwise-matching ban or expulsion."""
    old = {"status": old_status, "is_member": old_is_member}
    new = {"status": new_status}
    assert classify_membership_change(old, new, performed_by_subject=True) is None


def test_first_match_wins_where_rows_overlap() -> None:
    """`restricted (is_member true) -> left` matches row 3 (expulsion) even though a naive reader
    might also reach for row 6 (`restricted (is_member false) -> left` => reversal); the two are
    disjoint by `is_member`, and only one row of V3 ever matches a given pair."""
    expulsion = classify_membership_change(
        {"status": "restricted", "is_member": True},
        {"status": "left"},
        performed_by_subject=False,
    )
    assert expulsion == ("expulsion", "enforcement")

    reversal = classify_membership_change(
        {"status": "restricted", "is_member": False},
        {"status": "left"},
        performed_by_subject=False,
    )
    assert reversal == ("reversal", None)


# --- is_anonymous_performer (D-TG-109) ---


def test_group_anonymous_bot_is_recognised_as_anonymous() -> None:
    user = {"id": 1087968824, "is_bot": True, "username": "GroupAnonymousBot"}
    assert is_anonymous_performer(user) is True


def test_a_bot_with_a_different_username_is_not_anonymous() -> None:
    user = {"id": 42, "is_bot": True, "username": "SomeOtherBot"}
    assert is_anonymous_performer(user) is False


def test_a_human_is_not_anonymous() -> None:
    user = {"id": 42, "is_bot": False, "username": "GroupAnonymousBot"}
    assert is_anonymous_performer(user) is False


# --- T038: the payload-reading wrapper, over a full ChatMemberUpdated dict (Finding 4) ---


def _chat_member_updated(
    *,
    performer_id: int,
    subject_id: int,
    old_status: str,
    new_status: str,
    old_is_member: bool = True,
    new_is_member: bool = True,
    until_date: int | None = None,
) -> dict[str, object]:
    """Shaped exactly as the Bot API 10.3 reference quoted in research Finding 4: `from`, `date`,
    `old_chat_member`, `new_chat_member` — each carrying `user`, `status`, `is_member`, and
    `new_chat_member` alone carrying `until_date`."""
    payload: dict[str, object] = {
        "chat": {"id": -1001234567890},
        "from": {"id": performer_id, "is_bot": False, "first_name": "Performer"},
        "date": 1_768_000_000,
        "old_chat_member": {
            "user": {"id": subject_id, "is_bot": False, "first_name": "Subject"},
            "status": old_status,
            "is_member": old_is_member,
        },
        "new_chat_member": {
            "user": {"id": subject_id, "is_bot": False, "first_name": "Subject"},
            "status": new_status,
            "is_member": new_is_member,
        },
    }
    if until_date is not None:
        payload["new_chat_member"]["until_date"] = until_date
    return payload


@pytest.mark.parametrize(
    ("old_status", "new_status", "old_is_member", "new_is_member", "expected"),
    (
        ("member", "kicked", True, False, ("ban", "enforcement")),
        ("member", "restricted", True, True, ("restriction", "enforcement")),
        ("member", "left", True, False, ("expulsion", "enforcement")),
        ("administrator", "left", True, False, ("expulsion", "enforcement")),
        ("restricted", "left", True, False, ("expulsion", "enforcement")),
        ("restricted", "left", False, False, ("reversal", None)),
        ("kicked", "left", True, False, ("reversal", None)),
        ("kicked", "member", True, True, ("reversal", None)),
        ("restricted", "member", True, True, ("reversal", None)),
        ("member", "administrator", True, True, None),
        ("administrator", "member", True, True, None),
    ),
)
def test_payload_wrapper_reads_the_reference_shape_correctly(
    old_status: str,
    new_status: str,
    old_is_member: bool,
    new_is_member: bool,
    expected: tuple[str, str | None] | None,
) -> None:
    body = _chat_member_updated(
        performer_id=111,
        subject_id=222,
        old_status=old_status,
        new_status=new_status,
        old_is_member=old_is_member,
        new_is_member=new_is_member,
        until_date=1_768_100_000 if new_status in ("kicked", "restricted") else None,
    )
    assert _classify_membership_update(body) == expected


def test_payload_wrapper_recognises_the_member_acting_on_themselves() -> None:
    body = _chat_member_updated(
        performer_id=222, subject_id=222, old_status="member", new_status="left"
    )
    assert _classify_membership_update(body) is None
