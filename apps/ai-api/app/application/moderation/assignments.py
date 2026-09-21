"""Ownership as history (`contracts/moderator-ownership.md`, `data-model.md` §4).

`responsible_at` (§3, D-TG-48) is the single Python definition of the half-open predicate; the
Eloquent scope on `ModeratorGroupAssignment` mirrors it and must not drift. `open_assignment` and
`handover` (§2, D-TG-47) implement the one handover protocol — one transaction, close before
open, one timestamp value bound to both sides. SQL `now()` is `transaction_timestamp()`, identical
across every statement in one transaction, so both functions use it directly on both sides rather
than computing a value in Python and binding it twice — the PHP-side hazard this module has no
equivalent of.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.models_moderation import moderator_group_assignments, telegram_chats


class RepointConflictError(Exception):
    """The surviving chat row already has a current primary assignment (probe 8,
    `contracts/moderator-ownership.md` §6): the re-point refuses rather than picking a winner and
    silently discarding an ownership fact."""


async def responsible_at(
    session: AsyncSession, *, telegram_chat_id: int, t: datetime
) -> int | None:
    """`responsible_at(chat, t)` (`data-model.md` §4.2, D-TG-48): the `moderator_id` of the
    `primary` assignment whose half-open interval `[valid_from, valid_to)` covers `t`.

    Returns `None` — never the current owner — when no interval covers `t` (O2). Never returns a
    backup (O4). Returns at most one row for any `chat`/`t` (O1), which `uq_assignment_one_current
    _primary` and the handover protocol below jointly guarantee.
    """
    result = await session.execute(
        sa.select(moderator_group_assignments.c.moderator_id).where(
            moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
            moderator_group_assignments.c.assignment_role == "primary",
            moderator_group_assignments.c.valid_from <= t,
            sa.or_(
                moderator_group_assignments.c.valid_to.is_(None),
                moderator_group_assignments.c.valid_to > t,
            ),
        )
    )
    return result.scalar_one_or_none()


async def open_assignment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_chat_id: int,
    moderator_id: int,
    role: str = "primary",
    note: str | None = None,
) -> int:
    """Opens a new assignment — `contracts/moderator-ownership.md` §2. For `role='primary'` this
    is the **same** close-before-open, one-timestamp protocol as `handover`, with the close
    naturally affecting zero rows when the chat has never had a primary: "opening a first owner
    is the same protocol with the close affecting zero rows." For `role='backup'` there is no
    exclusivity to close — `uq_assignment_one_current_primary` only constrains `primary` — so this
    is a plain insert.

    One transaction. Returns the new row's id.
    """
    async with session_factory() as session:
        if role == "primary":
            await session.execute(
                moderator_group_assignments.update()
                .where(
                    moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
                    moderator_group_assignments.c.assignment_role == "primary",
                    moderator_group_assignments.c.valid_to.is_(None),
                )
                .values(valid_to=sa.func.now())
            )

        result = await session.execute(
            moderator_group_assignments.insert()
            .values(
                telegram_chat_id=telegram_chat_id,
                moderator_id=moderator_id,
                assignment_role=role,
                valid_from=sa.func.now(),
                note=note,
            )
            .returning(moderator_group_assignments.c.id)
        )
        new_id: int = result.scalar_one()
        await session.commit()
        return new_id


async def handover(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_chat_id: int,
    moderator_id: int,
    note: str | None = None,
) -> int:
    """A change of primary owner (§2, D-TG-47, Finding 2): close the incumbent, open the
    successor, one transaction, one timestamp value bound to both sides — never two clock
    readings, which is what leaves a hole with zero owners that no constraint detects.

    `open_assignment(role='primary')` already **is** this protocol — its close step affects the
    incumbent's row instead of zero rows when one is current. Delegating keeps there being one
    implementation, not two that could silently drift (mirrors D-TG-49's insert-only rationale).
    """
    return await open_assignment(
        session_factory,
        telegram_chat_id=telegram_chat_id,
        moderator_id=moderator_id,
        role="primary",
        note=note,
    )


async def repoint_for_migration(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    old_chat_id: int,
    new_chat_id: int,
) -> None:
    """The chat-migration re-point (`data-model.md` §4.3, `contracts/moderator-ownership.md` §6,
    D-TG-54): moves a promoted group's ownership assignments from the superseded chat row to the
    surviving one, and carries `is_monitored` / `injaz_course_id` forward — Finding 3's fix, since
    TG-M1's `apply_chat_migration_if_any` creates the surviving row at the table's defaults
    (`is_monitored = false`), which would otherwise silently stop the group being measured at the
    moment it is promoted.

    A technical migration is **not** a handover: no interval is closed and none is opened, only
    the foreign key on each assignment row moves. Refuses with `RepointConflictError` (probe 8)
    when the surviving row already has a current primary, rather than picking a winner and
    discarding an ownership fact — the caller surfaces that as a coverage problem for the operator
    to resolve.

    `old_chat_id` / `new_chat_id` are the platform's own chat identifiers, matching
    `apply_chat_migration_if_any`'s parameters — not the surrogate `telegram_chats.id`.
    """
    async with session_factory() as session:
        old_row = (
            await session.execute(
                sa.select(
                    telegram_chats.c.id,
                    telegram_chats.c.is_monitored,
                    telegram_chats.c.injaz_course_id,
                ).where(telegram_chats.c.chat_id == old_chat_id)
            )
        ).one()
        new_pk: int = (
            await session.execute(
                sa.select(telegram_chats.c.id).where(telegram_chats.c.chat_id == new_chat_id)
            )
        ).scalar_one()

        conflict = (
            await session.execute(
                sa.select(sa.literal(True))
                .select_from(moderator_group_assignments)
                .where(
                    moderator_group_assignments.c.telegram_chat_id == new_pk,
                    moderator_group_assignments.c.assignment_role == "primary",
                    moderator_group_assignments.c.valid_to.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise RepointConflictError(
                f"chat {new_chat_id} already has a current primary assignment"
            )

        await session.execute(
            moderator_group_assignments.update()
            .where(moderator_group_assignments.c.telegram_chat_id == old_row.id)
            .values(telegram_chat_id=new_pk)
        )
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.id == new_pk)
            .values(
                is_monitored=old_row.is_monitored,
                injaz_course_id=old_row.injaz_course_id,
                updated_at=sa.func.now(),
            )
        )
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.id == old_row.id)
            .values(is_monitored=False, updated_at=sa.func.now())
        )
        await session.commit()
