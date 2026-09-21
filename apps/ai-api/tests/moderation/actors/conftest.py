"""Shared fixtures for `tests/moderation/actors/`: an async session factory against
`injaz_ai_test` via `TEST_DATABASE_URL`, following `tests/moderation/ingest/conftest.py`, and
builders for `message`, `edited_message` and `my_chat_member` update payloads reusing TG-M1's
fixture shapes (`tests/moderation/ingest/conftest.py`'s `make_update` family).

This milestone reads stored `telegram_updates` rows rather than polling, so no transport fake is
needed here — only the payload shapes captured events already carry.

Assumes `injaz_ai_test` is already migrated to head; `make test-db-reset` is the operator's step.
"""

from __future__ import annotations

import os
import random
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.infrastructure.models_moderation import (
    moderator_group_assignments,
    telegram_chats,
    telegram_messages,
    telegram_updates,
    telegram_users,
)
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_APP_DIR = Path(__file__).resolve().parents[3]


def make_update(update_id: int, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """A raw Bot API update dict carrying exactly one `kind` key, as `getUpdates` would return."""
    return {"update_id": update_id, kind: body}


def make_message_update(
    update_id: int,
    *,
    chat_id: int = -1001,
    chat_type: str = "group",
    message_id: int | None = None,
    date: int = 1_700_000_000,
    text: str | None = "hello",
    caption: str | None = None,
    from_user: dict[str, Any] | None | bool = False,
    sender_chat: dict[str, Any] | None = None,
    reply_to_message_id: int | None = None,
    message_thread_id: int | None = None,
    is_automatic_forward: bool = False,
    entities: list[dict[str, Any]] | None = None,
    media_kind: str | None = None,
) -> dict[str, Any]:
    """A `message` update. `from_user=False` (the default) means "use TG-M1's usual sender";
    pass `None` explicitly for a senderless message (an anonymous admin or channel post via
    `sender_chat`), or a dict for a specific sender.
    """
    body: dict[str, Any] = {
        "message_id": message_id if message_id is not None else update_id,
        "date": date,
        "chat": {"id": chat_id, "type": chat_type},
    }
    if from_user is False:
        body["from"] = {"id": 1, "is_bot": False, "first_name": "Test"}
    elif from_user is not None:
        body["from"] = from_user
    if sender_chat is not None:
        body["sender_chat"] = sender_chat
    if text is not None:
        body["text"] = text
    if caption is not None:
        body["caption"] = caption
    if reply_to_message_id is not None:
        body["reply_to_message"] = {"message_id": reply_to_message_id}
    if message_thread_id is not None:
        body["message_thread_id"] = message_thread_id
    if is_automatic_forward:
        body["is_automatic_forward"] = True
    if entities is not None:
        body["entities"] = entities
    if media_kind is not None:
        body[media_kind] = {}
    return make_update(update_id, "message", body)


def make_service_message_update(
    update_id: int,
    *,
    chat_id: int = -1001,
    message_id: int | None = None,
    date: int = 1_700_000_000,
    new_chat_title: str | None = "New Title",
) -> dict[str, Any]:
    """A service announcement — no `text`, no personal content, `is_service` territory."""
    body: dict[str, Any] = {
        "message_id": message_id if message_id is not None else update_id,
        "date": date,
        "chat": {"id": chat_id, "type": "group"},
        "from": {"id": 1, "is_bot": False, "first_name": "Test"},
    }
    if new_chat_title is not None:
        body["new_chat_title"] = new_chat_title
    return make_update(update_id, "message", body)


def make_edited_message_update(
    update_id: int,
    *,
    chat_id: int = -1001,
    message_id: int,
    date: int = 1_700_000_100,
    text: str | None = "hello, edited",
    caption: str | None = None,
    from_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "message_id": message_id,
        "date": date,
        "chat": {"id": chat_id, "type": "group"},
        "from": from_user or {"id": 1, "is_bot": False, "first_name": "Test"},
    }
    if text is not None:
        body["text"] = text
    if caption is not None:
        body["caption"] = caption
    return make_update(update_id, "edited_message", body)


def make_my_chat_member_update(
    update_id: int,
    *,
    chat_id: int = -1001,
    chat_type: str = "supergroup",
    status: str = "member",
    can_delete_messages: bool | None = None,
) -> dict[str, Any]:
    new_member: dict[str, Any] = {"user": {"id": 999, "is_bot": True}, "status": status}
    if can_delete_messages is not None:
        new_member["can_delete_messages"] = can_delete_messages
    return make_update(
        update_id,
        "my_chat_member",
        {
            "chat": {"id": chat_id, "type": chat_type, "title": "Test Group"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "date": 1_700_000_000,
            "old_chat_member": {"user": {"id": 999, "is_bot": True}, "status": "left"},
            "new_chat_member": new_member,
        },
    )


@pytest.fixture
def actors_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the schema to head if `moderator_group_assignments` (the last table `0004`
    creates) is missing, mirroring `tests/moderation/ingest/conftest.py`'s guard."""
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('moderator_group_assignments')")
            ).scalar_one()
    finally:
        engine.dispose()

    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def actors_session_factory(
    actors_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(actors_test_database_url)
    engine = create_async_engine(actors_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def actors_engine(actors_test_database_url: str) -> AsyncIterator[AsyncEngine]:
    _ensure_schema_at_head(actors_test_database_url)
    engine = create_async_engine(actors_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def actors_sync_engine(actors_test_database_url: str) -> Iterator[Any]:
    """A synchronous engine for tests that exercise raw SQL directly against the database
    invariants rather than through the application (`test_db_invariants.py`)."""
    _ensure_schema_at_head(actors_test_database_url)
    engine = create_engine(actors_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def actors_bot_id() -> int:
    """A unique bot id per test, mirroring `ingest_bot_id`'s isolation in the shared test DB."""
    return random.randint(10_000_000, 2_000_000_000)


@pytest.fixture
def actors_chat_id() -> int:
    """A unique negative chat id per test, mirroring `ingest_chat_id`."""
    return -random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
def insert_chat(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_chats` row and returns its surrogate id. `is_monitored=True` by
    default — US1's derivation tests operate on a measured group; the gate itself (FR-019) is
    US2's concern (T025), not this fixture's."""

    async def _insert(
        *, chat_id: int, chat_type: str = "group", is_monitored: bool = True
    ) -> int:
        async with actors_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_chats.insert()
                    .values(chat_id=chat_id, chat_type=chat_type, is_monitored=is_monitored)
                    .returning(telegram_chats.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_captured_update(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `telegram_updates` row from an update dict shaped by `make_message_update` /
    `make_edited_message_update` / `make_my_chat_member_update` (i.e. carrying `update_id` and
    exactly one kind key), and returns its surrogate id — the `update_row_id` the derivation
    functions and `process_update_row` take."""

    async def _insert(*, bot_id: int, chat_id: int | None, update: dict[str, Any]) -> int:
        kind = next(k for k in update if k != "update_id")
        async with actors_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=bot_id,
                        update_id=update["update_id"],
                        update_type=kind,
                        chat_id=chat_id,
                        payload=update,
                    )
                    .returning(telegram_updates.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def fetch_message(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `telegram_messages` row as a mapping, or `None` if it was not derived."""

    async def _fetch(*, telegram_chat_id: int, message_id: int) -> dict[str, Any] | None:
        async with actors_session_factory() as session:
            result = await session.execute(
                sa.select(telegram_messages).where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.message_id == message_id,
                )
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _fetch


@pytest_asyncio.fixture
def count_messages(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Counts `telegram_messages` rows for one chat — used to assert idempotency and
    completeness over a backlog without fetching every row."""

    async def _count(*, telegram_chat_id: int) -> int:
        async with actors_session_factory() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(telegram_messages)
                    .where(telegram_messages.c.telegram_chat_id == telegram_chat_id)
                )
            ).scalar_one()

    return _count


@pytest_asyncio.fixture
def fetch_assignment(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `moderator_group_assignments` row by its surrogate id, as a mapping."""

    async def _fetch(*, assignment_id: int) -> dict[str, Any]:
        async with actors_session_factory() as session:
            result = await session.execute(
                sa.select(moderator_group_assignments).where(
                    moderator_group_assignments.c.id == assignment_id
                )
            )
            return dict(result.mappings().one())

    return _fetch


@pytest_asyncio.fixture
def count_current_owners_at(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Counts `primary` assignments covering instant `t` for one chat — an independent check of
    O1 (`responsible_at` returns at most one) that does not go through `responsible_at` itself."""

    async def _count(*, telegram_chat_id: int, t: Any) -> int:
        async with actors_session_factory() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(moderator_group_assignments)
                    .where(
                        moderator_group_assignments.c.telegram_chat_id == telegram_chat_id,
                        moderator_group_assignments.c.assignment_role == "primary",
                        moderator_group_assignments.c.valid_from <= t,
                        sa.or_(
                            moderator_group_assignments.c.valid_to.is_(None),
                            moderator_group_assignments.c.valid_to > t,
                        ),
                    )
                )
            ).scalar_one()

    return _count


@pytest_asyncio.fixture
def fetch_user(
    actors_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `telegram_users` row by the platform's `tg_user_id`, as a mapping, or `None`
    if no identity was resolved for it."""

    async def _fetch(*, tg_user_id: int) -> dict[str, Any] | None:
        async with actors_session_factory() as session:
            result = await session.execute(
                sa.select(telegram_users).where(telegram_users.c.tg_user_id == tg_user_id)
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _fetch
