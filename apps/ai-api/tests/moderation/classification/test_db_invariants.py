"""Revision `0007`'s twelve planted violations (research probe 9), plus the two extra
`ck_attempt_reason` directions — each rejected **directly in SQL**, by the constraint named for
it, never by a test-side re-derivation of eligibility or routing (pipeline contract N7).

⚠ **Probe 9 E2/E3**: a plain foreign key on `message_classifications.id` would accept a link to
*another message's* prediction. Only the composite `(id, telegram_chat_id, telegram_message_id)`
key — `uq_classification_identity`, `fk_incident_classification`, `fk_incident_prompted_by` —
refuses that. `test_a_model_opened_incident_may_not_cite_another_messages_prediction` and
`test_an_operator_flag_may_not_be_prompted_by_another_messages_prediction` are the two that would
pass against a plain FK and only fail against the composite one.

Each test opens its own transaction, seeds a minimal valid baseline directly against the tables
(no ORM, no `classify_one` — this package's own pure/application code is untested here on
purpose), attempts one invalid insert, and asserts the exact constraint psycopg reports via
`exc.orig.diag.constraint_name`. The transaction is rolled back on teardown regardless of outcome,
so no test's baseline (including a moderation profile it activates) ever reaches another test.
"""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

_PROFILE_ID_UNSET = object()  # "use the seed's own profile" vs. an explicit None (no model)


@pytest.fixture
def db_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def conn(db_url: str) -> Iterator[Connection]:
    """One transaction per test, always rolled back — including a moderation profile this file
    activates for its own baseline, so it never collides with another file's session-scoped
    seeded profile (`conftest.py`'s `classification_seeded_profile`)."""
    engine = create_engine(db_url)
    connection = engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()
        engine.dispose()


