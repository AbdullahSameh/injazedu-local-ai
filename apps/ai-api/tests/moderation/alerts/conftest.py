"""Shared fixtures for `tests/moderation/alerts/` (TG-M6, `tasks.md` T504).

Everything runs against `injaz_ai_test` via `TEST_DATABASE_URL` (Principle II), with Telegram
scripted by an `httpx.MockTransport` and no network.

- **Chats.** `source_chat` is a monitored group; `destination_chat` is an unmonitored chat carrying
  the alert-destination flag. There is at most one destination in the database
  (`uq_chat_one_alert_destination`), so the fixture clears any flag a crashed run left behind and
  clears its own at teardown.
- **A moderator** declared 30 days ago, active, with a `telegram_users` identity and a current team
  membership in the source chat since the same instant, so a press or act placed in the past is a
  team member's.
- **`make_rule(**fields)`** inserts `alert_rules`. There is one global rule per trigger in the whole
  database (`uq_alert_rule_global`), so teardown removes every rule the test made, with its alerts
  and their button acts. Without that, revision `0013`'s downgrade would refuse in a later
  migration test (data-model §6).
- **`scripted_telegram`** records each `(method, params)` and answers with scripted results.
- **Subjects** are inserted with past timestamps rather than mocking the clock, because the
  evaluator reads the database's `now()`.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.application.moderation.alerting import Evaluation, evaluate_once
from app.application.moderation.text import normalize
from app.domain.moderation.alerting import dedupe_key
from app.infrastructure.models_moderation import (
    alert_rules,
    alerts,
    moderation_actions,
    moderator_group_assignments,
    moderators,
    telegram_chats,
    telegram_messages,
    telegram_updates,
    telegram_users,
)
from app.providers.telegram.client import TelegramClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_APP_DIR = Path(__file__).resolve().parents[3]

# A moderator and their membership start this long ago, so any act a test places in the recent
# past falls inside both (B2: `created_at` at or before the press; T3: on the team at the instant).
DECLARED_AGO = timedelta(days=30)


def _ensure_schema_at_head(sqlalchemy_url: str) -> None:
    """Repairs the schema to head if `alerts` (the table `0013` creates) is missing, as every
    sibling package's conftest does for its own revision."""
    engine = create_engine(sqlalchemy_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('alerts')")).scalar_one()
    finally:
        engine.dispose()
    if exists is None:
        cfg = Config(str(_APP_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_APP_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
        command.upgrade(cfg, "head")


@pytest.fixture
def alert_test_database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest_asyncio.fixture
async def alert_session_factory(
    alert_test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _ensure_schema_at_head(alert_test_database_url)
    engine = create_async_engine(alert_test_database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
def db_now(alert_session_factory: async_sessionmaker[AsyncSession]):
    """The database's own `now()`: the evaluator judges against it, so tests place subjects as
    offsets from this value."""

    async def _now() -> datetime:
        async with alert_session_factory() as session:
            return (await session.execute(sa.select(sa.func.now()))).scalar_one()

    return _now


@pytest.fixture
def bot_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


def _random_chat_id() -> int:
    return -random.randint(10_000_000_000, 99_999_999_999)


@dataclass(frozen=True)
class Chat:
    id: int  # telegram_chats surrogate
    chat_id: int  # platform id


@pytest_asyncio.fixture
def insert_chat(alert_session_factory: async_sessionmaker[AsyncSession]):
    async def _insert(
        *,
        chat_type: str = "supergroup",
        is_monitored: bool = True,
        title: str | None = "Group",
        username: str | None = None,
        bot_status: str = "administrator",
        bot_status_at: datetime | None = None,
        last_event_at: datetime | None = None,
    ) -> Chat:
        chat_id = _random_chat_id()
        async with alert_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_chats.insert()
                    .values(
                        chat_id=chat_id,
                        chat_type=chat_type,
                        title=title,
                        username=username,
                        is_monitored=is_monitored,
                        bot_status=bot_status,
                        bot_status_at=bot_status_at,
                        last_event_at=last_event_at,
                    )
                    .returning(telegram_chats.c.id)
                )
            ).scalar_one()
            await session.commit()
        return Chat(id=row_id, chat_id=chat_id)

    return _insert


@pytest_asyncio.fixture
async def source_chat(insert_chat) -> Chat:
    """A monitored supergroup: where the subjects live."""
    chat: Chat = await insert_chat(title="Course group")
    return chat


async def clear_destination(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.is_alert_destination.is_(True))
            .values(is_alert_destination=False)
        )
        await session.commit()


@pytest_asyncio.fixture
async def destination_chat(
    alert_session_factory: async_sessionmaker[AsyncSession], insert_chat
) -> AsyncIterator[Chat]:
    """The alert group: unmonitored, flagged. Any stale flag is cleared first (D1)."""
    await clear_destination(alert_session_factory)
    chat: Chat = await insert_chat(title="Moderators", is_monitored=False, bot_status="member")
    async with alert_session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.id == chat.id)
            .values(is_alert_destination=True)
        )
        await session.commit()
    try:
        yield chat
    finally:
        await clear_destination(alert_session_factory)


