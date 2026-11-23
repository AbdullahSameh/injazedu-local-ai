"""D1 and D2 (`contracts/alerting.md` §1, data-model §1, FR-501, FR-502): one destination at most,
and never a monitored chat, refused by the database in both orders.

Each case runs in one transaction that is always rolled back, so the database's one real
destination (if a fixture set one) is never disturbed.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session(
    alert_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with alert_session_factory() as session:
        await session.begin()
        # No other destination inside this transaction, whatever the database holds.
        await session.execute(
            sa.text("UPDATE telegram_chats SET is_alert_destination = false "
                    "WHERE is_alert_destination")
        )
        try:
            yield session
        finally:
            await session.rollback()


async def _chat(session: AsyncSession, *, monitored: bool) -> int:
    return int(
        (
            await session.execute(
                sa.text(
                    "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
                    "VALUES (:chat_id, 'supergroup', :monitored) RETURNING id"
                ),
                {"chat_id": -random.randint(10_000_000, 2_000_000_000), "monitored": monitored},
            )
        ).scalar_one()
    )


async def _violation(session: AsyncSession, sql: str, params: dict[str, object]) -> str | None:
    try:
        async with session.begin_nested():
            await session.execute(sa.text(sql), params)
    except IntegrityError as exc:
        return exc.orig.diag.constraint_name  # type: ignore[union-attr]
    return None


async def _designate(session: AsyncSession, chat_pk: int) -> str | None:
    return await _violation(
        session,
        "UPDATE telegram_chats SET is_alert_destination = true WHERE id = :id",
        {"id": chat_pk},
    )


async def test_d1_a_second_destination_is_refused(session: AsyncSession) -> None:
    first = await _chat(session, monitored=False)
    second = await _chat(session, monitored=False)

    assert await _designate(session, first) is None
    assert await _designate(session, second) == "uq_chat_one_alert_destination"


async def test_d2_designating_a_monitored_chat_is_refused(session: AsyncSession) -> None:
    monitored = await _chat(session, monitored=True)

    assert await _designate(session, monitored) == "ck_chat_destination_not_monitored"


async def test_d2_monitoring_the_destination_is_refused(session: AsyncSession) -> None:
    destination = await _chat(session, monitored=False)
    assert await _designate(session, destination) is None

    assert (
        await _violation(
            session,
            "UPDATE telegram_chats SET is_monitored = true WHERE id = :id",
            {"id": destination},
        )
        == "ck_chat_destination_not_monitored"
    )


async def test_clearing_the_flag_then_designating_another_chat_works(
    session: AsyncSession,
) -> None:
    first = await _chat(session, monitored=False)
    second = await _chat(session, monitored=False)
    assert await _designate(session, first) is None

    await session.execute(
        sa.text("UPDATE telegram_chats SET is_alert_destination = false WHERE id = :id"),
        {"id": first},
    )

    assert await _designate(session, second) is None
    designated = (
        await session.execute(
            sa.text("SELECT id FROM telegram_chats WHERE is_alert_destination")
        )
    ).scalars().all()
    assert designated == [second]


async def test_a_new_chat_is_never_the_destination_by_default(session: AsyncSession) -> None:
    chat_pk = await _chat(session, monitored=False)

    flag = (
        await session.execute(
            sa.text("SELECT is_alert_destination FROM telegram_chats WHERE id = :id"),
            {"id": chat_pk},
        )
    ).scalar_one()
    assert flag is False