class _Seed:
    """A chat, one `moderation` profile (the only active one, in this transaction), one user,
    and two bare messages — `message_a` and `message_b` — with builders for a prediction, an
    attempt or an incident anchored on either. Nothing here computes eligibility or routing;
    every value is an explicit keyword the test controls."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        # Neutralise any other active `moderation` profile this connection might otherwise see
        # (none should be visible — it is another transaction's uncommitted work — but this is
        # the transaction's own baseline, not a dependency on isolation semantics).
        conn.execute(
            text(
                "UPDATE model_profiles SET is_active = false "
                "WHERE role = 'moderation' AND is_active = true"
            )
        )
        chat_id = -random.randint(10_000_000, 2_000_000_000)
        self.chat_pk: int = conn.execute(
            text(
                "INSERT INTO telegram_chats (chat_id, chat_type, is_monitored) "
                "VALUES (:chat_id, 'group', true) RETURNING id"
            ),
            {"chat_id": chat_id},
        ).scalar_one()
        self.profile_id: int = conn.execute(
            text(
                "INSERT INTO model_profiles "
                "(name, provider, model, role, params, is_active) VALUES "
                "(:name, 'fake', 'fake-moderation', 'moderation', '{}'::jsonb, true) "
                "RETURNING id"
            ),
            {"name": f"inv-test-{uuid.uuid4().hex[:12]}"},
        ).scalar_one()
        tg_user_id = random.randint(10_000_000, 2_000_000_000)
        self.user_pk: int = conn.execute(
            text("INSERT INTO telegram_users (tg_user_id) VALUES (:tg) RETURNING id"),
            {"tg": tg_user_id},
        ).scalar_one()
        self.message_a_id = 1
        self.message_b_id = 2
        self._insert_message(self.message_a_id)
        self._insert_message(self.message_b_id)

    def _insert_message(self, message_id: int) -> None:
        update_pk = self.conn.execute(
            text(
                "INSERT INTO telegram_updates "
                "(bot_id, update_id, update_type, chat_id, payload) VALUES "
                "(:bot_id, :update_id, 'message', :chat_id, :payload) RETURNING id"
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

    def insert_prediction(
        self,
        message_id: int,
        *,
        category: str = "SPAM_OR_AD",
        severity: str = "low",
        needs_response: bool = False,
        needs_moderation: bool = True,
        confidence: str = "0.720",
        path: str = "live",
        route: str = "possible_violation",
        route_reason: str | None = "uncertain",
        confidence_floor: str | None = "0.600",
        incident_threshold: str | None = "0.850",
        is_current: bool = True,
        model_profile_id: int | None = None,
    ) -> int:
        return self.conn.execute(
            text(
                "INSERT INTO message_classifications ("
                " telegram_chat_id, telegram_message_id, model_profile_id, prompt_version,"
                " taxonomy_version, category, needs_response, needs_moderation, severity,"
                " confidence, path, route, route_reason, confidence_floor, incident_threshold,"
                " is_current"
                ") VALUES ("
                " :chat_pk, :message_id, :model_profile_id, 'classify_v1', 1, :category,"
                " :needs_response, :needs_moderation, :severity, :confidence, :path, :route,"
                " :route_reason, :confidence_floor, :incident_threshold, :is_current"
                ") RETURNING id"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "model_profile_id": model_profile_id or self.profile_id,
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
            },
        ).scalar_one()

    def insert_attempt(
        self,
        message_id: int,
        *,
        outcome: str,
        reason: str,
        path: str = "live",
        model_profile_id: int | None | Any = _PROFILE_ID_UNSET,
    ) -> None:
        if model_profile_id is _PROFILE_ID_UNSET:
            # ck_attempt_profile: a model_profile_id only when the outcome is a failure.
            resolved_profile_id = self.profile_id if outcome == "failed" else None
        else:
            resolved_profile_id = model_profile_id
        self.conn.execute(
            text(
                "INSERT INTO message_classification_attempts ("
                " telegram_chat_id, telegram_message_id, path, outcome, reason, model_profile_id"
                ") VALUES (:chat_pk, :message_id, :path, :outcome, :reason, :model_profile_id)"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "path": path,
                "outcome": outcome,
                "reason": reason,
                "model_profile_id": resolved_profile_id,
            },
        )

    def insert_incident(
        self,
        message_id: int,
        *,
        source: str,
        opened_by_user_id: int | None = None,
        message_classification_id: int | None = None,
        prompted_by_classification_id: int | None = None,
        category: str = "SPAM_OR_AD",
        severity: str = "low",
    ) -> None:
        self.conn.execute(
            text(
                "INSERT INTO moderation_incidents ("
                " telegram_chat_id, telegram_message_id, opened_at, detected_at, source,"
                " opened_by_user_id, category, severity, message_classification_id,"
                " prompted_by_classification_id"
                ") VALUES ("
                " :chat_pk, :message_id, now(), now(), :source, :opened_by_user_id, :category,"
                " :severity, :message_classification_id, :prompted_by_classification_id"
                ")"
            ),
            {
                "chat_pk": self.chat_pk,
                "message_id": message_id,
                "source": source,
                "opened_by_user_id": opened_by_user_id,
                "category": category,
                "severity": severity,
                "message_classification_id": message_classification_id,
                "prompted_by_classification_id": prompted_by_classification_id,
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


# --- research probe 9's twelve planted violations -----------------------------------------------


def test_a_model_opened_incident_needs_a_prediction(seed: _Seed) -> None:
    with _expect_violation("ck_incident_ai_link"):
        seed.insert_incident(seed.message_a_id, source="ai")


def test_an_operator_flag_may_not_be_prompted_by_another_messages_prediction(seed: _Seed) -> None:
    prediction_b = seed.insert_prediction(seed.message_b_id)
    with _expect_violation("fk_incident_prompted_by"):
        seed.insert_incident(
            seed.message_a_id,
            source="operator",
            opened_by_user_id=seed.user_pk,
            prompted_by_classification_id=prediction_b,
        )


def test_a_model_opened_incident_may_not_cite_another_messages_prediction(seed: _Seed) -> None:
    prediction_a = seed.insert_prediction(seed.message_a_id)
    with _expect_violation("fk_incident_classification"):
        seed.insert_incident(
            seed.message_b_id, source="ai", message_classification_id=prediction_a
        )


def test_a_model_opened_incident_may_not_carry_a_prompted_by(seed: _Seed) -> None:
    prediction_a = seed.insert_prediction(seed.message_a_id)
    with _expect_violation("ck_incident_prompted_by"):
        seed.insert_incident(
            seed.message_a_id,
            source="ai",
            message_classification_id=prediction_a,
            prompted_by_classification_id=prediction_a,
        )


def test_a_second_current_prediction_is_refused(seed: _Seed) -> None:
    seed.insert_prediction(seed.message_a_id)
    with _expect_violation("uq_classification_current"):
        seed.insert_prediction(seed.message_a_id)


def test_confidence_out_of_range_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_classification_confidence"):
        seed.insert_prediction(seed.message_a_id, confidence="1.3")


def test_a_possible_violation_needs_a_reason(seed: _Seed) -> None:
    with _expect_violation("ck_classification_route_reason"):
        seed.insert_prediction(
            seed.message_a_id, route="possible_violation", route_reason=None
        )


def test_a_catch_up_prediction_may_not_route_to_incident(seed: _Seed) -> None:
    with _expect_violation("ck_classification_route_path"):
        seed.insert_prediction(
            seed.message_a_id,
            path="catch_up",
            route="incident",
            route_reason=None,
            confidence_floor=None,
            incident_threshold=None,
        )


def test_a_second_active_moderation_profile_is_refused(seed: _Seed) -> None:
    with _expect_violation("uq_model_profiles_one_active_per_role"):
        seed.conn.execute(
            text(
                "INSERT INTO model_profiles "
                "(name, provider, model, role, params, is_active) VALUES "
                "(:name, 'fake', 'fake-moderation-2', 'moderation', '{}'::jsonb, true)"
            ),
            {"name": f"inv-test-second-{uuid.uuid4().hex[:12]}"},
        )


def test_a_duplicate_exclusion_is_refused(seed: _Seed) -> None:
    seed.insert_attempt(seed.message_a_id, outcome="excluded", reason="service")
    with _expect_violation("uq_attempt_exclusion"):
        seed.insert_attempt(seed.message_a_id, outcome="excluded", reason="moderator")


def test_a_failure_must_name_a_model(seed: _Seed) -> None:
    with _expect_violation("ck_attempt_profile"):
        seed.insert_attempt(
            seed.message_a_id, outcome="failed", reason="model_timeout", model_profile_id=None
        )


def test_a_floor_above_its_threshold_is_refused(seed: _Seed) -> None:
    with _expect_violation("ck_classification_thresholds"):
        seed.insert_prediction(
            seed.message_a_id, confidence_floor="0.900", incident_threshold="0.850"
        )


# --- the two extra ck_attempt_reason directions -------------------------------------------------


def test_an_exclusion_may_not_carry_a_failure_reason(seed: _Seed) -> None:
    with _expect_violation("ck_attempt_reason"):
        seed.insert_attempt(
            seed.message_a_id, outcome="excluded", reason="model_truncated", model_profile_id=None
        )


def test_a_failure_may_not_carry_an_exclusion_reason(seed: _Seed) -> None:
    with _expect_violation("ck_attempt_reason"):
        seed.insert_attempt(seed.message_a_id, outcome="failed", reason="no_text")
