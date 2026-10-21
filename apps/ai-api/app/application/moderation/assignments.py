"""Ownership as history, held by a team (`specs/005…/contracts/moderator-ownership.md`, amended
by TG-M2.1's `specs/012-tg-m2-1-group-teams/contracts/group-teams.md` §1).

`team_at` (T3) reads the one definition of "on the team", the view `moderation_team_intervals`; the
Eloquent scope on `ModeratorGroupAssignment` reads the same view and must not drift. A group may
have several current members (T1); one moderator is current in a group at most once (T2).

- `open_assignment` adds a member or a backup (T4).
- `handover` replaces one member (T5): one transaction, close before open, one timestamp value
  bound to both sides.
- `end_assignment` ends one membership; `deactivate_moderator` ends all of a moderator's (T6).

SQL `now()` is `transaction_timestamp()`, identical across every statement in one transaction, so
every write here uses it directly on both sides rather than computing a value in Python and binding
it twice — the PHP-side hazard this module has no equivalent of.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.models_moderation import (
    moderation_team_intervals,
    moderator_group_assignments,
    moderators,
    telegram_chats,
)


class RepointConflictError(Exception):
    """The surviving chat row already has a current team (probe 8, `contracts/moderator-ownership
    .md` §6, `group-teams.md` T7): the re-point refuses rather than merging two teams and silently
    discarding an ownership fact."""


class MembershipRefusedError(ValueError):
    """A membership write the team contract refuses (`group-teams.md` T4-T5). `reason` is one of
    `inactive`, `overlap`, `future`, `before_declared`, `ambiguous` or `not_current`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def team_at(session: AsyncSession, *, telegram_chat_id: int, t: datetime) -> list[int]:
    """`team_at(chat, t)` (T3): every moderator whose membership covers `t` on this chat, or on the
    chat it migrated into, sorted by id.

    Half-open: `valid_from` included, `valid_to` excluded (O3). Returns `[]` — never today's team —
    when no interval covers `t` (O2). Never a backup (the view lists `primary` rows only).
    """
    result = await session.execute(
        sa.select(moderation_team_intervals.c.moderator_id)
        .where(
            moderation_team_intervals.c.telegram_chat_id == telegram_chat_id,
            moderation_team_intervals.c.valid_from <= t,
            sa.or_(
                moderation_team_intervals.c.valid_to.is_(None),
                moderation_team_intervals.c.valid_to > t,
            ),
        )
        .distinct()
        .order_by(moderation_team_intervals.c.moderator_id)
    )
    return [int(moderator_id) for moderator_id in result.scalars().all()]


