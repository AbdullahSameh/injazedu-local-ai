"""Shared fixtures for `tests/moderation/attention/`: an async session factory against
`injaz_ai_test` via `TEST_DATABASE_URL` (revision `0005` head), a controlled clock, and a
builder that inserts `telegram_messages` rows directly with an explicit `sent_at`,
`is_from_moderator`, `reply_to_message_id` and `message_thread_id`.

This milestone reads stored messages rather than polling or deriving from captured updates, so
tests build the rows they need directly instead of going through `derive_message` — mirroring
`tests/moderation/actors/conftest.py`'s pattern rather than importing its fixtures (siblings
under `tests/moderation/` do not inherit each other's `conftest.py`). TG-M2's chat, moderator and
assignment factories (`insert_chat` here; `map_moderator`, `open_assignment`, `handover`,
`responsible_at` imported directly from `app.application.moderation`) are reused rather than
re-implemented, so an attention test builds ownership exactly as TG-M2's own tests do.

Assumes `injaz_ai_test` is already migrated to head; `make test-db-reset` is the operator's step.
"""

from __future__ import annotations

import os
import random
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.application.moderation.attention import assemble_burst, match_response, open_item
from app.application.moderation.identities import map_moderator
from app.application.moderation.text import normalize
from app.infrastructure.models_moderation import (
    attention_items,
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


@dataclass
class ControlledClock:
    """A fixed, settable instant — the one source of "now" for this package's fixture data.

    Nothing under test calls `datetime.now()` directly: every `sent_at` / `opened_at` a test
    builds is an offset from `.now()`, so a test's meaning does not depend on when the suite
    happens to run. `app/domain/moderation/attention.py` stays pure (no clock of its own,
    `plan.md`'s boundary rule), so this fixture exists for test data, not for injection into
    production code.
    """

    _instant: datetime

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        self._instant = instant

    def advance(self, seconds: float) -> datetime:
        self._instant += timedelta(seconds=seconds)
        return self._instant


@pytest.fixture
def attention_clock() -> ControlledClock:
    return ControlledClock(datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC))


