"""Shared fixtures for `tests/moderation/classification/`: an async session factory against
`injaz_ai_test` via `TEST_DATABASE_URL`, builders that place a chat, a user, a moderator, an
assignment or a message without going through TG-M5's own pipeline code, an `insert_prediction`
builder writing `message_classifications` directly, a namespaced Redis fixture for the claim lock,
and `scripted_gateway` — a real `Gateway` wired to a scripted `FakeLLMProvider` (`tasks.md` T005).

TG-M2's chat, moderator and assignment factories are reused directly rather than re-implemented:
`map_moderator`, `open_assignment`, `handover`, `responsible_at` and `upsert_identity` are imported
from `app.application.moderation`, exactly as `tests/moderation/incidents/conftest.py` does.
`insert_chat` / `insert_user` / `insert_moderator` / `insert_assignment` / `insert_message` mirror
that same package's direct builders — siblings under `tests/moderation/` do not inherit each
other's `conftest.py`, so they are rebuilt here rather than imported across packages.

`insert_message` is extended, against that precedent, so every message is created **from a
captured `message` event** whose own `payload` carries the text (P1, D-TG-138): the classifier
reads `source_update_id`'s payload, never the row, so a test that wants to prove that
(`test_first_posted_text.py`) needs the update's body to diverge from the row it produced.

`insert_prediction` writes directly to `message_classifications` via `sa.text()` rather than
through the SQLAlchemy Core `Table` object, because this package's tests are written before
`data-model.md` §2's table exists (`tasks.md` Phase 1 precedes Phase 2, exactly as
`tests/moderation/incidents/conftest.py`'s own `insert_incident` was). Once migration `0007`
lands, the column names below are exactly `data-model.md`'s.

`scripted_gateway` builds a real `Gateway` — the `ProfileRegistry` resolves an **active
`moderation` profile** it seeds once per test session, matching the row `0007` and its CHECK
constraint will accept; until that migration lands, nothing in this package's own Phase 1 tests
calls it. M1's `FakeLLMProvider` cannot synthesise `Literal` fields (research probe 7), so every
prediction a test wants must be scripted via `responses=`.

Assumes `injaz_ai_test` is already migrated to head; `make test-db-reset` is the operator's step.
"""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.application.gateway.accounting import AccountingWriter
from app.application.gateway.breaker import CircuitBreaker
from app.application.gateway.errors import GatewayError
from app.application.gateway.gateway import Gateway
from app.application.gateway.lanes import Lane
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.identities import map_moderator
from app.application.moderation.text import normalize
from app.domain.model_profile import ModelProfile
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import (
    attention_items,
    moderation_actions,
    moderation_incidents,
    moderator_group_assignments,
    telegram_chats,
    telegram_messages,
    telegram_updates,
    telegram_users,
)
from app.providers.llm.base import (
    LLMProvider,
    StructuredRequest,
    StructuredResponse,
    TextRequest,
    TextResponse,
)
from app.providers.llm.fake import FakeLLMProvider
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_APP_DIR = Path(__file__).resolve().parents[3]

_MODERATION_PROFILE_NAME = "cls-test-moderation-active"


