"""Shared fixtures for `tests/moderation/incidents/`: an async session factory against
`injaz_ai_test` via `TEST_DATABASE_URL`, a controlled clock, and builders that let a test place an
incident, a piece of evidence or a captured `chat_member` / `message_reaction` event at a chosen
instant without going through `open_incident` or `process_update` — so US2/US3/US6 tests do not
depend on US1's code (`tasks.md` T007).

TG-M2's chat, moderator and assignment factories are reused directly rather than re-implemented:
`map_moderator`, `open_assignment`, `handover`, `responsible_at` and `upsert_identity` are imported
from `app.application.moderation`, exactly as `tests/moderation/attention/conftest.py` does.
`insert_message` mirrors that same package's direct `telegram_messages` builder (explicit
`sent_at`, `is_from_moderator`, `reply_to_message_id`, `sender_chat_id`) — siblings under
`tests/moderation/` do not inherit each other's `conftest.py`, so it is rebuilt here rather than
imported across packages.

`insert_incident` and `insert_action` write directly to `moderation_incidents` and
`moderation_actions` via `sa.text()` rather than through the SQLAlchemy Core `Table` objects,
because this package's tests are written before `data-model.md` §1–§2's tables exist
(`tasks.md` Phase 1 precedes Phase 2). Once Phase 2's migration `0006` lands, the column names
below are exactly `data-model.md`'s. `read_state` and `read_evidence` only `SELECT` from
`moderation_incident_evidence` and `moderation_incident_state` — the lifecycle's only definitions
(contract N6) — and compute nothing themselves.

Assumes `injaz_ai_test` is already migrated to head; `make test-db-reset` is the operator's step.
"""

from __future__ import annotations

