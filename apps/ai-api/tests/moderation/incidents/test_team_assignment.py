"""First-action assignment and the team figures (TG-M2.1, `specs/012-tg-m2-1-group-teams/
contracts/group-teams.md` §2 G1-G7 and §4 F1-F4).

The assignee views (`attention_item_assignee`, `moderation_incident_assignee`) are read exactly as
the panel reads them; nothing here computes an assignment itself. Items and evidence are inserted
directly at fixed instants, so every ordering and boundary is exact rather than timing-dependent.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
import sqlalchemy as sa
from app.application.moderation.metrics import (
    attention_work_stats,
    incident_work_stats,
    unanswered_stats,
)
from app.infrastructure.models_moderation import (
    attention_item_assignee,
    moderation_incident_assignee,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_T0 = datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)
_PERIOD = (_T0 - timedelta(days=1), _T0 + timedelta(days=1))


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
def insert_item(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `attention_items` row directly, with whatever terminal fields the case needs."""

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        opened_at: datetime,
        status: str = "open",
        first_response_moderator_id: int | None = None,
        first_response_at: datetime | None = None,
        first_response_message_id: int | None = None,
        closed_at: datetime | None = None,
        closed_by_moderator_id: int | None = None,
    ) -> int:
        async with incident_session_factory() as session:
            item_id: int = (
                await session.execute(
                    sa.text(
                        """
                        INSERT INTO attention_items (
                            telegram_chat_id, telegram_message_id, opened_at, source, status,
                            first_response_moderator_id, first_response_at,
                            first_response_message_id, first_response_kind,
                            closed_at, closed_by_moderator_id
                        ) VALUES (
                            :chat, :message, :opened_at, 'operator', :status,
                            :frm, :fra, :frmsg, :kind,
                            :closed_at, :closed_by
                        ) RETURNING id
                        """
                    ),
                    {
                        "chat": telegram_chat_id,
                        "message": telegram_message_id,
                        "opened_at": opened_at,
                        "status": status,
                        "frm": first_response_moderator_id,
                        "fra": first_response_at,
                        "frmsg": first_response_message_id,
                        "closed_at": closed_at,
                        "closed_by": closed_by_moderator_id,
                        "kind": "direct_reply" if status == "answered" else None,
                    },
                )
            ).scalar_one()
            await session.commit()
            return item_id

    return _insert


@pytest_asyncio.fixture
def react(insert_action: Any, captured_update: Any):
    """A declared moderator's reaction on one message, at one instant."""

    async def _react(
        *, telegram_chat_id: int, target_message_id: int, moderator: dict[str, int], at: datetime
    ) -> int:
        update_id = await captured_update("message_reaction", {}, chat_id=None)
        action_id: int = await insert_action(
            telegram_chat_id=telegram_chat_id,
            action_type="reaction",
            action_strength="acknowledgement",
            occurred_at=at,
            actor_telegram_user_id=moderator["telegram_user_id"],
            actor_moderator_id=moderator["moderator_id"],
            target_message_id=target_message_id,
            source_update_id=update_id,
        )
        return action_id

    return _react