@dataclass(frozen=True)
class Moderator:
    moderator_id: int
    telegram_user_id: int  # telegram_users surrogate
    tg_user_id: int  # platform id
    display_name: str


@pytest_asyncio.fixture
async def insert_moderator(
    alert_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[..., Any]]:
    """A declared moderator with an identity, declared `DECLARED_AGO`. `team_chat` adds a current
    membership in that chat from the same instant. Written directly: `open_assignment` refuses a
    start before the moderator's own `created_at`, which `now()` would set.

    Every membership added here is ended at teardown: a chat left with two current primaries
    would stop a later downgrade below `0011` from rebuilding its one-primary index."""
    memberships: list[int] = []

    async def _insert(
        *,
        display_name: str = "Moderator",
        team_chat: Chat | None = None,
        is_active: bool = True,
        declared_at: datetime | None = None,
    ) -> Moderator:
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
        async with alert_session_factory() as session:
            since = declared_at or (
                (await session.execute(sa.select(sa.func.now()))).scalar_one() - DECLARED_AGO
            )
            telegram_user_id = (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=tg_user_id, display_name=display_name)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
            moderator_id = (
                await session.execute(
                    moderators.insert()
                    .values(
                        telegram_user_id=telegram_user_id,
                        display_name=display_name,
                        is_active=is_active,
                        created_at=since,
                    )
                    .returning(moderators.c.id)
                )
            ).scalar_one()
            if team_chat is not None:
                memberships.append(
                    (
                        await session.execute(
                            moderator_group_assignments.insert()
                            .values(
                                telegram_chat_id=team_chat.id,
                                moderator_id=moderator_id,
                                assignment_role="primary",
                                valid_from=since,
                            )
                            .returning(moderator_group_assignments.c.id)
                        )
                    ).scalar_one()
                )
            await session.commit()
        return Moderator(
            moderator_id=moderator_id,
            telegram_user_id=telegram_user_id,
            tg_user_id=tg_user_id,
            display_name=display_name,
        )

    try:
        yield _insert
    finally:
        if memberships:
            async with alert_session_factory() as session:
                await session.execute(
                    moderator_group_assignments.update()
                    .where(
                        moderator_group_assignments.c.id.in_(memberships),
                        moderator_group_assignments.c.valid_to.is_(None),
                    )
                    .values(valid_to=sa.func.now())
                )
                await session.commit()


@pytest_asyncio.fixture
async def moderator(insert_moderator, source_chat: Chat) -> Moderator:
    """An active moderator on the source chat's team."""
    mod: Moderator = await insert_moderator(display_name="Sara", team_chat=source_chat)
    return mod


# --- rules ---


async def purge_rules(
    session_factory: async_sessionmaker[AsyncSession], rule_ids: list[int]
) -> None:
    """Removes rules with their alerts and those alerts' button acts. Tests only: in production a
    fired rule is never deleted (FR-514) and an act is never removed."""
    if not rule_ids:
        return
    async with session_factory() as session:
        alert_ids = sa.select(alerts.c.id).where(alerts.c.alert_rule_id.in_(rule_ids))
        await session.execute(
            moderation_actions.delete().where(moderation_actions.c.alert_id.in_(alert_ids))
        )
        await session.execute(alerts.delete().where(alerts.c.alert_rule_id.in_(rule_ids)))
        await session.execute(alert_rules.delete().where(alert_rules.c.id.in_(rule_ids)))
        await session.commit()


