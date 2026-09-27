"""`added_reactions` — the reaction-identity delta (T030, lifecycle contract V7, D-TG-110). Pure:
no database, no session — `new - old` by identity, order-insensitive.
"""

from __future__ import annotations

from app.domain.moderation.incident import added_reactions


def test_an_added_emoji_is_returned() -> None:
    added = added_reactions([], [{"type": "emoji", "emoji": "👍"}])
    assert added == ({"type": "emoji", "emoji": "👍"},)


def test_a_removed_emoji_yields_nothing() -> None:
    added = added_reactions([{"type": "emoji", "emoji": "👍"}], [])
    assert added == ()


def test_a_swap_yields_only_the_new_emoji() -> None:
    added = added_reactions(
        [{"type": "emoji", "emoji": "👍"}], [{"type": "emoji", "emoji": "❤️"}]
    )
    assert added == ({"type": "emoji", "emoji": "❤️"},)


def test_identical_lists_yield_nothing() -> None:
    old = [{"type": "emoji", "emoji": "👍"}]
    new = [{"type": "emoji", "emoji": "👍"}]
    assert added_reactions(old, new) == ()


def test_custom_emoji_reactions_compared_by_custom_emoji_id() -> None:
    old = [{"type": "custom_emoji", "custom_emoji_id": "111"}]
    new = [{"type": "custom_emoji", "custom_emoji_id": "222"}]
    assert added_reactions(old, new) == ({"type": "custom_emoji", "custom_emoji_id": "222"},)

    same = [{"type": "custom_emoji", "custom_emoji_id": "111"}]
    assert added_reactions(old, same) == ()


def test_paid_reactions_compared_by_identity() -> None:
    assert added_reactions([], [{"type": "paid"}]) == ({"type": "paid"},)
    assert added_reactions([{"type": "paid"}], [{"type": "paid"}]) == ()


def test_order_within_a_list_is_ignored() -> None:
    old = [{"type": "emoji", "emoji": "👍"}, {"type": "emoji", "emoji": "❤️"}]
    new = [{"type": "emoji", "emoji": "❤️"}, {"type": "emoji", "emoji": "👍"}]
    assert added_reactions(old, new) == ()


def test_a_new_reaction_alongside_an_unchanged_one_returns_only_the_new_one() -> None:
    old = [{"type": "emoji", "emoji": "👍"}]
    new = [{"type": "emoji", "emoji": "👍"}, {"type": "emoji", "emoji": "🔥"}]
    assert added_reactions(old, new) == ({"type": "emoji", "emoji": "🔥"},)