async def _item_assignee(
    session_factory: async_sessionmaker[AsyncSession], item_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        return dict(
            (
                await session.execute(
                    sa.select(attention_item_assignee).where(
                        attention_item_assignee.c.attention_item_id == item_id
                    )
                )
            )
            .mappings()
            .one()
        )


async def _incident_assignee(
    session_factory: async_sessionmaker[AsyncSession], incident_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        return dict(
            (
                await session.execute(
                    sa.select(moderation_incident_assignee).where(
                        moderation_incident_assignee.c.incident_id == incident_id
                    )
                )
            )
            .mappings()
            .one()
        )


async def _group(
    insert_chat: Any, insert_moderator: Any, insert_assignment: Any, names: tuple[str, ...]
) -> tuple[int, dict[str, dict[str, int]]]:
    """A monitored group whose team is `names`, every membership current since a day before _T0."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    team: dict[str, dict[str, int]] = {}
    for name in names:
        team[name] = await insert_moderator(display_name=name)
        await insert_assignment(
            telegram_chat_id=chat_pk,
            moderator_id=team[name]["moderator_id"],
            valid_from=_T0 - timedelta(days=1),
        )
    return chat_pk, team


# --- Attention items (G2, G4, G5) ---------------------------------------------------------------


async def test_a_new_item_is_assigned_to_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    chat_pk, _ = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=_T0)

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] is None
    assert assignee["assigned_via"] is None


async def test_a_team_members_reply_assigns_the_item(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    answered_at = _T0 + timedelta(minutes=3)
    await insert_message(telegram_chat_id=chat_pk, message_id=2, sent_at=answered_at)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="answered",
        first_response_moderator_id=team["A"]["moderator_id"],
        first_response_at=answered_at,
        first_response_message_id=2,
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] == team["A"]["moderator_id"]
    assert assignee["assigned_via"] == "reply"
    assert assignee["assigned_at"] == answered_at


async def test_a_linked_panel_dismissal_assigns_the_item(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="dismissed",
        closed_at=_T0 + timedelta(minutes=1),
        closed_by_moderator_id=team["A"]["moderator_id"],
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert (assignee["assigned_moderator_id"], assignee["assigned_via"]) == (
        team["A"]["moderator_id"],
        "dismissal",
    )


async def test_an_unlinked_operators_dismissal_assigns_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    """C2: an operator whose panel account is not a moderator closes the item as before (G7)."""
    chat_pk, _ = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="dismissed",
        closed_at=_T0 + timedelta(minutes=1),
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] is None


async def test_a_reaction_takes_an_open_item_without_closing_it(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=_T0)
    await react(
        telegram_chat_id=chat_pk,
        target_message_id=1,
        moderator=team["B"],
        at=_T0 + timedelta(seconds=30),
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert (assignee["assigned_moderator_id"], assignee["assigned_via"]) == (
        team["B"]["moderator_id"],
        "reaction",
    )


async def test_a_reaction_on_a_burst_member_takes_the_item(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=_T0 + timedelta(seconds=10)
    )
    item_id = await insert_item(telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=_T0)
    async with incident_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE telegram_messages SET attention_item_id = :item "
                "WHERE telegram_chat_id = :chat AND message_id = 2"
            ),
            {"item": item_id, "chat": chat_pk},
        )
        await session.commit()
    await react(
        telegram_chat_id=chat_pk,
        target_message_id=2,
        moderator=team["A"],
        at=_T0 + timedelta(minutes=1),
    )

    assert (await _item_assignee(incident_session_factory, item_id))[
        "assigned_moderator_id"
    ] == team["A"]["moderator_id"]


async def test_the_first_act_wins_and_a_later_answer_by_a_colleague_does_not_move_it(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    """The quickstart's smoke: B reacts 👀, A answers — assigned to B, answered by A."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    answered_at = _T0 + timedelta(minutes=5)
    await insert_message(telegram_chat_id=chat_pk, message_id=2, sent_at=answered_at)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="answered",
        first_response_moderator_id=team["A"]["moderator_id"],
        first_response_at=answered_at,
        first_response_message_id=2,
    )
    await react(
        telegram_chat_id=chat_pk,
        target_message_id=1,
        moderator=team["B"],
        at=_T0 + timedelta(minutes=1),
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert (assignee["assigned_moderator_id"], assignee["assigned_via"]) == (
        team["B"]["moderator_id"],
        "reaction",
    )


async def test_a_reply_beats_a_reaction_at_the_same_instant(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    """G5's attention tie-break: instant, then reply before dismissal before reaction."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    at = _T0 + timedelta(minutes=2)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    await insert_message(telegram_chat_id=chat_pk, message_id=2, sent_at=at)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="answered",
        first_response_moderator_id=team["A"]["moderator_id"],
        first_response_at=at,
        first_response_message_id=2,
    )
    await react(telegram_chat_id=chat_pk, target_message_id=1, moderator=team["B"], at=at)

    assert (await _item_assignee(incident_session_factory, item_id))[
        "assigned_moderator_id"
    ] == team["A"]["moderator_id"]


async def test_an_outsiders_answer_closes_the_item_but_assigns_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    chat_pk, _ = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    outsider = await insert_moderator(display_name="Outsider")
    answered_at = _T0 + timedelta(minutes=3)
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    await insert_message(telegram_chat_id=chat_pk, message_id=2, sent_at=answered_at)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="answered",
        first_response_moderator_id=outsider["moderator_id"],
        first_response_at=answered_at,
        first_response_message_id=2,
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] is None


async def test_a_reaction_after_the_item_expired_assigns_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    """G4 / D-TG-204: a late 👀 cannot erase the team's miss."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    expired_at = _T0 + timedelta(hours=24)
    item_id = await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="expired",
        closed_at=expired_at,
    )
    await react(
        telegram_chat_id=chat_pk,
        target_message_id=1,
        moderator=team["A"],
        at=expired_at + timedelta(minutes=1),
    )

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] is None


async def test_a_moderator_added_after_the_act_was_not_on_the_team(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    late = await insert_moderator(display_name="Late")
    acted_at = _T0 + timedelta(minutes=1)
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=late["moderator_id"],
        valid_from=acted_at + timedelta(seconds=1),
    )
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=_T0)
    await react(telegram_chat_id=chat_pk, target_message_id=1, moderator=late, at=acted_at)

    assignee = await _item_assignee(incident_session_factory, item_id)
    assert assignee["assigned_moderator_id"] is None