@pytest_asyncio.fixture
async def make_rule(
    alert_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[..., Any]]:
    """Inserts one `alert_rules` row and returns its id. Enabled by default, with `enabled_at`
    `DECLARED_AGO` back so subjects placed in the past qualify after it (FR-515); pass
    `enabled_at` to test that boundary. A stale global rule for the same trigger (a crashed run)
    is purged first."""
    created: list[int] = []

    async def _make(**fields: Any) -> int:
        values: dict[str, Any] = {"is_enabled": True, **fields}
        async with alert_session_factory() as session:
            if "enabled_at" not in values and values["is_enabled"]:
                values["enabled_at"] = (
                    await session.execute(sa.select(sa.func.now()))
                ).scalar_one() - DECLARED_AGO
            if values.get("telegram_chat_id") is None:
                stale = (
                    await session.execute(
                        sa.select(alert_rules.c.id).where(
                            alert_rules.c.trigger == values["trigger"],
                            alert_rules.c.telegram_chat_id.is_(None),
                        )
                    )
                ).scalars().all()
                if stale:
                    await session.rollback()
                    await purge_rules(alert_session_factory, list(stale))
        async with alert_session_factory() as session:
            rule_id = (
                await session.execute(
                    alert_rules.insert().values(**values).returning(alert_rules.c.id)
                )
            ).scalar_one()
            await session.commit()
        created.append(rule_id)
        return rule_id

    try:
        yield _make
    finally:
        await purge_rules(alert_session_factory, created)


# --- scripted Telegram ---


