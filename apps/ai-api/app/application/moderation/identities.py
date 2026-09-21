"""Sender identities — the single replay-safe upsert (`data-model.md` §1, D-TG-51).

Phase 3 (US1) adds `upsert_identity`, the one statement that resolves a captured sender into a
`telegram_users` row without ever letting a replayed, out-of-order observation move
`first_seen_at` forward, drag `last_seen_at` back, or clobber a current display name with a stale
one (Finding 4). Phase 5 (US3) adds placeholder creation for a moderator mapped before they have
ever posted.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.models_moderation import moderators, telegram_users


async def upsert_identity(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    display_name: str | None,
    is_bot: bool,
    observed_at: datetime,
) -> int:
    """Resolves one observed sender into `telegram_users`, replay-safe in all three directions
    (`data-model.md` §1, D-TG-51):

    - `first_seen_at` is `LEAST(stored, incoming)` — never moves forward; a genuinely older
      replayed observation may correctly move it back.
    - `last_seen_at` is `GREATEST(stored, incoming)` — never moves backwards, so an out-of-order
      replay cannot make a group read as having gone quiet.
    - `username`/`display_name` are written only when `observed_at` is not older than the stored
      `last_seen_at` — the guard that stops a re-derivation of older events from overwriting a
      current display name with a stale one.

    Takes an already-open session and does not commit — composed into the caller's transaction
    (`messages.derive_message` inserts the message in the same transaction as this upsert).
    Returns the surrogate `telegram_users.id`.
    """
    insert_stmt = pg_insert(telegram_users).values(
        tg_user_id=tg_user_id,
        username=username,
        display_name=display_name,
        is_bot=is_bot,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    excluded = insert_stmt.excluded
    stored_last_seen_at = sa.func.coalesce(telegram_users.c.last_seen_at, excluded.last_seen_at)
    is_not_older = excluded.last_seen_at >= stored_last_seen_at

    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[telegram_users.c.tg_user_id],
        set_={
            "first_seen_at": sa.func.least(
                sa.func.coalesce(telegram_users.c.first_seen_at, excluded.first_seen_at),
                excluded.first_seen_at,
            ),
            "last_seen_at": sa.func.greatest(stored_last_seen_at, excluded.last_seen_at),
            "username": sa.case((is_not_older, excluded.username), else_=telegram_users.c.username),
            "display_name": sa.case(
                (is_not_older, excluded.display_name), else_=telegram_users.c.display_name
            ),
            "is_bot": excluded.is_bot,
            "updated_at": sa.func.now(),
        },
    ).returning(telegram_users.c.id)

    result = await session.execute(stmt)
    surrogate_id: int = result.scalar_one()
    return surrogate_id


async def create_placeholder_identity(session: AsyncSession, *, tg_user_id: int) -> int:
    """Creates a placeholder `telegram_users` row for a moderator mapped before they have ever
    been observed (`data-model.md` §1, D-TG-52): `INSERT … ON CONFLICT (tg_user_id) DO NOTHING`,
    names NULL, `first_seen_at` NULL. The person's first real observation later fills it in
    through `upsert_identity`, creating no second row (FR-027, FR-028).

    Idempotent: if the identity already exists — observed or already a placeholder — it is left
    untouched and its existing surrogate id is returned.

    Takes an already-open session and does not commit — composed into the caller's transaction
    (`map_moderator` inserts the moderator row in the same transaction as this).
    """
    insert_stmt = (
        pg_insert(telegram_users)
        .values(tg_user_id=tg_user_id, is_bot=False)
        .on_conflict_do_nothing(index_elements=[telegram_users.c.tg_user_id])
        .returning(telegram_users.c.id)
    )
    result = await session.execute(insert_stmt)
    surrogate_id: int | None = result.scalar_one_or_none()
    if surrogate_id is not None:
        return surrogate_id

    result = await session.execute(
        sa.select(telegram_users.c.id).where(telegram_users.c.tg_user_id == tg_user_id)
    )
    existing_id: int = result.scalar_one()
    return existing_id


async def map_moderator(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tg_user_id: int,
    display_name: str,
    injaz_user_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Creates a moderator against an observed **or** placeholder identity in one transaction
    (FR-025…FR-027), so a numeric identifier for someone never yet observed and an
    already-observed sender share the one path. `create_placeholder_identity` resolves
    `tg_user_id` to a surrogate id — a no-op if the identity is already there — and the
    `moderators` row is inserted in the same transaction.

    Refuses (raises `IntegrityError`, `uq_moderators_telegram_user_id`) when the identity is
    already mapped to another moderator (FR-026).
    """
    async with session_factory() as session:
        identity_id = await create_placeholder_identity(session, tg_user_id=tg_user_id)
        result = await session.execute(
            moderators.insert()
            .values(
                telegram_user_id=identity_id,
                display_name=display_name,
                injaz_user_id=injaz_user_id,
                notes=notes,
            )
            .returning(moderators.c.id)
        )
        moderator_id: int = result.scalar_one()
        await session.commit()
        return moderator_id