async def test_an_item_on_a_migrated_chat_is_judged_against_its_successors_team(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    """T3: memberships moved to the surviving chat; the item stayed on the superseded one."""
    new_chat_id = -_rand_id()
    old_pk = await insert_chat(chat_id=-_rand_id(), migrated_to_chat_id=new_chat_id)
    new_pk = await insert_chat(chat_id=new_chat_id)
    member = await insert_moderator(display_name="Member")
    await insert_assignment(
        telegram_chat_id=new_pk,
        moderator_id=member["moderator_id"],
        valid_from=_T0 - timedelta(days=1),
    )
    await insert_message(telegram_chat_id=old_pk, message_id=1, sent_at=_T0)
    item_id = await insert_item(telegram_chat_id=old_pk, telegram_message_id=1, opened_at=_T0)
    await react(
        telegram_chat_id=old_pk,
        target_message_id=1,
        moderator=member,
        at=_T0 + timedelta(minutes=1),
    )

    assert (await _item_assignee(incident_session_factory, item_id))[
        "assigned_moderator_id"
    ] == member["moderator_id"]


# --- Incidents (G3, G4, G5) ---------------------------------------------------------------------


async def _incident(insert_message: Any, insert_incident: Any, *, chat_pk: int) -> int:
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    incident_id: int = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        detected_at=_T0 + timedelta(seconds=10),
        category="SPAM_OR_AD",
        severity="low",
    )
    return incident_id


async def test_a_linked_panel_acknowledgement_assigns_the_incident(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    incident_id = await _incident(insert_message, insert_incident, chat_pk=chat_pk)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_acknowledge",
        action_strength="acknowledgement",
        occurred_at=_T0 + timedelta(minutes=1),
        panel_user_id=7,
        actor_moderator_id=team["A"]["moderator_id"],
        moderation_incident_id=incident_id,
    )

    assignee = await _incident_assignee(incident_session_factory, incident_id)
    assert (assignee["assigned_moderator_id"], assignee["assigned_via"]) == (
        team["A"]["moderator_id"],
        "panel_acknowledge",
    )