@dataclass
class ScriptedTelegram:
    """Records every Bot API call and answers it. A scripted entry for a method is consumed in
    order; with none left, the method's default answers. An entry is one of:

    - a `dict`/`bool`/`list`: a 200 with that `result`;
    - `(status, description)` or `(status, description, parameters)`: an error response;
    - an `httpx` exception instance: raised as the transport failure.
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    scripted: dict[str, list[Any]] = field(default_factory=dict)
    sleeps: list[float] = field(default_factory=list)
    _next_message_id: int = 1000
    client: TelegramClient | None = None

    def script(self, method: str, *responses: Any) -> None:
        self.scripted.setdefault(method, []).extend(responses)

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [params for name, params in self.calls if name == method]

    def _default(self, method: str, params: dict[str, Any]) -> Any:
        if method == "sendMessage":
            self._next_message_id += 1
            return {
                "message_id": self._next_message_id,
                "chat": {"id": params.get("chat_id")},
                "date": 0,
            }
        if method == "editMessageText":
            return {"message_id": params.get("message_id"), "chat": {"id": params.get("chat_id")}}
        if method == "getChatMember":
            return {"status": "member"}
        return True

    def handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        params: dict[str, Any] = json.loads(request.content or b"{}")
        self.calls.append((method, params))
        queue = self.scripted.get(method) or []
        entry = queue.pop(0) if queue else self._default(method, params)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, tuple):
            status, description, *rest = entry
            body: dict[str, Any] = {
                "ok": False,
                "error_code": status,
                "description": description,
            }
            if rest:
                body["parameters"] = rest[0]
            return httpx.Response(status, json=body)
        return httpx.Response(200, json={"ok": True, "result": entry})


@pytest.fixture
def scripted_telegram() -> ScriptedTelegram:
    scripted = ScriptedTelegram()

    async def _no_sleep(seconds: float) -> None:
        scripted.sleeps.append(seconds)

    scripted.client = TelegramClient(
        "test-token",
        base_url="https://telegram.invalid",
        transport=httpx.MockTransport(scripted.handle),
        sleep=_no_sleep,
    )
    return scripted


# --- subjects ---


@pytest_asyncio.fixture
def insert_message(
    alert_session_factory: async_sessionmaker[AsyncSession], bot_id: int
):
    """One captured `message` update and its `telegram_messages` row. The update's payload carries
    `text` (or `caption`), the first-posted words the excerpt reads (D-TG-221)."""

    async def _insert(
        chat: Chat,
        *,
        sent_at: datetime,
        text: str | None = "When is the exam?",
        caption: str | None = None,
        media_kind: str | None = None,
        telegram_user_id: int | None = None,
        message_id: int | None = None,
        text_purged_at: datetime | None = None,
    ) -> int:
        resolved_message_id = message_id or random.randint(1, 2_000_000_000)
        body: dict[str, Any] = {
            "message_id": resolved_message_id,
            "chat": {"id": chat.chat_id, "type": "supergroup"},
            "date": int(sent_at.timestamp()),
        }
        if text is not None:
            body["text"] = text
        if caption is not None:
            body["caption"] = caption
        if media_kind is not None:
            body[media_kind] = {}
        stored_text = text if text is not None else caption
        async with alert_session_factory() as session:
            update_row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=bot_id,
                        update_id=random.randint(10_000_000, 2_000_000_000),
                        update_type="message",
                        chat_id=chat.chat_id,
                        payload={"update_id": 0, "message": body},
                    )
                    .returning(telegram_updates.c.id)
                )
            ).scalar_one()
            await session.execute(
                telegram_messages.insert().values(
                    telegram_chat_id=chat.id,
                    message_id=resolved_message_id,
                    telegram_user_id=telegram_user_id,
                    sent_at=sent_at,
                    original_text=stored_text,
                    normalized_text=normalize(stored_text) if stored_text else None,
                    media_kind=media_kind,
                    text_purged_at=text_purged_at,
                    source_update_id=update_row_id,
                )
            )
            await session.commit()
        return resolved_message_id

    return _insert


@pytest_asyncio.fixture
async def insert_item(
    alert_session_factory: async_sessionmaker[AsyncSession], insert_message
) -> AsyncIterator[Callable[..., Any]]:
    """An `attention_items` row (`source='operator'`) anchored on a fresh message sent at
    `opened_at`. Returns the item id.

    Every item still open at teardown is expired: the database is shared, and a recent open item
    left behind would sit on the first page of the panel's Live Attention Queue in its own tests."""
    created: list[int] = []

    async def _insert(
        chat: Chat,
        *,
        opened_at: datetime,
        status: str = "open",
        text: str | None = "When is the exam?",
        **message_fields: Any,
    ) -> int:
        message_id = await insert_message(chat, sent_at=opened_at, text=text, **message_fields)
        async with alert_session_factory() as session:
            item_id = (
                await session.execute(
                    sa.text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, status) "
                        "VALUES (:chat, :message, :opened_at, 'operator', :status) RETURNING id"
                    ),
                    {
                        "chat": chat.id,
                        "message": message_id,
                        "opened_at": opened_at,
                        "status": status,
                    },
                )
            ).scalar_one()
            await session.commit()
        created.append(int(item_id))
        return int(item_id)

    try:
        yield _insert
    finally:
        if created:
            async with alert_session_factory() as session:
                await session.execute(
                    sa.text(
                        "UPDATE attention_items SET status = 'expired', closed_at = now(), "
                        "close_reason = 'expired' WHERE id = ANY(:ids) AND status = 'open'"
                    ),
                    {"ids": created},
                )
                await session.commit()


@pytest_asyncio.fixture
def insert_incident(alert_session_factory: async_sessionmaker[AsyncSession], insert_message):
    """A `moderation_incidents` row anchored on a fresh message. `opened_at` defaults to
    `detected_at`. Returns the incident id."""

    async def _insert(
        chat: Chat,
        *,
        detected_at: datetime,
        opened_at: datetime | None = None,
        category: str = "SPAM_OR_AD",
        severity: str = "medium",
        source: str = "operator",
        text: str | None = "Buy followers now",
        **message_fields: Any,
    ) -> int:
        sent_at = (opened_at or detected_at) - timedelta(minutes=1)
        message_id = await insert_message(chat, sent_at=sent_at, text=text, **message_fields)
        async with alert_session_factory() as session:
            incident_id = (
                await session.execute(
                    sa.text(
                        "INSERT INTO moderation_incidents "
                        "(telegram_chat_id, telegram_message_id, opened_at, detected_at, "
                        " source, opened_by_user_id, category, severity) "
                        "VALUES (:chat, :message, :opened_at, :detected_at, "
                        " :source, :opened_by, :category, :severity) RETURNING id"
                    ),
                    {
                        "chat": chat.id,
                        "message": message_id,
                        "opened_at": opened_at or detected_at,
                        "detected_at": detected_at,
                        "source": source,
                        "opened_by": 1 if source == "operator" else None,
                        "category": category,
                        "severity": severity,
                    },
                )
            ).scalar_one()
            await session.commit()
        return int(incident_id)

    return _insert


