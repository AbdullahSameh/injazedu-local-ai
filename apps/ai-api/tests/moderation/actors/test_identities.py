"""⚠ Replay-safety of the sender upsert (FR-015, SC-010, research Finding 4). Probe 5 showed the
obvious `ON CONFLICT DO UPDATE` fails all three of these silently: it clobbers a current display
name with a stale one, drags `last_seen_at` backwards (which a coverage read would misreport as a
group having gone quiet), and leaves `first_seen_at` unable to move at all.

Exercises `app.application.moderation.identities.upsert_identity` directly (implemented, T019) —
this file validates that implementation, not a future one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.moderation.identities import upsert_identity
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_replaying_an_older_observation_after_a_newer_one_does_not_clobber_the_name(
    actors_session_factory: async_sessionmaker[AsyncSession],
    fetch_user: Any,
) -> None:
    tg_user_id = 800_000_001
    newer_at = datetime.fromtimestamp(1_700_000_500, tz=UTC)
    older_at = datetime.fromtimestamp(1_700_000_000, tz=UTC)

    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="new_handle",
            display_name="New Name",
            is_bot=False,
            observed_at=newer_at,
        )
        await session.commit()

    # The replay: an older observation, applied after the newer one already landed.
    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="stale_handle",
            display_name="Stale Name",
            is_bot=False,
            observed_at=older_at,
        )
        await session.commit()

    row = await fetch_user(tg_user_id=tg_user_id)
    assert row is not None
    # Not overwritten by the older replay:
    assert row["display_name"] == "New Name"
    assert row["username"] == "new_handle"
    # last_seen_at never moves backwards:
    assert row["last_seen_at"] == newer_at
    # first_seen_at correctly moves back — a genuinely older observation is allowed to do this:
    assert row["first_seen_at"] == older_at


async def test_a_newer_observation_after_an_older_one_advances_last_seen_and_the_name(
    actors_session_factory: async_sessionmaker[AsyncSession],
    fetch_user: Any,
) -> None:
    tg_user_id = 800_000_002
    first_at = datetime.fromtimestamp(1_700_000_000, tz=UTC)
    second_at = datetime.fromtimestamp(1_700_000_500, tz=UTC)

    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="first_handle",
            display_name="First Name",
            is_bot=False,
            observed_at=first_at,
        )
        await session.commit()

    async with actors_session_factory() as session:
        await upsert_identity(
            session,
            tg_user_id=tg_user_id,
            username="second_handle",
            display_name="Second Name",
            is_bot=False,
            observed_at=second_at,
        )
        await session.commit()

    row = await fetch_user(tg_user_id=tg_user_id)
    assert row is not None
    assert row["display_name"] == "Second Name"
    assert row["username"] == "second_handle"
    assert row["last_seen_at"] == second_at
    assert row["first_seen_at"] == first_at