async def test_an_outsiders_ban_assigns_nobody_and_a_later_act_comes_too_late(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    insert_user: Any,
    captured_update: Any,
    react: Any,
) -> None:
    """G4: the outsider's ban resolves the incident; a team member's reaction after it lands
    after the end, so the incident stays unassigned."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    outsider = await insert_moderator(display_name="Outsider")
    incident_id = await _incident(insert_message, insert_incident, chat_pk=chat_pk)
    async with incident_session_factory() as session:
        sender = (
            await session.execute(
                sa.text(
                    "SELECT telegram_user_id FROM telegram_messages "
                    "WHERE telegram_chat_id = :c AND message_id = 1"
                ),
                {"c": chat_pk},
            )
        ).scalar_one()
    if sender is None:
        sender = await insert_user(tg_user_id=_rand_id())
        async with incident_session_factory() as session:
            await session.execute(
                sa.text(
                    "UPDATE telegram_messages SET telegram_user_id = :u "
                    "WHERE telegram_chat_id = :c AND message_id = 1"
                ),
                {"u": sender, "c": chat_pk},
            )
            await session.commit()
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=_T0 + timedelta(minutes=1),
        actor_telegram_user_id=outsider["telegram_user_id"],
        actor_moderator_id=outsider["moderator_id"],
        subject_telegram_user_id=sender,
        source_update_id=await captured_update("chat_member", {}, chat_id=None),
    )
    await react(
        telegram_chat_id=chat_pk,
        target_message_id=1,
        moderator=team["A"],
        at=_T0 + timedelta(minutes=2),
    )

    assert (await _incident_assignee(incident_session_factory, incident_id))[
        "assigned_moderator_id"
    ] is None


async def test_a_reversal_assigns_nobody(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    insert_user: Any,
    captured_update: Any,
) -> None:
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    sender = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=_T0, telegram_user_id=sender
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        detected_at=_T0 + timedelta(seconds=10),
        category="SPAM_OR_AD",
        severity="low",
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reversal",
        occurred_at=_T0 + timedelta(minutes=1),
        actor_telegram_user_id=team["A"]["telegram_user_id"],
        actor_moderator_id=team["A"]["moderator_id"],
        subject_telegram_user_id=sender,
        source_update_id=await captured_update("chat_member", {}, chat_id=None),
    )

    assert (await _incident_assignee(incident_session_factory, incident_id))[
        "assigned_moderator_id"
    ] is None


# --- Figures (F1-F4) ----------------------------------------------------------------------------


async def test_a_miss_counts_once_for_each_member_and_once_for_the_group(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
) -> None:
    """F2 / D4: never zero, never three times."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_T0)
    await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="expired",
        closed_at=_T0 + timedelta(hours=24),
    )

    async with incident_session_factory() as session:
        by_member = [
            await unanswered_stats(
                session,
                period_from=_PERIOD[0],
                period_to=_PERIOD[1],
                moderator_id=team[name]["moderator_id"],
            )
            for name in ("A", "B")
        ]
        by_group = await unanswered_stats(
            session, period_from=_PERIOD[0], period_to=_PERIOD[1], chat_id=chat_pk
        )

    assert [stats["unanswered"] for stats in by_member] == [1, 1]
    assert by_group["unanswered"] == 1


