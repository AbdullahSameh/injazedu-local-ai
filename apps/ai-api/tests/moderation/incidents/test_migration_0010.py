"""Revision `0010` (`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 1): the
link rule's incident source and the advert guard's route reason.

- `moderation_incidents.source` gains `'rule'`, with `rule_version` set exactly when it is.
- `message_classifications.route_reason` gains `'no_contact_signal'`.

Modelled on `tests/moderation/actors/test_migration_0009.py`, against `injaz_ai_test` only
(Principle II): the lifecycle starts from, and ends at, an empty schema; the planted violations run
in one rolled-back transaction on a schema at head.
"""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

APP_DIR = Path(__file__).resolve().parents[3]
BASELINE_REVISION = "0009"
HEAD_REVISION = "0010"

_TABLES = (
    "message_attention_attempts",
    "message_attention_judgements",
    "message_classification_attempts",
    "message_classifications",
    "moderation_actions",
    "moderation_incidents",
    "attention_items",
    "moderator_group_assignments",
    "telegram_messages",
    "moderators",
    "telegram_users",
    "telegram_chats",
    "ingestion_gaps",
    "ingestion_state",
    "telegram_updates",
    "model_runs",
    "model_profiles",
    "users",
)
_VIEWS = ("moderation_incident_evidence", "moderation_incident_state")


def _alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return cfg


@pytest.fixture
def test_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _drop_all(test_url: str) -> None:
    engine = create_engine(test_url)
    try:
        with engine.begin() as conn:
            for view in _VIEWS:
                conn.execute(text(f"DROP VIEW IF EXISTS {view} CASCADE"))
            for table in _TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


@pytest.fixture
def empty_schema(test_url: str) -> Iterator[None]:
    """The lifecycle tests start from, and end at, an empty schema."""
    _drop_all(test_url)
    yield
    _drop_all(test_url)