async def _refuse_unless_openable(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    moderator_id: int,
    valid_from: datetime | None,
) -> None:
    """T4's refusals, inside the caller's transaction. An unknown moderator is left to the
    foreign key, which refuses it with the same rollback."""
    moderator = (
        await session.execute(
            sa.select(moderators.c.is_active, moderators.c.created_at).where(
                moderators.c.id == moderator_id
            )
        )
    ).one_or_none()
    if moderator is None:
        return
    if not moderator.is_active:
        raise MembershipRefusedError("inactive")

    if valid_from is not None:
        now = (await session.execute(sa.select(sa.func.now()))).scalar_one()
        if valid_from > now:
            raise MembershipRefusedError("future")
        if valid_from < moderator.created_at:
            raise MembershipRefusedError("before_declared")

    start = valid_from if valid_from is not None else sa.func.now()
    overlap = (
        await session.execute(
            sa.select(sa.literal(True))
            .select_from(moderator_group_assignments)
            .where(
                moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
                moderator_group_assignments.c.moderator_id == moderator_id,
                sa.or_(
                    moderator_group_assignments.c.valid_to.is_(None),
                    moderator_group_assignments.c.valid_to > start,
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if overlap is not None:
        raise MembershipRefusedError("overlap")


async def open_assignment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_chat_id: int,
    moderator_id: int,
    role: str = "primary",
    note: str | None = None,
    valid_from: datetime | None = None,
) -> int:
    """Adds a team member (`role='primary'`) or records a backup — `group-teams.md` T4. Nobody
    else's membership is touched: a group's team grows by one.

    `valid_from` defaults to the transaction's `now()`. A backdated start is an operator's
    correction, refused in the future and before the moderator was declared. Refused too for an
    inactive moderator, and when it would overlap that moderator's own interval in this group.

    One transaction. Returns the new row's id.
    """
    async with session_factory() as session:
        await _refuse_unless_openable(
            session,
            telegram_chat_id=telegram_chat_id,
            moderator_id=moderator_id,
            valid_from=valid_from,
        )
        result = await session.execute(
            moderator_group_assignments.insert()
            .values(
                telegram_chat_id=telegram_chat_id,
                moderator_id=moderator_id,
                assignment_role=role,
                valid_from=valid_from if valid_from is not None else sa.func.now(),
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
    replacing: int | None = None,
    note: str | None = None,
) -> int:
    """Replaces one team member (T5, §2, D-TG-47, Finding 2): close the incumbent, open the
    successor, one transaction, one timestamp value bound to both sides — never two clock
    readings, which is what leaves a hole that no constraint detects.

    `replacing` names the incumbent moderator. Left out, it means the group's sole current member
    (TG-M2's single-owner handover, unchanged), or nobody when the group has no team yet ("opening a
    first owner is the same protocol with the close affecting zero rows"). With several current
    members and no `replacing`, it refuses (`ambiguous`) rather than ending the whole team. Every
    other member is untouched (D-TG-209).
    """
    async with session_factory() as session:
        current = (
            await session.execute(
                sa.select(moderator_group_assignments.c.moderator_id).where(
                    moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
                    moderator_group_assignments.c.assignment_role == "primary",
                    moderator_group_assignments.c.valid_to.is_(None),
                )
            )
        ).scalars().all()
        if replacing is None:
            if len(current) > 1:
                raise MembershipRefusedError("ambiguous")
            incumbents = list(current)
        elif replacing in current:
            incumbents = [replacing]
        else:
            raise MembershipRefusedError("not_current")

        if incumbents:
            await session.execute(
                moderator_group_assignments.update()
                .where(
                    moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
                    moderator_group_assignments.c.moderator_id.in_(incumbents),
                    moderator_group_assignments.c.assignment_role == "primary",
                    moderator_group_assignments.c.valid_to.is_(None),
                )
                .values(valid_to=sa.func.now())
            )

        await _refuse_unless_openable(
            session, telegram_chat_id=telegram_chat_id, moderator_id=moderator_id, valid_from=None
        )
        result = await session.execute(
            moderator_group_assignments.insert()
            .values(
                telegram_chat_id=telegram_chat_id,
                moderator_id=moderator_id,
                assignment_role="primary",
                valid_from=sa.func.now(),
                note=note,
            )
            .returning(moderator_group_assignments.c.id)
        )
        new_id: int = result.scalar_one()
        await session.commit()
        return new_id


async def end_assignment(
    session_factory: async_sessionmaker[AsyncSession], *, assignment_id: int
) -> bool:
    """Ends one current membership at the transaction's `now()` (T5). Returns whether a current
    row was ended — an already-ended row is left exactly as it is."""
    async with session_factory() as session:
        result = await session.execute(
            moderator_group_assignments.update()
            .where(
                moderator_group_assignments.c.id == assignment_id,
                moderator_group_assignments.c.valid_to.is_(None),
            )
            .values(valid_to=sa.func.now())
        )
        await session.commit()
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        return rowcount == 1


async def deactivate_moderator(
    session_factory: async_sessionmaker[AsyncSession], *, moderator_id: int
) -> int:
    """T6: `is_active = false`, and every current membership of this moderator ends at the same
    `now()`, in one transaction — otherwise someone who left stays on "Team: …" and keeps collecting
    misses (D-TG-208). History is untouched. Returns how many memberships ended."""
    async with session_factory() as session:
        await session.execute(
            moderators.update()
            .where(moderators.c.id == moderator_id)
            .values(is_active=False, updated_at=sa.func.now())
        )
        result = await session.execute(
            moderator_group_assignments.update()
            .where(
                moderator_group_assignments.c.moderator_id == moderator_id,
                moderator_group_assignments.c.valid_to.is_(None),
            )
            .values(valid_to=sa.func.now())
        )
        await session.commit()
        ended: int = result.rowcount  # type: ignore[attr-defined]
        return ended


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
    the foreign key on each assignment row moves. Refuses with `RepointConflictError` (probe 8,
    T7) when the surviving row already has a current team member, rather than merging two teams
    and discarding an ownership fact — the caller surfaces that as a coverage problem for the
    operator to resolve.

    **Deliberately does not move `attention_items`** (TG-M3, FR-081, SC-022), unlike assignments.
    `attention_items` carries `fk_attention_message`, a *composite* FK on `(telegram_chat_id,
    telegram_message_id)` into `telegram_messages` — and `telegram_message_id` is Telegram's own
    per-chat counter, which restarts at 1 under the new supergroup id (research Finding 2,
    D-TG-71). Messages themselves are never re-pointed (`group_history_chat_ids`'s own docstring),
    so reassigning an item's `telegram_chat_id` alone would either violate that FK outright (the
    anchor message never existed under the surviving chat's own numbering) or, worse, silently
    resolve to a coincidentally-numbered but unrelated message there. An item's own row —
    `status`, every timing, its attribution — is never touched by a migration either way, which is
    what SC-022 actually requires: nothing here deletes or mutates an existing item. What an item
    "follows the surviving chat" means for *reading* a group's items across a promotion is a
    `group_history_chat_ids`-shaped concern for whichever screen needs it, not a stored column.

    `old_chat_id` / `new_chat_id` are the platform's own chat identifiers, matching
    `apply_chat_migration_if_any`'s parameters — not the surrogate `telegram_chats.id`.

    **Incidents, like items, are not re-pointed either** (TG-M4, D-TG-107): an incident anchors on
    the same composite `(telegram_chat_id, telegram_message_id)` FK as an item, for the same
    reason — `telegram_message_id` restarts at 1 under the new supergroup id — so
    `moderation_incident_evidence` follows the promotion one hop forward instead, at read time,
    rather than any row here moving.
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
                f"chat {new_chat_id} already has a current team"
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
