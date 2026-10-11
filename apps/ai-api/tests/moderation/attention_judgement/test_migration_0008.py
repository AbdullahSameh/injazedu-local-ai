"""Revision `0008` (TG-M5.3, `data-model.md` §1-§4, §6; `tasks.md` T015): the two attention tables,
`attention_items`' second link and `ck_attention_ai_link`, and the `attention` model role.

Two kinds of test, both against `injaz_ai_test` only (Principle II):
- **The lifecycle** (modelled on `tests/moderation/classification/test_migration_0007.py`): each
  starts from, and ends at, an empty schema. The downgrade must drop exactly what the upgrade
  added: the schema at `0007` before the upgrade and after the downgrade are compared object by
  object, with no attention rows present.
- **The planted violations:** each runs in its own transaction on a schema at head, seeds a minimal
  valid baseline directly in SQL, attempts one invalid write, asserts the constraint psycopg names
  (`exc.orig.diag.constraint_name`), and rolls back. Nothing is re-derived on the test side.
"""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

APP_DIR = Path(__file__).resolve().parents[3]
BASELINE_REVISION = "0007"
HEAD_REVISION = "0008"

_NEW_TABLES = ("message_attention_judgements", "message_attention_attempts")
_PRIOR_TABLES = (
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
_PRIOR_VIEWS = ("moderation_incident_evidence", "moderation_incident_state")
_NEW_INDEXES = (
    "uq_attention_judgement_current",
    "ix_attention_judgements_profile",
    "uq_attention_attempt_exclusion",
    "ix_attention_attempts_message",
)
_NEW_CONSTRAINTS = (
    ("message_attention_judgements", "fk_attention_judgement_message"),
    ("message_attention_judgements", "uq_attention_judgement_identity"),
    ("message_attention_judgements", "ck_attention_judgement_intent"),
    ("message_attention_judgements", "ck_attention_judgement_path"),
    ("message_attention_attempts", "fk_attention_attempt_message"),
    ("message_attention_attempts", "ck_attention_attempt_path"),
    ("message_attention_attempts", "ck_attention_attempt_outcome"),
    ("message_attention_attempts", "ck_attention_attempt_reason"),
    ("message_attention_attempts", "ck_attention_attempt_profile"),
    ("attention_items", "fk_attention_judgement"),
    ("attention_items", "ck_attention_ai_link"),
)


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
            for view in _PRIOR_VIEWS:
                conn.execute(text(f"DROP VIEW IF EXISTS {view} CASCADE"))
            for table in (*_NEW_TABLES, *_PRIOR_TABLES):
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


def _relation_exists(test_url: str, name: str) -> bool:
    return _scalar(test_url, f"SELECT to_regclass('{name}')") is not None


def _index_exists(test_url: str, name: str) -> bool:
    return bool(
        _scalar(test_url, "SELECT count(*) FROM pg_indexes WHERE indexname = :n", {"n": name})
    )


def _column_exists(test_url: str, table: str, column: str) -> bool:
    return bool(
        _scalar(
            test_url,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c",
            {"t": table, "c": column},
        )
    )


def _constraint_exists(test_url: str, table: str, name: str) -> bool:
    return bool(
        _scalar(
            test_url,
            "SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = :t AND c.conname = :n",
            {"t": table, "n": name},
        )
    )


def _role_check_definition(test_url: str) -> str:
    definition: str = _scalar(
        test_url,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'ck_model_profiles_role'",
    )
    return definition


def _schema_fingerprint(test_url: str) -> dict[str, frozenset[tuple[str, ...]]]:
    """Every table, column, constraint and index in `public`, each with its definition — the
    schema compared before the upgrade and after the downgrade."""
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
def test_empty_to_0008(test_url: str) -> None:
    command.upgrade(_alembic_config(test_url), HEAD_REVISION)

    assert _current_revision(test_url) == HEAD_REVISION
    for table in _NEW_TABLES:
        assert _relation_exists(test_url, table), f"{table} missing after upgrade"
    assert _column_exists(test_url, "attention_items", "attention_judgement_id")
    for table, name in _NEW_CONSTRAINTS:
        assert _constraint_exists(test_url, table, name), f"{name} missing on {table}"
    for index_name in _NEW_INDEXES:
        assert _index_exists(test_url, index_name), f"{index_name} missing after upgrade"
    assert "'attention'" in _role_check_definition(test_url)


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
    assert "'attention'" not in _role_check_definition(test_url)

    command.upgrade(cfg, HEAD_REVISION)
    assert _current_revision(test_url) == HEAD_REVISION


# --- The planted violations ---------------------------------------------------------------------


@pytest.fixture
def conn(test_url: str) -> Iterator[Connection]:
    """One transaction on a schema at head, always rolled back."""
    if not _relation_exists(test_url, "message_attention_judgements"):
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


class _Seed:
    """A chat, a user and two bare messages (`a` and `b`); one active `attention` profile (the
    only one, in this transaction) and one inactive `moderation` profile, with builders for a
    judgement, an attempt, a prediction and an item. Every value is an explicit keyword."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        conn.execute(
            text(
                "UPDATE model_profiles SET is_active = false "
                "WHERE role = 'attention' AND is_active = true"
            )
        )
        self.chat_pk: int = conn.execute(
            text(
                "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
                "VALUES (:chat_id, 'group', true) RETURNING id"
            ),
            {"chat_id": -random.randint(10_000_000, 2_000_000_000)},
        ).scalar_one()
        self.attention_profile_id = self.insert_profile("attention", active=True)
        self.moderation_profile_id = self.insert_profile("moderation", active=False)
        self.user_pk: int = conn.execute(
            text("INSERT INTO telegram_users (tg_user_id) VALUES (:tg) RETURNING id"),
            {"tg": random.randint(10_000_000, 2_000_000_000)},
        ).scalar_one()
        self.message_a_id = 1
        self.message_b_id = 2
        self._insert_message(self.message_a_id)
        self._insert_message(self.message_b_id)

    def insert_profile(self, role: str, *, active: bool) -> int:
        profile_id: int = self.conn.execute(
            text(
                "INSERT INTO model_profiles (name, provider, model, role, params, is_active) "
                "VALUES (:name, 'fake', 'fake-model', :role, '{}'::jsonb, :active) RETURNING id"
            ),
            {"name": f"m8-test-{uuid.uuid4().hex[:12]}", "role": role, "active": active},
        ).scalar_one()
        return profile_id

    def _insert_message(self, message_id: int) -> None:
        update_pk = self.conn.execute(
            text(
                "INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload) "
                "VALUES (:bot_id, :update_id, 'message', :chat_id, :payload) RETURNING id"
            ),
            {
                "bot_id": random.randint(10_000_000, 2_000_000_000),
                "update_id": random.randint(10_000_000, 2_000_000_000),
                "chat_id": self.chat_pk,
                "payload": '{"message": {}}',
            },
        ).scalar_one()
        self.conn.execute(
            text(
                "INSERT INTO telegram_messages "
                "(telegram_chat_id, message_id, telegram_user_id, sent_at, is_service, "
                " is_from_moderator, original_text, normalized_text, source_update_id) VALUES "
                "(:chat_pk, :message_id, :user_pk, now(), false, false, 'hi', 'hi', :update_pk)"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "user_pk": self.user_pk,
                "update_pk": update_pk,
            },
        )

    def insert_judgement(
        self,
        message_id: int,
        *,
        intent: str = "asking",
        needs_response: bool = True,
        path: str = "live",
    ) -> int:
        judgement_id: int = self.conn.execute(
            text(
                "INSERT INTO message_attention_judgements "
                "(telegram_chat_id, telegram_message_id, model_profile_id, prompt_version, "
                " intent, needs_response, path) VALUES "
                "(:chat_pk, :message_id, :profile_id, 'attention_test', :intent, "
                " :needs_response, :path) RETURNING id"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "profile_id": self.attention_profile_id,
                "intent": intent,
                "needs_response": needs_response,
                "path": path,
            },
        ).scalar_one()
        return judgement_id

    def insert_attempt(
        self,
        message_id: int,
        *,
        outcome: str,
        reason: str,
        model_profile_id: int | None,
    ) -> None:
        self.conn.execute(
            text(
                "INSERT INTO message_attention_attempts "
                "(telegram_chat_id, telegram_message_id, path, outcome, reason, "
                " model_profile_id) VALUES "
                "(:chat_pk, :message_id, 'live', :outcome, :reason, :profile_id)"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "outcome": outcome,
                "reason": reason,
                "profile_id": model_profile_id,
            },
        )

    def insert_prediction(self, message_id: int) -> int:
        prediction_id: int = self.conn.execute(
            text(
                "INSERT INTO message_classifications "
                "(telegram_chat_id, telegram_message_id, model_profile_id, prompt_version, "
                " taxonomy_version, category, needs_response, needs_moderation, severity, "
                " confidence, path, route, confidence_floor, incident_threshold) VALUES "
                "(:chat_pk, :message_id, :profile_id, 'classify_v2', 1, 'QUESTION_COURSE', "
                " true, false, 'none', 0.900, 'live', 'none', 0.600, 0.850) RETURNING id"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "profile_id": self.moderation_profile_id,
            },
        ).scalar_one()
        return prediction_id

    def insert_item(
        self,
        message_id: int,
        *,
        source: str,
        message_classification_id: int | None = None,
        attention_judgement_id: int | None = None,
    ) -> None:
        self.conn.execute(
            text(
                "INSERT INTO attention_items "
                "(telegram_chat_id, telegram_message_id, opened_at, source, rule_version, "
                " message_classification_id, attention_judgement_id) VALUES "
                "(:chat_pk, :message_id, now(), :source, :rule_version, "
                " :classification_id, :judgement_id)"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "source": source,
                "rule_version": 1 if source == "rule" else None,
                "classification_id": message_classification_id,
                "judgement_id": attention_judgement_id,
            },
        )


@pytest.fixture
def seed(conn: Connection) -> _Seed:
    return _Seed(conn)


@contextmanager
def _expect_violation(constraint_name: str) -> Iterator[None]:
    with pytest.raises(IntegrityError) as exc_info:
        yield
    assert exc_info.value.orig is not None
    assert exc_info.value.orig.diag.constraint_name == constraint_name, (
        f"expected {constraint_name!r}, got {exc_info.value.orig.diag.constraint_name!r}"
    )


def test_an_unknown_intent_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_attention_judgement_intent"):
        seed.insert_judgement(seed.message_a_id, intent="question", needs_response=True)


def test_an_unknown_path_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_attention_judgement_path"):
        seed.insert_judgement(seed.message_a_id, path="x")


def test_a_second_current_judgement_for_one_message_is_refused(seed: _Seed) -> None:
    seed.insert_judgement(seed.message_a_id)
    with _expect_violation("uq_attention_judgement_current"):
        seed.insert_judgement(seed.message_a_id, intent="social", needs_response=False)


def test_a_second_exclusion_for_one_message_is_refused(seed: _Seed) -> None:
    seed.insert_attempt(
        seed.message_a_id, outcome="excluded", reason="media", model_profile_id=None
    )
    with _expect_violation("uq_attention_attempt_exclusion"):
        seed.insert_attempt(
            seed.message_a_id, outcome="excluded", reason="rule_opens", model_profile_id=None
        )


def test_a_failure_without_a_profile_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_attention_attempt_profile"):
        seed.insert_attempt(
            seed.message_a_id, outcome="failed", reason="model_timeout", model_profile_id=None
        )


def test_an_exclusion_with_a_profile_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_attention_attempt_profile"):
        seed.insert_attempt(
            seed.message_a_id,
            outcome="excluded",
            reason="media",
            model_profile_id=seed.attention_profile_id,
        )


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("excluded", "unknown_reason"),
        ("failed", "unknown_reason"),
        # The classification's failure reason that has no meaning here: there is no confidence.
        ("failed", "confidence_out_of_range"),
        # An exclusion reason recorded as a failure, and the reverse.
        ("failed", "rule_opens"),
        ("excluded", "model_timeout"),
    ],
)
def test_a_reason_outside_its_outcome_vocabulary_is_refused(
    seed: _Seed, outcome: str, reason: str
) -> None:
    profile_id = seed.attention_profile_id if outcome == "failed" else None
    with _expect_violation("ck_attention_attempt_reason"):
        seed.insert_attempt(
            seed.message_a_id, outcome=outcome, reason=reason, model_profile_id=profile_id
        )


def test_a_model_item_with_no_link_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_attention_ai_link"):
        seed.insert_item(seed.message_a_id, source="ai")


def test_a_model_item_with_both_links_is_refused(seed: _Seed) -> None:
    prediction_id = seed.insert_prediction(seed.message_a_id)
    judgement_id = seed.insert_judgement(seed.message_a_id)
    with _expect_violation("ck_attention_ai_link"):
        seed.insert_item(
            seed.message_a_id,
            source="ai",
            message_classification_id=prediction_id,
            attention_judgement_id=judgement_id,
        )


def test_a_rule_item_with_a_judgement_link_is_refused(seed: _Seed) -> None:
    judgement_id = seed.insert_judgement(seed.message_a_id)
    with _expect_violation("ck_attention_ai_link"):
        seed.insert_item(seed.message_a_id, source="rule", attention_judgement_id=judgement_id)


def test_an_operator_item_with_a_classification_link_is_refused(seed: _Seed) -> None:
    prediction_id = seed.insert_prediction(seed.message_a_id)
    with _expect_violation("ck_attention_ai_link"):
        seed.insert_item(
            seed.message_a_id, source="operator", message_classification_id=prediction_id
        )


def test_a_second_active_attention_profile_is_refused(seed: _Seed) -> None:
    with _expect_violation("uq_model_profiles_one_active_per_role"):
        seed.insert_profile("attention", active=True)


# --- What the revision accepts ------------------------------------------------------------------


def test_the_attention_role_and_a_rule_opens_exclusion_are_accepted(seed: _Seed) -> None:
    seed.insert_profile("attention", active=False)
    seed.insert_attempt(
        seed.message_a_id, outcome="excluded", reason="rule_opens", model_profile_id=None
    )


def test_a_model_item_with_exactly_one_link_is_accepted(seed: _Seed) -> None:
    """Both eras: a TG-M5.1 item linked to its prediction, a TG-M5.3 item to its judgement."""
    seed.insert_item(
        seed.message_a_id,
        source="ai",
        message_classification_id=seed.insert_prediction(seed.message_a_id),
    )
    seed.insert_item(
        seed.message_b_id,
        source="ai",
        attention_judgement_id=seed.insert_judgement(seed.message_b_id),
    )