async def test_my_work_splits_what_i_took_from_what_i_answered(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_item: Any,
    react: Any,
) -> None:
    """F3, hand-computed: item 1 is taken by B's 👀 and answered by A after 5 minutes; item 2 is
    taken by B's 👀 and left to expire; item 3 is answered after 2 minutes by an outsider, C."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A", "B"))
    outsider = await insert_moderator(display_name="C")
    for message_id, minute in ((1, 0), (2, 1), (3, 2)):
        await insert_message(
            telegram_chat_id=chat_pk, message_id=message_id, sent_at=_T0 + timedelta(minutes=minute)
        )
    for message_id, minute in ((11, 5), (13, 4)):
        await insert_message(
            telegram_chat_id=chat_pk, message_id=message_id, sent_at=_T0 + timedelta(minutes=minute)
        )
    await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_T0,
        status="answered",
        first_response_moderator_id=team["A"]["moderator_id"],
        first_response_at=_T0 + timedelta(minutes=5),
        first_response_message_id=11,
    )
    await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=2,
        opened_at=_T0 + timedelta(minutes=1),
        status="expired",
        closed_at=_T0 + timedelta(hours=24),
    )
    await insert_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=3,
        opened_at=_T0 + timedelta(minutes=2),
        status="answered",
        first_response_moderator_id=outsider["moderator_id"],
        first_response_at=_T0 + timedelta(minutes=4),
        first_response_message_id=13,
    )
    for message_id in (1, 2):
        await react(
            telegram_chat_id=chat_pk,
            target_message_id=message_id,
            moderator=team["B"],
            at=_T0 + timedelta(minutes=3),
        )

    async with incident_session_factory() as session:
        work = {
            name: await attention_work_stats(
                session,
                period_from=_PERIOD[0],
                period_to=_PERIOD[1],
                min_samples=10,
                moderator_id=moderator["moderator_id"],
            )
            for name, moderator in (("A", team["A"]), ("B", team["B"]), ("C", outsider))
        }
        unanswered_a = await unanswered_stats(
            session,
            period_from=_PERIOD[0],
            period_to=_PERIOD[1],
            moderator_id=team["A"]["moderator_id"],
        )

    assert work["B"]["assigned"] == 2
    assert (work["B"]["via_reaction"], work["B"]["via_reply"]) == (2, 0)
    assert (work["B"]["assigned_answered"], work["B"]["assigned_expired"]) == (1, 1)
    assert work["B"]["answered_by_me"]["answered"] == 0

    assert work["A"]["assigned"] == 0
    assert work["A"]["answered_by_me"]["answered"] == 1
    assert work["A"]["answered_by_me"]["median_frt"] == 300
    assert work["A"]["answered_by_me"]["p90_frt"] is None  # 1 < min_samples
    assert work["A"]["outside"] == 0

    assert work["C"]["assigned"] == 0
    assert work["C"]["outside"] == 1
    assert work["C"]["answered_by_me"]["max_frt"] == 120

    # The item B took and let expire is still a miss for the whole team (D-TG-205).
    assert unanswered_a["unanswered"] == 1


async def test_my_incident_work_counts_what_i_took_and_how_fast(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
) -> None:
    """F4, hand-computed: A acknowledges in the panel 50 seconds after the flag; an outsider, C,
    acknowledges a second incident in the same group."""
    chat_pk, team = await _group(insert_chat, insert_moderator, insert_assignment, ("A",))
    outsider = await insert_moderator(display_name="C")
    incident_ids = []
    for message_id in (1, 2):
        await insert_message(telegram_chat_id=chat_pk, message_id=message_id, sent_at=_T0)
        incident_ids.append(
            await insert_incident(
                telegram_chat_id=chat_pk,
                telegram_message_id=message_id,
                opened_at=_T0,
                detected_at=_T0 + timedelta(seconds=10),
                category="SPAM_OR_AD",
                severity="low",
            )
        )
    for incident_id, moderator in zip(incident_ids, (team["A"], outsider), strict=True):
        await insert_action(
            telegram_chat_id=chat_pk,
            action_type="panel_acknowledge",
            action_strength="acknowledgement",
            occurred_at=_T0 + timedelta(seconds=60),
            panel_user_id=7,
            actor_moderator_id=moderator["moderator_id"],
            moderation_incident_id=incident_id,
        )

    async with incident_session_factory() as session:
        work_a = await incident_work_stats(
            session,
            period_from=_PERIOD[0],
            period_to=_PERIOD[1],
            min_samples=10,
            moderator_id=team["A"]["moderator_id"],
        )
        work_c = await incident_work_stats(
            session,
            period_from=_PERIOD[0],
            period_to=_PERIOD[1],
            min_samples=10,
            moderator_id=outsider["moderator_id"],
        )

    assert (work_a["assigned"], work_a["assigned_acknowledged"]) == (1, 1)
    assert work_a["via"] == {"panel_acknowledge": 1}
    assert work_a["take"]["samples"] == 1
    assert work_a["take"]["median"] == 50
    assert work_a["outside"] == 0
    assert (work_c["assigned"], work_c["outside"]) == (0, 1)
