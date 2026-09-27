"""Policy incidents — pure domain rules (`data-model.md` §1, D-TG-101).

Pure: no I/O, no clock, no session, no import outside the standard library — exactly as
`app/domain/moderation/attention.py`. This is the second module of the moderation domain package.
Phase 3 (US1) uses these vocabularies to validate a panel-opened incident's labels; Phase 4 (US2)
adds the reaction delta and Phase 5 (US3) the membership classifier, both here, both pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# D-TG-08's taxonomy, spelled exactly — an operator's label and TG-M5's prediction compare
# without a mapping (D-TG-101).
CATEGORIES: tuple[str, ...] = ("SPAM_OR_AD", "ABUSE", "OTHER")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high")


def _reaction_identity(reaction: Mapping[str, object]) -> tuple[object, ...]:
    """A `ReactionType` object's identity (lifecycle contract V7): `(type, emoji)` for an
    emoji reaction, `(type, custom_emoji_id)` for a custom one, `(type,)` for `paid` — the
    platform allows only one `paid` reaction per user, so its type alone is unique."""
    kind = reaction.get("type")
    if kind == "emoji":
        return (kind, reaction.get("emoji"))
    if kind == "custom_emoji":
        return (kind, reaction.get("custom_emoji_id"))
    return (kind,)


def added_reactions(
    old: Sequence[Mapping[str, object]], new: Sequence[Mapping[str, object]]
) -> tuple[Mapping[str, object], ...]:
    """`new − old`, by reaction identity, order-insensitive (lifecycle contract V7, D-TG-110).
    A swap (an emoji removed and a different one added) yields the new one only; identical lists
    yield nothing; a pure removal yields nothing. Pure: no I/O, no clock."""
    old_identities = {_reaction_identity(reaction) for reaction in old}
    seen: set[tuple[object, ...]] = set()
    added: list[Mapping[str, object]] = []
    for reaction in new:
        identity = _reaction_identity(reaction)
        if identity in old_identities or identity in seen:
            continue
        seen.add(identity)
        added.append(reaction)
    return tuple(added)


def classify_membership_change(
    old: Mapping[str, object], new: Mapping[str, object], *, performed_by_subject: bool
) -> tuple[str, str | None] | None:
    """The membership classifier (lifecycle contract V1-V3, D-TG-108): a pure function over the
    old and new `ChatMember` shapes' `status` (and `old`'s `is_member`, which alone distinguishes
    the two `restricted -> left` rows) and whether the performer is the member themselves.

    Rows are evaluated top to bottom; the first match wins:

    | Old | New | Kind | Strength |
    |---|---|---|---|
    | any | `kicked` | `ban` | enforcement |
    | any | `restricted` | `restriction` | enforcement |
    | `member`/`administrator`/`restricted` (member) | `left` | `expulsion` | enforcement |
    | `kicked` | `left`/`member` | `reversal` | none |
    | `restricted` | `member` | `reversal` | none |
    | `restricted` (not a member) | `left` | `reversal` | none |
    | anything else — joins, promotions, demotions, `creator` changes | | *nothing* | |

    A change performed by the member themselves is never evidence (V2), checked first so it takes
    precedence even over an otherwise-matching row. Pure: no I/O, no clock.
    """
    if performed_by_subject:
        return None

    old_status = old.get("status")
    new_status = new.get("status")
    old_is_member = old.get("is_member", True)

    if new_status == "kicked":
        return ("ban", "enforcement")
    if new_status == "restricted":
        return ("restriction", "enforcement")
    if new_status == "left":
        if old_status in ("member", "administrator") or (
            old_status == "restricted" and old_is_member
        ):
            return ("expulsion", "enforcement")
        if old_status == "kicked" or (old_status == "restricted" and not old_is_member):
            return ("reversal", None)
        return None
    if new_status == "member":
        if old_status in ("kicked", "restricted"):
            return ("reversal", None)
        return None
    return None


def is_anonymous_performer(user: Mapping[str, object]) -> bool:
    """The platform's anonymous-administrator account (D-TG-109): a bot user named
    `GroupAnonymousBot`. The Bot API reference does not document this for membership changes
    (research probe 2), so callers should treat it as unverified live rather than asserted. Pure:
    no I/O, no clock."""
    return bool(user.get("is_bot")) and user.get("username") == "GroupAnonymousBot"