@pytest.fixture(scope="session")
def classification_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the schema to head if `message_classifications` (the table `0007` creates) is
    missing, mirroring `tests/moderation/incidents/conftest.py`'s guard."""
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('message_classifications')")
            ).scalar_one()
    finally:
        engine.dispose()

    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def classification_session_factory(
    classification_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(classification_test_database_url)
    engine = create_async_engine(classification_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def classification_engine(
    classification_test_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    _ensure_schema_at_head(classification_test_database_url)
    engine = create_async_engine(classification_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def classification_bot_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


@pytest.fixture
def classification_chat_id() -> int:
    """A unique negative chat id per test, mirroring `incident_chat_id`."""
    return -random.randint(10_000_000, 2_000_000_000)


@pytest_asyncio.fixture
def insert_chat(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_chats` row and returns its surrogate id. `is_monitored=True` by
    default, mirroring `tests/moderation/incidents/conftest.py`'s fixture of the same name."""

    async def _insert(
        *,
        chat_id: int,
        chat_type: str = "group",
        is_monitored: bool = True,
        migrated_to_chat_id: int | None = None,
    ) -> int:
        async with classification_session_factory() as session:
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
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts a `telegram_users` row directly and returns its surrogate id."""

    async def _insert(
        *, tg_user_id: int, username: str | None = None, is_bot: bool = False
    ) -> int:
        async with classification_session_factory() as session:
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
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_bot_id: int,
):
    """Inserts one `telegram_messages` row from a captured `message` event whose own `payload`
    carries the text (P1, D-TG-138) — the classifier reads the event, never the row. `body`'s
    shape follows the Bot API reference exactly as `app/application/moderation/messages.py`'s own
    derivation reads it, so a future `load_facts` finds it there unmodified. `body_overrides` lets
    a test place fields this builder does not otherwise expose (e.g. an entity list for
    redaction fixtures)."""

    async def _insert(
        *,
        telegram_chat_id: int,
        message_id: int,
        sent_at: datetime,
        telegram_user_id: int | None = None,
        tg_user_id: int | None = None,
        sender_chat_id: int | None = None,
        is_from_moderator: bool = False,
        is_service: bool = False,
        is_automatic_forward: bool = False,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
        original_text: str | None = "hello",
        normalized_text: str | None = None,
        media_kind: str | None = None,
        edited_at: datetime | None = None,
        text_purged_at: datetime | None = None,
        body_overrides: dict[str, Any] | None = None,
    ) -> int:
        resolved_normalized_text = (
            normalize(original_text)
            if normalized_text is None and original_text is not None
            else normalized_text
        )

        body: dict[str, Any] = {"message_id": message_id, "date": int(sent_at.timestamp())}
        if original_text is not None:
            body["text"] = original_text
        if media_kind is not None:
            body[media_kind] = {}
        if is_service:
            body["new_chat_title"] = "renamed"
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = {"message_id": reply_to_message_id}
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        if sender_chat_id is not None:
            body["sender_chat"] = {"id": sender_chat_id}
        if is_automatic_forward:
            body["is_automatic_forward"] = True
        if tg_user_id is not None:
            body["from"] = {"id": tg_user_id}
        if body_overrides:
            body.update(body_overrides)

        async with classification_session_factory() as session:
            update_row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=classification_bot_id,
                        update_id=random.randint(10_000_000, 2_000_000_000),
                        update_type="message",
                        chat_id=telegram_chat_id,
                        payload={"message": body},
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
                        text_purged_at=text_purged_at,
                        source_update_id=update_row_id,
                    )
                    .returning(telegram_messages.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest.fixture
def classification_settings() -> Settings:
    """A `Settings` instance built without an `.env` file, for `classify_one`'s `settings`
    parameter — every value but `DATABASE_URL`/`REDIS_URL` (both unused: the test's own session
    factory and Redis client are what actually get used) is this milestone's documented default:
    floor `0.60`, threshold `0.85`, `GATEWAY_CALL_TIMEOUT_S` `180`."""
    return Settings(DATABASE_URL="postgresql://unused/unused", REDIS_URL="redis://unused/0")


@pytest_asyncio.fixture
def insert_moderator(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Creates a moderator: a `telegram_users` row plus its `moderators` mapping, sharing one
    `tg_user_id`."""

    async def _insert(*, display_name: str = "Moderator") -> dict[str, int]:
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
        async with classification_session_factory() as session:
            telegram_user_id = (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=tg_user_id)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
            await session.commit()
        moderator_id = await map_moderator(
            classification_session_factory, tg_user_id=tg_user_id, display_name=display_name
        )
        return {"telegram_user_id": telegram_user_id, "moderator_id": moderator_id}

    return _insert


@pytest_asyncio.fixture
def insert_assignment(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderator_group_assignments` row directly, `valid_from`/`valid_to` given
    explicitly by the caller."""

    async def _insert(
        *,
        telegram_chat_id: int,
        moderator_id: int,
        valid_from: datetime,
        valid_to: datetime | None = None,
        role: str = "primary",
    ) -> int:
        async with classification_session_factory() as session:
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
def insert_prediction(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `message_classifications` row directly (`data-model.md` §2), bypassing
    `classify_one` so a test can place a prediction without this milestone's own pipeline code.
    Every field a test might need to control is an explicit keyword argument; the live-path
    defaults (thresholds set, `path='live'`) are the common case."""

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        model_profile_id: int,
        category: str,
        severity: str,
        needs_response: bool = False,
        needs_moderation: bool = False,
        confidence: str = "0.900",
        path: str = "live",
        route: str = "none",
        route_reason: str | None = None,
        confidence_floor: str | None = "0.600",
        incident_threshold: str | None = "0.850",
        model_run_id: int | None = None,
        prompt_version: str = "classify_v1",
        taxonomy_version: int = 1,
        is_current: bool = True,
        created_at: datetime | None = None,
    ) -> int:
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    sa.text(
                        """
                        INSERT INTO message_classifications (
                            telegram_chat_id, telegram_message_id, model_profile_id, model_run_id,
                            prompt_version, taxonomy_version, category, needs_response,
                            needs_moderation, severity, confidence, path, route, route_reason,
                            confidence_floor, incident_threshold, is_current, created_at
                        ) VALUES (
                            :telegram_chat_id, :telegram_message_id, :model_profile_id,
                            :model_run_id, :prompt_version, :taxonomy_version, :category,
                            :needs_response, :needs_moderation, :severity, :confidence, :path,
                            :route, :route_reason, :confidence_floor, :incident_threshold,
                            :is_current, COALESCE(:created_at, now())
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "telegram_chat_id": telegram_chat_id,
                        "telegram_message_id": telegram_message_id,
                        "model_profile_id": model_profile_id,
                        "model_run_id": model_run_id,
                        "prompt_version": prompt_version,
                        "taxonomy_version": taxonomy_version,
                        "category": category,
                        "needs_response": needs_response,
                        "needs_moderation": needs_moderation,
                        "severity": severity,
                        "confidence": confidence,
                        "path": path,
                        "route": route,
                        "route_reason": route_reason,
                        "confidence_floor": confidence_floor,
                        "incident_threshold": incident_threshold,
                        "is_current": is_current,
                        "created_at": created_at,
                    },
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_incident(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderation_incidents` row directly (`data-model.md` §4), bypassing both
    `open_incident` and `classify_one`'s own call to `insert_incident` — so US4 tests can place an
    operator's incident *before* classifying a message, independent of the code under test.
    `source='operator'` and its opener are the defaults, mirroring
    `tests/moderation/incidents/conftest.py`'s fixture of the same name."""

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
        prompted_by_classification_id: int | None = None,
        responsible_moderator_id: int | None = None,
    ) -> int:
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    moderation_incidents.insert()
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        telegram_message_id=telegram_message_id,
                        opened_at=opened_at,
                        detected_at=detected_at,
                        source=source,
                        opened_by_user_id=opened_by_user_id,
                        category=category,
                        severity=severity,
                        message_classification_id=message_classification_id,
                        prompted_by_classification_id=prompted_by_classification_id,
                        responsible_moderator_id=responsible_moderator_id,
                    )
                    .returning(moderation_incidents.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def fetch_incident(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `moderation_incidents` row by `(chat_pk, message_id)` — its own columns, never
    the derived view — or `None` when no incident anchors that message."""

    async def _fetch(*, telegram_chat_id: int, telegram_message_id: int) -> dict[str, Any] | None:
        async with classification_session_factory() as session:
            result = await session.execute(
                sa.select(moderation_incidents).where(
                    moderation_incidents.c.telegram_chat_id == telegram_chat_id,
                    moderation_incidents.c.telegram_message_id == telegram_message_id,
                )
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _fetch


@pytest_asyncio.fixture
def read_incident_state(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """`SELECT * FROM moderation_incident_state WHERE incident_id = :id` — TG-M4's only
    definition of an incident's status and moments (lifecycle contract N6), read here and computed
    nowhere in this package."""

    async def _read(incident_id: int) -> dict[str, Any] | None:
        async with classification_session_factory() as session:
            result = await session.execute(
                sa.text("SELECT * FROM moderation_incident_state WHERE incident_id = :id"),
                {"id": incident_id},
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    return _read


@pytest_asyncio.fixture
def insert_action(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `moderation_actions` row directly (`data-model.md` §2 of TG-M4), bypassing
    every derivation and guarded panel write — so a test can place a captured enforcement (e.g. a
    ban before classification ever ran) or a panel false-positive closure at a chosen instant."""

    async def _insert(
        *,
        telegram_chat_id: int,
        action_type: str,
        occurred_at: datetime,
        action_strength: str | None = None,
        actor_telegram_user_id: int | None = None,
        actor_moderator_id: int | None = None,
        panel_user_id: int | None = None,
        subject_telegram_user_id: int | None = None,
        moderation_incident_id: int | None = None,
        source_update_id: int | None = None,
        note: str | None = None,
    ) -> int:
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    moderation_actions.insert()
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        action_type=action_type,
                        action_strength=action_strength,
                        occurred_at=occurred_at,
                        actor_telegram_user_id=actor_telegram_user_id,
                        actor_moderator_id=actor_moderator_id,
                        panel_user_id=panel_user_id,
                        subject_telegram_user_id=subject_telegram_user_id,
                        moderation_incident_id=moderation_incident_id,
                        source_update_id=source_update_id,
                        note=note,
                    )
                    .returning(moderation_actions.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_attention_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Inserts one `attention_items` row directly (`data-model.md` §1 of TG-M3/TG-M4), bypassing
    the rule set entirely — for T055's proof that classification never creates, closes or
    otherwise touches one."""

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        opened_at: datetime,
        source: str = "rule",
        rule_version: int | None = 1,
        status: str = "open",
        responsible_moderator_id: int | None = None,
        first_response_message_id: int | None = None,
        first_response_at: datetime | None = None,
        first_response_kind: str | None = None,
    ) -> int:
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    attention_items.insert()
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        telegram_message_id=telegram_message_id,
                        opened_at=opened_at,
                        source=source,
                        rule_version=rule_version,
                        status=status,
                        responsible_moderator_id=responsible_moderator_id,
                        first_response_message_id=first_response_message_id,
                        first_response_at=first_response_at,
                        first_response_kind=first_response_kind,
                    )
                    .returning(attention_items.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def fetch_attention_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
):
    """Fetches one `attention_items` row by its surrogate id, as a plain mapping — for a
    before/after byte-identical comparison."""

    async def _fetch(*, item_id: int) -> dict[str, Any]:
        async with classification_session_factory() as session:
            result = await session.execute(
                sa.select(attention_items).where(attention_items.c.id == item_id)
            )
            return dict(result.mappings().one())

    return _fetch


@pytest.fixture
def classification_redis_namespace() -> str:
    """A per-test-run prefix so concurrent test runs never collide on the same claim keys."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def classification_redis(classification_redis_namespace: str) -> AsyncIterator[Redis]:
    """A real Redis client, scoped to keys under this run's namespace, cleaned up on teardown —
    mirrors `tests/gateway/conftest.py`'s `gateway_redis`, for `classify_one`'s `claim()` lock
    (`ai:mod:classify:msg:*`, T034)."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        async for key in client.scan_iter(
            match=f"ai:mod:classify:*{classification_redis_namespace}*", count=100
        ):
            await client.delete(key)
        await client.aclose()


@pytest_asyncio.fixture
async def classification_seeded_profile(
    classification_test_database_url: str,
) -> AsyncIterator[None]:
    """One active `moderation` profile, re-seeded before every test rather than once per session:
    `test_migration_0007.py`'s own autouse fixture drops and recreates every table in this same
    database, including `model_profiles`, so a session-scoped row does not survive running
    alongside it. `ON CONFLICT ... DO UPDATE` reactivates the row if a table drop or an unrelated
    test left it (re)created but inactive."""
    _ensure_schema_at_head(classification_test_database_url)
    engine = create_async_engine(classification_test_database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE model_profiles SET is_active = false "
                    "WHERE role = 'moderation' AND name <> :name AND is_active = true"
                ),
                {"name": _MODERATION_PROFILE_NAME},
            )
            await conn.execute(
                text(
                    "INSERT INTO model_profiles "
                    "(name, provider, base_url, model, role, params, dim, is_active) VALUES "
                    "(:name, 'fake', NULL, 'fake-moderation-active', 'moderation', "
                    "  '{}'::jsonb, NULL, true) "
                    "ON CONFLICT (name) DO UPDATE SET is_active = true"
                ),
                {"name": _MODERATION_PROFILE_NAME},
            )
        yield
    finally:
        try:
            async with engine.begin() as conn:
                table_exists = (
                    await conn.execute(text("SELECT to_regclass('model_profiles')"))
                ).scalar_one()
                if table_exists is not None:
                    await conn.execute(
                        text("DELETE FROM model_profiles WHERE name = :name"),
                        {"name": _MODERATION_PROFILE_NAME},
                    )
        except Exception:  # noqa: BLE001 — best-effort teardown, mirrors gateway conftest
            pass
        await engine.dispose()


class _RecordingProvider:
    """Wraps a `FakeLLMProvider`, appending every request it receives to `calls` — the second
    value `scripted_gateway` returns, so a test can inspect exactly what the provider was sent
    (T044) as well as how many times (T031, T032)."""

    def __init__(self, inner: FakeLLMProvider, calls: list[Any]) -> None:
        self._inner = inner
        self._calls = calls

    async def generate_text(self, req: TextRequest) -> TextResponse:
        self._calls.append(req)
        return await self._inner.generate_text(req)

    async def generate_structured(
        self, req: StructuredRequest[Any]
    ) -> StructuredResponse[Any]:
        self._calls.append(req)
        return await self._inner.generate_structured(req)


@pytest_asyncio.fixture
async def scripted_gateway(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_seeded_profile: None,
) -> AsyncIterator[Callable[..., tuple[Gateway, list[Any]]]]:
    """Returns a builder — `scripted_gateway(responses=None, fail_with=None,
    capture_payloads=False)` → `(gateway, provider_calls)` — over a real `ProfileRegistry`
    resolving the active `moderation` profile, a `FakeLLMProvider` scripted with `responses` /
    `fail_with`, the gateway tests' lane and breaker wiring (namespaced per call so concurrent
    tests never collide), a real `AccountingWriter` on the test session factory, and
    `max_retries=0` (a cut-off answer's retry is the task's job, US3 — research Finding 6)."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    opened_clients: list[Redis] = []

    def _build(
        *,
        responses: list[Any] | None = None,
        fail_with: type[GatewayError] | None = None,
        capture_payloads: bool = False,
    ) -> tuple[Gateway, list[Any]]:
        provider_calls: list[Any] = []

        def _llm_provider_factory(profile: ModelProfile) -> LLMProvider:
            fake = FakeLLMProvider(
                responses=list(responses) if responses is not None else None,
                fail_with=fail_with,
                profile_name=profile.name,
            )
            return _RecordingProvider(fake, provider_calls)  # type: ignore[return-value]

        namespace = f"test-{uuid.uuid4().hex[:12]}"
        redis: Redis = Redis.from_url(redis_url, decode_responses=True)
        opened_clients.append(redis)

        registry = ProfileRegistry(classification_session_factory)
        accounting = AccountingWriter(
            classification_session_factory, capture_payloads=capture_payloads
        )
        gateway = Gateway(
            registry,
            llm_provider_factory=_llm_provider_factory,  # type: ignore[arg-type]
            llm_lane=Lane(redis, "llm", key_prefix=f"ai:gw:{namespace}"),
            embed_lane=Lane(redis, "embed", key_prefix=f"ai:gw:{namespace}"),
            breaker=CircuitBreaker(redis, key_prefix=f"ai:gw:{namespace}:breaker"),
            accounting=accounting,
            max_retries=0,
        )
        return gateway, provider_calls

    try:
        yield _build
    finally:
        # Every lane/breaker key carries a TTL (data-model.md §3) — a per-call namespace that is
        # never revisited simply expires; only the connections themselves need closing.
        for client in opened_clients:
            await client.aclose()