@pytest.fixture
def attention_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the schema to head if `attention_items` (the table `0005` creates) is missing,
    mirroring `tests/moderation/actors/conftest.py`'s guard."""
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('attention_items')")).scalar_one()
    finally:
        engine.dispose()

    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def attention_session_factory(
    attention_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(attention_test_database_url)
    engine = create_async_engine(attention_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def attention_engine(attention_test_database_url: str) -> AsyncIterator[AsyncEngine]:
    _ensure_schema_at_head(attention_test_database_url)
    engine = create_async_engine(attention_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def attention_sync_engine(attention_test_database_url: str) -> Iterator[Any]:
    """A synchronous engine for tests that exercise raw SQL directly against the database
    invariants rather than through the application (`test_db_invariants.py`)."""
    _ensure_schema_at_head(attention_test_database_url)
    engine = create_engine(attention_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def attention_bot_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


@pytest.fixture
def attention_chat_id() -> int:
    """A unique negative chat id per test, mirroring `actors_chat_id`."""
    return -random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
def insert_chat(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_chats` row and returns its surrogate id. `is_monitored=True` by
    default, mirroring `tests/moderation/actors/conftest.py`'s fixture of the same name — most of
    this package's tests operate on a measured group."""

    async def _insert(
        *, chat_id: int, chat_type: str = "group", is_monitored: bool = True
    ) -> int:
        async with attention_session_factory() as session:
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
def insert_user(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_users` row directly and returns its surrogate id — `insert_message`'s
    `telegram_user_id` is a real FK, and this package builds sender identity itself rather than
    going through `upsert_identity` (T004: no transport, no credential, this milestone reads
    stored messages)."""

    async def _insert(
        *, tg_user_id: int, username: str | None = None, is_bot: bool = False
    ) -> int:
        async with attention_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=tg_user_id, username=username, is_bot=is_bot)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_message(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_bot_id: int,
):
    """Inserts one `telegram_messages` row directly, with every field this milestone's rules and
    matcher read as an explicit keyword argument — no `telegram_updates` round-trip and no
    `derive_message`, since this package tests the burst/rule/matching layer against rows it
    places itself (T004). A throwaway `telegram_updates` row satisfies `source_update_id`'s FK;
    nothing under test here reads its payload.

    `normalized_text=None` (the default) derives it from `original_text` via `normalize()` — pass
    it explicitly to store a normalisation that deliberately differs from a fresh derivation, or
    `original_text=None` with a `normalized_text` to simulate a message whose text was purged.
    """

    async def _insert(
        *,
        telegram_chat_id: int,
        message_id: int,
        sent_at: datetime,
        telegram_user_id: int | None = None,
        sender_chat_id: int | None = None,
        is_from_moderator: bool = False,
        is_service: bool = False,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        original_text: str | None = "hello",
        normalized_text: str | None = None,
        media_kind: str | None = None,
        edited_at: datetime | None = None,
    ) -> int:
        resolved_normalized_text = (
            normalize(original_text)
            if normalized_text is None and original_text is not None
            else normalized_text
        )
        async with attention_session_factory() as session:
            update_row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=attention_bot_id,
                        update_id=random.randint(10_000_000, 2_000_000_000),
                        update_type="message",
                        chat_id=telegram_chat_id,
                        payload={},
                    )
                    .returning(telegram_updates.c.id)
                )
            ).scalar_one()
            row_id = (
                await session.execute(
                    telegram_messages.insert()
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        message_id=message_id,
                        telegram_user_id=telegram_user_id,
                        sender_chat_id=sender_chat_id,
                        sent_at=sent_at,
                        edited_at=edited_at,
                        reply_to_message_id=reply_to_message_id,
                        message_thread_id=message_thread_id,
                        is_service=is_service,
                        is_from_moderator=is_from_moderator,
                        original_text=original_text,
                        normalized_text=resolved_normalized_text,
                        media_kind=media_kind,
                        source_update_id=update_row_id,
                    )
                    .returning(telegram_messages.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_moderator(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Creates a moderator who can send messages: a `telegram_users` row plus its `moderators`
    mapping, sharing one `tg_user_id` (Phase 4). `insert_message`'s `telegram_user_id` accepts the
    returned `telegram_user_id`; `close_item` resolves `first_response_moderator_id` from it via
    the `moderators` mapping, exactly as it would for a real sender.
    """

    async def _insert(*, display_name: str = "Moderator") -> dict[str, int]:
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
        async with attention_session_factory() as session:
            telegram_user_id = (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=tg_user_id)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
            await session.commit()
        moderator_id = await map_moderator(
            attention_session_factory, tg_user_id=tg_user_id, display_name=display_name
        )
        return {"telegram_user_id": telegram_user_id, "moderator_id": moderator_id}

    return _insert


@pytest_asyncio.fixture
def match_message(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Runs one live match — fetches the stored message by `(telegram_chat_id, message_id)` and
    calls `match_response`, exactly as `match_response_once` does without going through dramatiq
    (T042-T044). Returns the closed item's id, or `None`."""

    async def _match(*, telegram_chat_id: int, message_id: int) -> int | None:
        async with attention_session_factory() as session:
            message = (
                await session.execute(
                    sa.select(telegram_messages).where(
                        telegram_messages.c.telegram_chat_id == telegram_chat_id,
                        telegram_messages.c.message_id == message_id,
                    )
                )
            ).mappings().one()
            item_id = await match_response(session, message)
            await session.commit()
            return item_id

    return _match


@pytest_asyncio.fixture
def fetch_message(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `telegram_messages` row as a mapping, or `None` if it does not exist."""

    async def _fetch(*, telegram_chat_id: int, message_id: int) -> dict[str, Any] | None:
        async with attention_session_factory() as session:
            result = await session.execute(
                sa.select(telegram_messages).where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.message_id == message_id,
                )
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _fetch


@pytest.fixture
def attention_burst_gap_s() -> int:
    """`MODERATION_BURST_GAP_S`'s default (`.env.example`) — Phase 3's tests pass this
    explicitly rather than loading `Settings`, mirroring `record_downtime_if_any`'s
    explicit-parameter style."""
    return 90


@pytest_asyncio.fixture
def judge_burst(
    attention_session_factory: async_sessionmaker[AsyncSession],
    attention_burst_gap_s: int,
):
    """Runs one judgement — `assemble_burst` then `open_item`, one transaction — exactly as
    `evaluate_attention_once` does, without going through dramatiq (T026, T027). Returns the
    opened item's id, or `None` when the rules decline."""

    async def _judge(
        *,
        telegram_chat_id: int,
        telegram_user_id: int,
        message_thread_id: int | None = None,
        around: datetime,
        gap_s: int | None = None,
    ) -> int | None:
        async with attention_session_factory() as session:
            burst = await assemble_burst(
                session,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                message_thread_id=message_thread_id,
                around=around,
                gap_s=gap_s if gap_s is not None else attention_burst_gap_s,
            )
            item_id = await open_item(session, burst)
            await session.commit()
            return item_id

    return _judge


@pytest_asyncio.fixture
def fetch_item(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `attention_items` row by its surrogate id, as a mapping."""

    async def _fetch(*, item_id: int) -> dict[str, Any]:
        async with attention_session_factory() as session:
            result = await session.execute(
                sa.select(attention_items).where(attention_items.c.id == item_id)
            )
            return dict(result.mappings().one())

    return _fetch


@pytest_asyncio.fixture
def fetch_item_by_anchor(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches an `attention_items` row by its anchor `(telegram_chat_id, telegram_message_id)`,
    or `None` — the shape `uq_attention_anchor` protects (T015)."""

    async def _fetch(*, telegram_chat_id: int, telegram_message_id: int) -> dict[str, Any] | None:
        async with attention_session_factory() as session:
            result = await session.execute(
                sa.select(attention_items).where(
                    attention_items.c.telegram_chat_id == telegram_chat_id,
                    attention_items.c.telegram_message_id == telegram_message_id,
                )
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _fetch


@pytest_asyncio.fixture
def fetch_assignment(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `moderator_group_assignments` row by its surrogate id, as a mapping —
    `open_assignment`/`handover` stamp `valid_from`/`valid_to` from the database's own `now()`,
    not from `attention_clock`, so attribution tests read the real value back rather than
    assuming it (T021)."""

    async def _fetch(*, assignment_id: int) -> dict[str, Any]:
        async with attention_session_factory() as session:
            result = await session.execute(
                sa.select(moderator_group_assignments).where(
                    moderator_group_assignments.c.id == assignment_id
                )
            )
            return dict(result.mappings().one())

    return _fetch


@pytest_asyncio.fixture
def count_items(
    attention_session_factory: async_sessionmaker[AsyncSession],
):
    """Counts `attention_items` rows for one chat (T015, T018)."""

    async def _count(*, telegram_chat_id: int) -> int:
        async with attention_session_factory() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(attention_items)
                    .where(attention_items.c.telegram_chat_id == telegram_chat_id)
                )
            ).scalar_one()

    return _count