def _scalar(test_url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()
    finally:
        engine.dispose()


def _current_revision(test_url: str) -> str | None:
    if _scalar(test_url, "SELECT to_regclass('alembic_version')") is None:
        return None
    revision: str | None = _scalar(test_url, "SELECT version_num FROM alembic_version")
    return revision


def _constraint_definition(test_url: str, table: str, name: str) -> str | None:
    definition: str | None = _scalar(
        test_url,
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :n",
        {"t": table, "n": name},
    )
    return definition


def _schema_fingerprint(test_url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every column, constraint and index in `public`, each with its definition."""
    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, "
                    "coalesce(column_default, '') FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            ).all()
            constraints = conn.execute(
                text(
                    "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) "
                    "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'public'"
                )
            ).all()
            indexes = conn.execute(
                text(
                    "SELECT tablename, indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public'"
                )
            ).all()
    finally:
        engine.dispose()
    return {
        "columns": frozenset(tuple(str(v) for v in row) for row in columns),
        "constraints": frozenset(tuple(str(v) for v in row) for row in constraints),
        "indexes": frozenset(tuple(str(v) for v in row) for row in indexes),
    }


# --- The lifecycle ------------------------------------------------------------------------------


@pytest.mark.usefixtures("empty_schema")
def test_empty_to_0010(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    source = _constraint_definition(test_url, "moderation_incidents", "ck_incident_source")
    assert source is not None and "'rule'" in source
    assert _constraint_definition(
        test_url, "moderation_incidents", "ck_incident_rule_version"
    ) is not None
    reason = _constraint_definition(
        test_url, "message_classifications", "ck_classification_route_reason"
    )
    assert reason is not None and "'no_contact_signal'" in reason


@pytest.mark.usefixtures("empty_schema")
def test_the_downgrade_drops_exactly_what_the_upgrade_added(test_url: str) -> None:
    cfg = _alembic_config(test_url)
    command.upgrade(cfg, BASELINE_REVISION)
    before = _schema_fingerprint(test_url)

    command.upgrade(cfg, HEAD_REVISION)
    assert _schema_fingerprint(test_url) != before

    command.downgrade(cfg, BASELINE_REVISION)
    assert _current_revision(test_url) == BASELINE_REVISION
    assert _schema_fingerprint(test_url) == before

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


# --- The planted violations ---------------------------------------------------------------------


@pytest.fixture
def conn(test_url: str) -> Iterator[Connection]:
    """One transaction on a schema at head, always rolled back."""
    if _constraint_definition(test_url, "moderation_incidents", "ck_incident_rule_version") is None:
        command.upgrade(_alembic_config(test_url), "head")
    engine = create_engine(test_url)
    connection = engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()
        engine.dispose()


def _message(conn: Connection) -> tuple[int, int]:
    chat_pk: int = conn.execute(
        text(
            "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
            "VALUES (:chat_id, 'group', true) RETURNING id"
        ),
        {"chat_id": -random.randint(10_000_000, 2_000_000_000)},
    ).scalar_one()
    update_pk = conn.execute(
        text(
            "INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload) "
            "VALUES (:bot_id, :update_id, 'message', :chat_id, '{}'::jsonb) RETURNING id"
        ),
        {
            "bot_id": random.randint(10_000_000, 2_000_000_000),
            "update_id": random.randint(10_000_000, 2_000_000_000),
            "chat_id": chat_pk,
        },
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO telegram_messages "
            "(telegram_chat_id, message_id, sent_at, is_service, is_from_moderator, "
            " source_update_id) VALUES (:chat_pk, 1, now(), false, false, :update_pk)"
        ),
        {"chat_pk": chat_pk, "update_pk": update_pk},
    )
    return chat_pk, 1


def _incident(conn: Connection, *, source: str, rule_version: int | None) -> None:
    chat_pk, message_id = _message(conn)
    conn.execute(
        text(
            "INSERT INTO moderation_incidents "
            "(telegram_chat_id, telegram_message_id, opened_at, detected_at, source, "
            " category, severity, rule_version) VALUES "
            "(:chat_pk, :message_id, now(), now(), :source, 'OTHER', 'low', :rule_version)"
        ),
        {
            "chat_pk": chat_pk,
            "message_id": message_id,
            "source": source,
            "rule_version": rule_version,
        },
    )


def test_a_rule_incident_with_its_version_is_accepted(conn: Connection) -> None:
    _incident(conn, source="rule", rule_version=1)


def test_a_rule_incident_needs_its_version(conn: Connection) -> None:
    with pytest.raises(IntegrityError) as exc:
        _incident(conn, source="rule", rule_version=None)

    assert exc.value.orig is not None
    assert exc.value.orig.diag.constraint_name == "ck_incident_rule_version"


def test_only_a_rule_incident_carries_a_version(conn: Connection) -> None:
    chat_pk, message_id = _message(conn)
    with pytest.raises(IntegrityError) as exc:
        conn.execute(
            text(
                "INSERT INTO moderation_incidents "
                "(telegram_chat_id, telegram_message_id, opened_at, detected_at, source, "
                " opened_by_user_id, category, severity, rule_version) VALUES "
                "(:chat_pk, :message_id, now(), now(), 'operator', 1, 'OTHER', 'low', 1)"
            ),
            {"chat_pk": chat_pk, "message_id": message_id},
        )

    assert exc.value.orig is not None
    assert exc.value.orig.diag.constraint_name == "ck_incident_rule_version"


def test_no_contact_signal_is_a_possible_violation_reason(conn: Connection) -> None:
    chat_pk, message_id = _message(conn)
    profile_id = conn.execute(
        text(
            "INSERT INTO model_profiles (name, provider, model, role, params, is_active) "
            "VALUES (:name, 'fake', 'fake-model', 'moderation', '{}'::jsonb, false) RETURNING id"
        ),
        {"name": f"m10-test-{uuid.uuid4().hex[:12]}"},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO message_classifications "
            "(telegram_chat_id, telegram_message_id, model_profile_id, prompt_version, "
            " taxonomy_version, category, needs_response, needs_moderation, severity, "
            " confidence, path, route, route_reason, confidence_floor, incident_threshold) "
            "VALUES (:chat_pk, :message_id, :profile_id, 'classify_v2', 1, 'SPAM_OR_AD', "
            " false, true, 'medium', 0.950, 'live', 'possible_violation', 'no_contact_signal', "
            " 0.600, 0.850)"
        ),
        {"chat_pk": chat_pk, "message_id": message_id, "profile_id": profile_id},
    )