@pytest_asyncio.fixture
def insert_update(alert_session_factory: async_sessionmaker[AsyncSession], bot_id: int):
    """One captured update of any kind (e.g. a `callback_query`), `body` shaped as the Bot API
    sends it. Returns the `telegram_updates` surrogate id."""

    async def _insert(kind: str, body: dict[str, Any], *, chat_id: int | None = None) -> int:
        update_id = random.randint(10_000_000, 2_000_000_000)
        async with alert_session_factory() as session:
            row_id = (
                await session.execute(
                    telegram_updates.insert()
                    .values(
                        bot_id=bot_id,
                        update_id=update_id,
                        update_type=kind,
                        chat_id=chat_id,
                        payload={"update_id": update_id, kind: body},
                    )
                    .returning(telegram_updates.c.id)
                )
            ).scalar_one()
            await session.commit()
        return int(row_id)

    return _insert


@pytest_asyncio.fixture
def fetch_alerts(alert_session_factory: async_sessionmaker[AsyncSession]):
    """Every alert for one subject, oldest first."""

    async def _fetch(subject_type: str, subject_id: int) -> list[dict[str, Any]]:
        async with alert_session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(alerts)
                    .where(alerts.c.subject_type == subject_type, alerts.c.subject_id == subject_id)
                    .order_by(alerts.c.id)
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    return _fetch


@pytest_asyncio.fixture
def insert_alert(alert_session_factory: async_sessionmaker[AsyncSession]):
    """One `alerts` row written directly, for delivery, press and refresh tests that should not
    depend on the evaluator. Returns its id."""

    async def _insert(
        *,
        rule_id: int,
        chat: Chat,
        subject_type: str,
        subject_id: int,
        trigger: str,
        repeat_index: int = 0,
        episode_at: datetime | None = None,
        qualified_at: datetime | None = None,
        **fields: Any,
    ) -> int:
        async with alert_session_factory() as session:
            now = (await session.execute(sa.select(sa.func.now()))).scalar_one()
            alert_id = (
                await session.execute(
                    alerts.insert()
                    .values(
                        alert_rule_id=rule_id,
                        trigger=trigger,
                        telegram_chat_id=chat.id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        episode_at=episode_at,
                        repeat_index=repeat_index,
                        dedupe_key=dedupe_key(
                            rule_id, subject_type, subject_id, episode_at, repeat_index
                        ),
                        qualified_at=qualified_at or now,
                        **{"rule_values": {}, **fields},
                    )
                    .returning(alerts.c.id)
                )
            ).scalar_one()
            await session.commit()
        return int(alert_id)

    return _insert