import json
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
from app.application.moderation.identities import map_moderator
from app.application.moderation.text import normalize
from app.infrastructure.models_moderation import (
    moderation_incidents,
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

    Nothing under test calls `datetime.now()` directly: every `opened_at` / `occurred_at` a test
    builds is an offset from `.now()`. `app/domain/moderation/incident.py` stays pure (no clock of
    its own), so this fixture exists for test data, not for injection into production code.
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
def incident_clock() -> ControlledClock:
    return ControlledClock(datetime(2026, 1, 12, 9, 0, 0, tzinfo=UTC))


@pytest.fixture
def incident_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the schema to head if `moderation_incidents` (the table `0006` creates) is
    missing, mirroring `tests/moderation/attention/conftest.py`'s guard."""
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('moderation_incidents')")).scalar_one()
    finally:
        engine.dispose()

    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def incident_session_factory(
    incident_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(incident_test_database_url)
    engine = create_async_engine(incident_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def incident_engine(incident_test_database_url: str) -> AsyncIterator[AsyncEngine]:
    _ensure_schema_at_head(incident_test_database_url)
    engine = create_async_engine(incident_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def incident_sync_engine(incident_test_database_url: str) -> Iterator[Any]:
    """A synchronous engine for tests that exercise raw SQL directly against the database
    invariants rather than through the application (`test_db_invariants.py`)."""
    _ensure_schema_at_head(incident_test_database_url)
    engine = create_engine(incident_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest_asyncio.fixture
def db_now(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Reads the database's own `now()` once, for `test_metrics.py` (T058): the outcome SQL
    (`contracts/incident-metrics.md` §2) judges "missed" and "within window" against `now()`
    itself, so a test that wants a deterministic outcome places `detected_at` as an offset from
    this value — days in the past for a "settled" incident, minutes ago for one "within window"
    — rather than trying to fake the database's clock."""

    async def _now() -> datetime:
        async with incident_session_factory() as session:
            result = await session.execute(sa.select(sa.func.now()))
            return result.scalar_one()

    return _now


@pytest.fixture
def incident_bot_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


@pytest.fixture
def incident_chat_id() -> int:
    """A unique negative chat id per test, mirroring `attention_chat_id`."""
    return -random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
def insert_chat(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_chats` row and returns its surrogate id. `is_monitored=True` by
    default, mirroring `tests/moderation/attention/conftest.py`'s fixture of the same name."""

    async def _insert(
        *,
        chat_id: int,
        chat_type: str = "group",
        is_monitored: bool = True,
        migrated_to_chat_id: int | None = None,
    ) -> int:
        async with incident_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_chats.insert()
                    .values(
                        chat_id=chat_id,
                        chat_type=chat_type,
                        is_monitored=is_monitored,
                        migrated_to_chat_id=migrated_to_chat_id,
                    )
                    .returning(telegram_chats.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_user(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_users` row directly and returns its surrogate id, mirroring
    `tests/moderation/actors/conftest.py`'s fixture of the same name."""

    async def _insert(
        *, tg_user_id: int, username: str | None = None, is_bot: bool = False
    ) -> int:
        async with incident_session_factory() as session:
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
    incident_session_factory: async_sessionmaker[AsyncSession],
    incident_bot_id: int,
):
    """Inserts one `telegram_messages` row directly, exactly as
    `tests/moderation/attention/conftest.py`'s fixture of the same name — this package builds the
    anchor and reply/reaction targets it needs rather than deriving them from a captured update."""

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
        async with incident_session_factory() as session:
            update_row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=incident_bot_id,
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
def captured_update(
    incident_session_factory: async_sessionmaker[AsyncSession],
    incident_bot_id: int,
):
    """Inserts one `telegram_updates` row of kind `chat_member` or `message_reaction`, `body`
    shaped exactly as the caller builds it against the Bot API reference (research Finding 4).
    Returns the surrogate id — the `update_row_id` the evidence-derivation functions and
    `process_update_row` take, mirroring `tests/moderation/actors/conftest.py`'s
    `insert_captured_update`."""

    async def _insert(
        kind: str,
        body: dict[str, Any],
        *,
        update_id: int | None = None,
        chat_id: int | None = None,
        processed_at: datetime | None = None,
    ) -> int:
        resolved_update_id = (
            update_id if update_id is not None else random.randint(10_000_000, 2_000_000_000)
        )
        payload = {"update_id": resolved_update_id, kind: body}
        async with incident_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=incident_bot_id,
                        update_id=resolved_update_id,
                        update_type=kind,
                        chat_id=chat_id,
                        payload=payload,
                        processed_at=processed_at,
                    )
                    .returning(telegram_updates.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_incident(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderation_incidents` row directly (`data-model.md` §1), bypassing
    `open_incident` so US2/US3/US6 tests do not depend on US1's code. Every field a test might
    need to control is an explicit keyword argument; `source='operator'` and its opener are the
    only defaults, matching this milestone's only opener (`ai` is reserved for TG-M5)."""

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        opened_at: datetime,
        detected_at: datetime,
        category: str,
        severity: str,
        source: str = "operator",
        opened_by_user_id: int | None = 1,
        message_classification_id: int | None = None,
        responsible_moderator_id: int | None = None,
    ) -> int:
        async with incident_session_factory() as session:
            row_id = (
                await session.execute(
                    sa.text(
                        """
                        INSERT INTO moderation_incidents (
                            telegram_chat_id, telegram_message_id, opened_at, detected_at,
                            source, opened_by_user_id, category, severity,
                            message_classification_id, responsible_moderator_id
                        ) VALUES (
                            :telegram_chat_id, :telegram_message_id, :opened_at, :detected_at,
                            :source, :opened_by_user_id, :category, :severity,
                            :message_classification_id, :responsible_moderator_id
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "telegram_chat_id": telegram_chat_id,
                        "telegram_message_id": telegram_message_id,
                        "opened_at": opened_at,
                        "detected_at": detected_at,
                        "source": source,
                        "opened_by_user_id": opened_by_user_id,
                        "category": category,
                        "severity": severity,
                        "message_classification_id": message_classification_id,
                        "responsible_moderator_id": responsible_moderator_id,
                    },
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_action(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderation_actions` row directly (`data-model.md` §2), bypassing
    `derive_membership_evidence` / `derive_reaction_evidence` / the panel's guarded methods so
    US2/US3/US4/US6 tests can place evidence at a chosen instant, in a chosen order, without this
    milestone's own derivation code. `detail` defaults to `{}`, matching the column's default."""

    async def _insert(
        *,
        telegram_chat_id: int,
        action_type: str,
        occurred_at: datetime,
        action_strength: str | None = None,
        actor_telegram_user_id: int | None = None,
        actor_moderator_id: int | None = None,
        actor_is_anonymous: bool = False,
        panel_user_id: int | None = None,
        subject_telegram_user_id: int | None = None,
        target_message_id: int | None = None,
        moderation_incident_id: int | None = None,
        source_update_id: int | None = None,
        detail: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> int:
        async with incident_session_factory() as session:
            row_id = (
                await session.execute(
                    sa.text(
                        """
                        INSERT INTO moderation_actions (
                            telegram_chat_id, action_type, action_strength, occurred_at,
                            actor_telegram_user_id, actor_moderator_id, actor_is_anonymous,
                            panel_user_id, subject_telegram_user_id, target_message_id,
                            moderation_incident_id, source_update_id, detail, note
                        ) VALUES (
                            :telegram_chat_id, :action_type, :action_strength, :occurred_at,
                            :actor_telegram_user_id, :actor_moderator_id, :actor_is_anonymous,
                            :panel_user_id, :subject_telegram_user_id, :target_message_id,
                            :moderation_incident_id, :source_update_id, :detail, :note
                        )
                        RETURNING id
                        """
                    ).bindparams(sa.bindparam("detail", type_=sa.JSON())),
                    {
                        "telegram_chat_id": telegram_chat_id,
                        "action_type": action_type,
                        "action_strength": action_strength,
                        "occurred_at": occurred_at,
                        "actor_telegram_user_id": actor_telegram_user_id,
                        "actor_moderator_id": actor_moderator_id,
                        "actor_is_anonymous": actor_is_anonymous,
                        "panel_user_id": panel_user_id,
                        "subject_telegram_user_id": subject_telegram_user_id,
                        "target_message_id": target_message_id,
                        "moderation_incident_id": moderation_incident_id,
                        "source_update_id": source_update_id,
                        "detail": json.dumps(detail or {}),
                        "note": note,
                    },
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def read_state(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """`SELECT * FROM moderation_incident_state WHERE incident_id = :id` — the only definition of
    an incident's status and moments (contract N6). Computes nothing itself."""

    async def _read(incident_id: int) -> dict[str, Any] | None:
        async with incident_session_factory() as session:
            result = await session.execute(
                sa.text("SELECT * FROM moderation_incident_state WHERE incident_id = :id"),
                {"id": incident_id},
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _read


@pytest_asyncio.fixture
def insert_moderator(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Creates a moderator: a `telegram_users` row plus its `moderators` mapping, sharing one
    `tg_user_id`, mirroring `tests/moderation/attention/conftest.py`'s fixture of the same
    name."""

    async def _insert(*, display_name: str = "Moderator") -> dict[str, int]:
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
        async with incident_session_factory() as session:
            telegram_user_id = (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=tg_user_id)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
            await session.commit()
        moderator_id = await map_moderator(
            incident_session_factory, tg_user_id=tg_user_id, display_name=display_name
        )
        return {"telegram_user_id": telegram_user_id, "moderator_id": moderator_id}

    return _insert


@pytest_asyncio.fixture
def insert_assignment(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderator_group_assignments` row directly, `valid_from`/`valid_to` given
    explicitly by the caller — bypassing `open_assignment`/`handover` so a test can position an
    interval's boundary at an exact instant it already knows (e.g. a just-opened incident's own
    `detected_at`), which neither of those two functions' own `now()`-stamping lets a caller do."""

    async def _insert(
        *,
        telegram_chat_id: int,
        moderator_id: int,
        valid_from: datetime,
        valid_to: datetime | None = None,
        role: str = "primary",
    ) -> int:
        async with incident_session_factory() as session:
            row_id = (
                await session.execute(
                    moderator_group_assignments.insert()
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        moderator_id=moderator_id,
                        assignment_role=role,
                        valid_from=valid_from,
                        valid_to=valid_to,
                    )
                    .returning(moderator_group_assignments.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def fetch_incident(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `moderation_incidents` row by its surrogate id, as a mapping — the row's own
    columns (`data-model.md` §1), never the derived view."""

    async def _fetch(*, incident_id: int) -> dict[str, Any]:
        async with incident_session_factory() as session:
            result = await session.execute(
                sa.select(moderation_incidents).where(moderation_incidents.c.id == incident_id)
            )
            return dict(result.mappings().one())

    return _fetch


@pytest_asyncio.fixture
def read_evidence(
    incident_session_factory: async_sessionmaker[AsyncSession],
):
    """`SELECT * FROM moderation_incident_evidence WHERE incident_id = :id`, ordered
    `(occurred_at, source_rank, evidence_id)` — D-TG-106's tie-break, the only definition of
    linkage (contract N6). Computes nothing itself."""

    async def _read(incident_id: int) -> list[dict[str, Any]]:
        async with incident_session_factory() as session:
            result = await session.execute(
                sa.text(
                    """
                    SELECT * FROM moderation_incident_evidence
                    WHERE incident_id = :id
                    ORDER BY occurred_at, source_rank, evidence_id
                    """
                ),
                {"id": incident_id},
            )
            return [dict(row) for row in result.mappings().all()]

    return _read
