"""The database invariants of revision `0006`, attempted directly in SQL rather than through the
application (`data-model.md` §1-§2 Constraints) — each is a claim about the store, not the app.

Each test opens one transaction, inserts the prerequisite rows and a valid row where needed,
attempts the violating statement inside the same transaction, asserts it raises, then rolls the
whole transaction back — leaving the shared `injaz_ai_test` database untouched regardless of
outcome. Mirrors `tests/moderation/attention/test_db_invariants.py`.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


def _insert_chat_and_message(conn, *, chat_id: int, message_id: int) -> tuple[int, int]:
    bot_id = _rand_id()
    update_id = _rand_id()
    chat_pk = conn.execute(
        text(
            "INSERT INTO telegram_chats (chat_id, chat_type) "
            "VALUES (:chat_id, 'group') RETURNING id"
        ),
        {"chat_id": chat_id},
    ).scalar_one()
    update_pk = conn.execute(
        text(
            "INSERT INTO telegram_updates (bot_id, update_id, update_type, payload) "
            "VALUES (:bot_id, :update_id, 'message', '{}'::jsonb) RETURNING id"
        ),
        {"bot_id": bot_id, "update_id": update_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO telegram_messages "
            "(telegram_chat_id, message_id, sent_at, source_update_id) "
            "VALUES (:chat, :message_id, now(), :update)"
        ),
        {"chat": chat_pk, "message_id": message_id, "update": update_pk},
    )
    return chat_pk, update_pk


def _insert_captured_update(conn, *, update_type: str = "chat_member") -> int:
    return conn.execute(
        text(
            "INSERT INTO telegram_updates (bot_id, update_id, update_type, payload) "
            "VALUES (:bot_id, :update_id, :update_type, '{}'::jsonb) RETURNING id"
        ),
        {"bot_id": _rand_id(), "update_id": _rand_id(), "update_type": update_type},
    ).scalar_one()


def _insert_user(conn, *, tg_user_id: int | None = None) -> int:
    return conn.execute(
        text(
            "INSERT INTO telegram_users (tg_user_id) VALUES (:tg_user_id) RETURNING id"
        ),
        {"tg_user_id": tg_user_id if tg_user_id is not None else _rand_id()},
    ).scalar_one()


def _insert_incident(
    conn,
    *,
    chat_pk: int,
    message_id: int,
    category: str = "SPAM_OR_AD",
    severity: str = "low",
    source: str = "operator",
    opened_by_user_id: int | None = 1,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO moderation_incidents "
            "(telegram_chat_id, telegram_message_id, opened_at, detected_at, source, "
            "opened_by_user_id, category, severity) "
            "VALUES (:chat, :message_id, now(), now(), :source, :opened_by, :category, "
            ":severity) RETURNING id"
        ),
        {
            "chat": chat_pk,
            "message_id": message_id,
            "source": source,
            "opened_by": opened_by_user_id,
            "category": category,
            "severity": severity,
        },
    ).scalar_one()


# --- moderation_incidents ---


def test_duplicate_anchor_within_one_chat_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            _insert_incident(conn, chat_pk=chat_pk, message_id=1)

            with pytest.raises(IntegrityError):
                _insert_incident(conn, chat_pk=chat_pk, message_id=1)
        finally:
            trans.rollback()


def test_anchor_on_a_never_stored_message_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk = conn.execute(
                text(
                    "INSERT INTO telegram_chats (chat_id, chat_type) "
                    "VALUES (:chat_id, 'group') RETURNING id"
                ),
                {"chat_id": chat_id},
            ).scalar_one()

            with pytest.raises(IntegrityError):
                _insert_incident(conn, chat_pk=chat_pk, message_id=999)
        finally:
            trans.rollback()


def test_category_outside_the_vocabulary_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                _insert_incident(conn, chat_pk=chat_pk, message_id=1, category="NOT_A_CATEGORY")
        finally:
            trans.rollback()


def test_severity_outside_the_vocabulary_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                _insert_incident(conn, chat_pk=chat_pk, message_id=1, severity="critical")
        finally:
            trans.rollback()


def test_operator_source_with_no_opener_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                _insert_incident(conn, chat_pk=chat_pk, message_id=1, opened_by_user_id=None)
        finally:
            trans.rollback()


def test_operator_source_with_a_classification_id_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_incidents "
                        "(telegram_chat_id, telegram_message_id, opened_at, detected_at, "
                        "source, opened_by_user_id, category, severity, "
                        "message_classification_id) "
                        "VALUES (:chat, 1, now(), now(), 'operator', 1, 'SPAM_OR_AD', 'low', 42)"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


# --- moderation_actions ---


def test_reaction_with_a_strength_other_than_acknowledgement_is_rejected(
    incident_sync_engine: Engine,
) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            moderator_id = _seed_moderator(conn)
            update_pk = _insert_captured_update(conn, update_type="message_reaction")

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "actor_moderator_id, target_message_id, source_update_id) "
                        "VALUES (:chat, 'reaction', 'enforcement', now(), :moderator, 1, :update)"
                    ),
                    {"chat": chat_pk, "moderator": moderator_id, "update": update_pk},
                )
        finally:
            trans.rollback()


def test_reaction_with_no_actor_moderator_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            update_pk = _insert_captured_update(conn, update_type="message_reaction")

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "target_message_id, source_update_id) "
                        "VALUES (:chat, 'reaction', 'acknowledgement', now(), 1, :update)"
                    ),
                    {"chat": chat_pk, "update": update_pk},
                )
        finally:
            trans.rollback()


@pytest.mark.parametrize("action_type", ["reversal", "panel_false_positive"])
def test_a_kind_that_never_carries_a_strength_is_rejected_with_one(
    incident_sync_engine: Engine, action_type: str
) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            subject_id = _insert_user(conn)

            if action_type == "reversal":
                update_pk = _insert_captured_update(conn, update_type="chat_member")
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO moderation_actions "
                            "(telegram_chat_id, action_type, action_strength, occurred_at, "
                            "subject_telegram_user_id, source_update_id) "
                            "VALUES (:chat, 'reversal', 'enforcement', now(), :subject, :update)"
                        ),
                        {"chat": chat_pk, "subject": subject_id, "update": update_pk},
                    )
            else:
                incident_id = _insert_incident(conn, chat_pk=chat_pk, message_id=1)
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO moderation_actions "
                            "(telegram_chat_id, action_type, action_strength, occurred_at, "
                            "panel_user_id, moderation_incident_id, note) "
                            "VALUES (:chat, 'panel_false_positive', 'confirmation', now(), 1, "
                            ":incident, 'not a violation')"
                        ),
                        {"chat": chat_pk, "incident": incident_id},
                    )
        finally:
            trans.rollback()


def test_panel_resolve_with_an_empty_note_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            incident_id = _insert_incident(conn, chat_pk=chat_pk, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "panel_user_id, moderation_incident_id, note) "
                        "VALUES (:chat, 'panel_resolve', 'confirmation', now(), 1, :incident, '  ')"
                    ),
                    {"chat": chat_pk, "incident": incident_id},
                )
        finally:
            trans.rollback()


def test_panel_kind_with_no_incident_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "panel_user_id) "
                        "VALUES (:chat, 'panel_acknowledge', 'acknowledgement', now(), 1)"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_panel_kind_with_a_source_update_id_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            incident_id = _insert_incident(conn, chat_pk=chat_pk, message_id=1)
            update_pk = _insert_captured_update(conn)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "panel_user_id, moderation_incident_id, source_update_id) "
                        "VALUES (:chat, 'panel_acknowledge', 'acknowledgement', now(), 1, "
                        ":incident, :update)"
                    ),
                    {"chat": chat_pk, "incident": incident_id, "update": update_pk},
                )
        finally:
            trans.rollback()


def test_captured_kind_with_no_source_update_id_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            subject_id = _insert_user(conn)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "subject_telegram_user_id) "
                        "VALUES (:chat, 'ban', 'enforcement', now(), :subject)"
                    ),
                    {"chat": chat_pk, "subject": subject_id},
                )
        finally:
            trans.rollback()


def test_membership_kind_with_no_subject_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            update_pk = _insert_captured_update(conn)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "source_update_id) "
                        "VALUES (:chat, 'ban', 'enforcement', now(), :update)"
                    ),
                    {"chat": chat_pk, "update": update_pk},
                )
        finally:
            trans.rollback()


def test_a_second_row_for_the_same_source_update_is_rejected(incident_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with incident_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            subject_id = _insert_user(conn)
            update_pk = _insert_captured_update(conn)
            conn.execute(
                text(
                    "INSERT INTO moderation_actions "
                    "(telegram_chat_id, action_type, action_strength, occurred_at, "
                    "subject_telegram_user_id, source_update_id) "
                    "VALUES (:chat, 'ban', 'enforcement', now(), :subject, :update)"
                ),
                {"chat": chat_pk, "subject": subject_id, "update": update_pk},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderation_actions "
                        "(telegram_chat_id, action_type, action_strength, occurred_at, "
                        "subject_telegram_user_id, source_update_id) "
                        "VALUES (:chat, 'restriction', 'enforcement', now(), :subject, :update)"
                    ),
                    {"chat": chat_pk, "subject": subject_id, "update": update_pk},
                )
        finally:
            trans.rollback()


def _seed_moderator(conn) -> int:
    identity_id = _insert_user(conn)
    return conn.execute(
        text(
            "INSERT INTO moderators (telegram_user_id, display_name) "
            "VALUES (:identity, 'Mod') RETURNING id"
        ),
        {"identity": identity_id},
    ).scalar_one()
