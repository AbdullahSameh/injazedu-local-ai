"""The database invariants of revision `0005`, attempted directly in SQL rather than through the
application (data-model.md §1 Constraints) — each is a claim about the store, not the app.

Each test opens one transaction, inserts the prerequisite rows and a valid item where needed,
attempts the violating statement inside the same transaction, asserts it raises, then rolls the
whole transaction back — leaving the shared `injaz_ai_test` database untouched regardless of
outcome.
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


def test_duplicate_anchor_within_one_chat_is_rejected(attention_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)
            conn.execute(
                text(
                    "INSERT INTO attention_items "
                    "(telegram_chat_id, telegram_message_id, opened_at, source, rule_version) "
                    "VALUES (:chat, 1, now(), 'rule', 1)"
                ),
                {"chat": chat_pk},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, "
                        "rule_version) VALUES (:chat, 1, now(), 'rule', 1)"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_anchor_on_a_never_stored_message_is_rejected(attention_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
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
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, "
                        "rule_version) VALUES (:chat, 999, now(), 'rule', 1)"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_answered_status_with_no_first_response_at_is_rejected(
    attention_sync_engine: Engine,
) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, "
                        "rule_version, status) "
                        "VALUES (:chat, 1, now(), 'rule', 1, 'answered')"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_first_response_at_not_after_opened_at_is_rejected(
    attention_sync_engine: Engine,
) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, "
                        "rule_version, status, first_response_at, first_response_message_id, "
                        "first_response_kind) "
                        "VALUES (:chat, 1, now(), 'rule', 1, 'answered', now(), 1, "
                        "'direct_reply')"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_rule_source_with_no_rule_version_is_rejected(attention_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source) "
                        "VALUES (:chat, 1, now(), 'rule')"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()


def test_operator_source_with_a_rule_version_is_rejected(attention_sync_engine: Engine) -> None:
    chat_id = -_rand_id()

    with attention_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk, _ = _insert_chat_and_message(conn, chat_id=chat_id, message_id=1)

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO attention_items "
                        "(telegram_chat_id, telegram_message_id, opened_at, source, "
                        "rule_version) VALUES (:chat, 1, now(), 'operator', 1)"
                    ),
                    {"chat": chat_pk},
                )
        finally:
            trans.rollback()