@pytest_asyncio.fixture
def insert_act(alert_session_factory: async_sessionmaker[AsyncSession], insert_update):
    """One `moderation_actions` row written directly. A captured kind gets a fresh captured update
    for its `source_update_id` (`ck_actions_provenance`); a `panel_*` kind gets none. Returns the
    action id."""

    async def _insert(
        chat: Chat,
        *,
        action_type: str,
        occurred_at: datetime,
        action_strength: str | None = None,
        actor: Moderator | None = None,
        alert_id: int | None = None,
        incident_id: int | None = None,
        target_message_id: int | None = None,
        panel_user_id: int | None = None,
        note: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        source_update_id = None
        if not action_type.startswith("panel_"):
            source_update_id = await insert_update(
                "callback_query" if action_type.startswith("alert_") else "message_reaction",
                {},
                chat_id=chat.chat_id,
            )
        async with alert_session_factory() as session:
            action_id = (
                await session.execute(
                    moderation_actions.insert()
                    .values(
                        telegram_chat_id=chat.id,
                        action_type=action_type,
                        action_strength=action_strength,
                        occurred_at=occurred_at,
                        actor_telegram_user_id=actor.telegram_user_id if actor else None,
                        actor_moderator_id=actor.moderator_id if actor else None,
                        panel_user_id=panel_user_id,
                        target_message_id=target_message_id,
                        moderation_incident_id=incident_id,
                        source_update_id=source_update_id,
                        alert_id=alert_id,
                        note=note,
                        detail=detail or {},
                    )
                    .returning(moderation_actions.c.id)
                )
            ).scalar_one()
            await session.commit()
        return int(action_id)

    return _insert


# --- firing and ending (US1 onward) ---


@pytest_asyncio.fixture
def evaluate(alert_session_factory: async_sessionmaker[AsyncSession]):
    """One evaluation (F1-F8) in its own session, as the actor runs it."""

    async def _evaluate() -> Evaluation:
        async with alert_session_factory() as session:
            return await evaluate_once(session)

    return _evaluate


@pytest_asyncio.fixture
def end_item(alert_session_factory: async_sessionmaker[AsyncSession]):
    """Ends an open item the way each route records it (`attention_items` only):
    `answered_moderator`, `answered_member`, `dismissed` (by `moderator`'s linked panel account,
    or an unlinked one) or `expired`. Returns the end instant (the database's `now()`)."""

    async def _end(item_id: int, route: str, *, moderator: Moderator | None = None) -> datetime:
        if route in ("answered_moderator", "answered_member"):
            sql = (
                "UPDATE attention_items SET status = 'answered', first_response_at = now(), "
                "first_response_message_id = :response, first_response_kind = 'direct_reply', "
                "first_response_moderator_id = :moderator WHERE id = :id AND status = 'open' "
                "RETURNING first_response_at"
            )
        elif route == "dismissed":
            sql = (
                "UPDATE attention_items SET status = 'dismissed', closed_at = now(), "
                "closed_by_user_id = 1, closed_by_moderator_id = :moderator, "
                "close_reason = 'member_discussion' WHERE id = :id AND status = 'open' "
                "RETURNING closed_at"
            )
        elif route == "expired":
            sql = (
                "UPDATE attention_items SET status = 'expired', closed_at = now(), "
                "close_reason = 'expired' WHERE id = :id AND status = 'open' RETURNING closed_at"
            )
        else:
            raise ValueError(route)
        params: dict[str, Any] = {
            "id": item_id,
            "moderator": moderator.moderator_id if moderator else None,
            "response": random.randint(1, 2_000_000_000),
        }
        async with alert_session_factory() as session:
            ended_at: datetime = (await session.execute(text(sql), params)).scalar_one()
            await session.commit()
        return ended_at

    return _end


_MEMBERSHIP_KINDS = ("ban", "expulsion", "restriction")


@pytest_asyncio.fixture
async def end_incident(
    alert_session_factory: async_sessionmaker[AsyncSession], insert_update
) -> AsyncIterator[Callable[..., Any]]:
    """Records the act that moves an incident by one route, as its own writer would, and returns
    the act's instant (the database's `now()`). Routes:

    - `acknowledged`: a `panel_acknowledge` (still live);
    - `panel_resolve`, `panel_false_positive`: by panel account 7, linked to `moderator` when given;
    - `ban`, `expulsion`, `restriction`: against the anchor's sender (given one if the anchor has
      none), performed by `moderator`, or by `actor="anonymous"` (the anonymous administrator) or
      `actor="administrator"` (an undeclared group administrator);
    - `eyes`: `moderator`'s 👀 confirmation on the anchor;
    - `alert_handled`, `alert_false_positive`: `moderator`'s press on `alert_id`.

    A 👀 confirmation is removed at teardown: while one exists, revision 0012's downgrade refuses,
    and the shared database is downgraded by the migration tests.
    """
    eyes: list[int] = []

    async def _identity(session: AsyncSession, name: str) -> int:
        return int(
            (
                await session.execute(
                    telegram_users.insert()
                    .values(tg_user_id=random.randint(10_000_000, 2_000_000_000), display_name=name)
                    .returning(telegram_users.c.id)
                )
            ).scalar_one()
        )

    async def _end(
        incident_id: int,
        route: str,
        *,
        moderator: Moderator | None = None,
        actor: str = "moderator",
        alert_id: int | None = None,
    ) -> datetime:
        async with alert_session_factory() as session:
            incident = (
                await session.execute(
                    text(
                        "SELECT i.telegram_chat_id, i.telegram_message_id, m.telegram_user_id "
                        "FROM moderation_incidents i JOIN telegram_messages m "
                        "  ON m.telegram_chat_id = i.telegram_chat_id "
                        " AND m.message_id = i.telegram_message_id WHERE i.id = :id"
                    ),
                    {"id": incident_id},
                )
            ).mappings().one()
            chat_platform_id = (
                await session.execute(
                    sa.select(telegram_chats.c.chat_id).where(
                        telegram_chats.c.id == incident["telegram_chat_id"]
                    )
                )
            ).scalar_one()
        values: dict[str, Any] = {
            "telegram_chat_id": incident["telegram_chat_id"],
            "action_type": route,
            "occurred_at": sa.func.now(),
            "actor_moderator_id": moderator.moderator_id if moderator else None,
            "actor_telegram_user_id": moderator.telegram_user_id if moderator else None,
            "detail": {},
        }
        if route in ("acknowledged", "panel_resolve", "panel_false_positive"):
            values["action_type"] = "panel_acknowledge" if route == "acknowledged" else route
            values["action_strength"] = {
                "acknowledged": "acknowledgement",
                "panel_resolve": "confirmation",
                "panel_false_positive": None,
            }[route]
            values["panel_user_id"] = 7
            values["moderation_incident_id"] = incident_id
            values["actor_telegram_user_id"] = None
            if route != "acknowledged":
                values["note"] = "Checked by the team"
        elif route in _MEMBERSHIP_KINDS:
            values["action_strength"] = "enforcement"
            values["source_update_id"] = await insert_update(
                "chat_member", {}, chat_id=chat_platform_id
            )
            async with alert_session_factory() as session:
                subject = incident["telegram_user_id"]
                if subject is None:
                    subject = await _identity(session, "Student")
                    await session.execute(
                        telegram_messages.update()
                        .where(
                            telegram_messages.c.telegram_chat_id == incident["telegram_chat_id"],
                            telegram_messages.c.message_id == incident["telegram_message_id"],
                        )
                        .values(telegram_user_id=subject)
                    )
                values["subject_telegram_user_id"] = subject
                if actor != "moderator":
                    values["actor_moderator_id"] = None
                    values["actor_telegram_user_id"] = await _identity(
                        session, "Group" if actor == "anonymous" else "Admin"
                    )
                    values["actor_is_anonymous"] = actor == "anonymous"
                await session.commit()
        elif route == "eyes":
            values["action_type"] = "reaction"
            values["action_strength"] = "confirmation"
            values["target_message_id"] = incident["telegram_message_id"]
            values["source_update_id"] = await insert_update(
                "message_reaction", {}, chat_id=chat_platform_id
            )
            values["detail"] = {"added": [{"type": "emoji", "emoji": "👀"}]}
        elif route in ("alert_handled", "alert_false_positive"):
            values["action_strength"] = "confirmation" if route == "alert_handled" else None
            values["alert_id"] = alert_id
            values["moderation_incident_id"] = incident_id
            values["source_update_id"] = await insert_update("callback_query", {})
        else:
            raise ValueError(route)
        async with alert_session_factory() as session:
            action_id, occurred_at = (
                await session.execute(
                    moderation_actions.insert()
                    .values(**values)
                    .returning(moderation_actions.c.id, moderation_actions.c.occurred_at)
                )
            ).one()
            await session.commit()
        if route == "eyes":
            eyes.append(int(action_id))
        ended_at: datetime = occurred_at
        return ended_at

    try:
        yield _end
    finally:
        if eyes:
            async with alert_session_factory() as session:
                await session.execute(
                    moderation_actions.delete().where(moderation_actions.c.id.in_(eyes))
                )
                await session.commit()
