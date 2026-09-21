"""The four database invariants of revision `0004`, attempted directly in SQL rather than
through the application — FR-069 is a claim about the store, not the app (SC-031).

Each test opens one transaction, inserts a valid row, attempts the violating second insert
inside the same transaction (so the uniqueness/exclusion check sees the first row), asserts it
raises, then rolls the whole transaction back — leaving the shared `injaz_ai_test` database
untouched regardless of outcome.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


def test_duplicate_chat_and_message_id_is_rejected(actors_sync_engine: Engine) -> None:
    chat_id = -_rand_id()
    bot_id = _rand_id()
    update_id = _rand_id()

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
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
                    "VALUES (:chat, 1, now(), :update)"
                ),
                {"chat": chat_pk, "update": update_pk},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO telegram_messages "
                        "(telegram_chat_id, message_id, sent_at, source_update_id) "
                        "VALUES (:chat, 1, now(), :update)"
                    ),
                    {"chat": chat_pk, "update": update_pk},
                )
        finally:
            trans.rollback()


def test_duplicate_tg_user_id_is_rejected(actors_sync_engine: Engine) -> None:
    tg_user_id = _rand_id()

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("INSERT INTO telegram_users (tg_user_id, is_bot) VALUES (:id, false)"),
                {"id": tg_user_id},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO telegram_users (tg_user_id, is_bot) VALUES (:id, false)"
                    ),
                    {"id": tg_user_id},
                )
        finally:
            trans.rollback()


def test_two_moderators_on_one_identity_is_rejected(actors_sync_engine: Engine) -> None:
    tg_user_id = _rand_id()

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            user_pk = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'First Mapping')"
                ),
                {"user": user_pk},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderators (telegram_user_id, display_name) "
                        "VALUES (:user, 'Second Mapping')"
                    ),
                    {"user": user_pk},
                )
        finally:
            trans.rollback()


def test_second_current_primary_for_one_chat_is_rejected(actors_sync_engine: Engine) -> None:
    chat_id = -_rand_id()
    tg_user_id_a = _rand_id()
    tg_user_id_b = _rand_id()

    with actors_sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            chat_pk = conn.execute(
                text(
                    "INSERT INTO telegram_chats (chat_id, chat_type) "
                    "VALUES (:chat_id, 'group') RETURNING id"
                ),
                {"chat_id": chat_id},
            ).scalar_one()
            user_a = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id_a},
            ).scalar_one()
            user_b = conn.execute(
                text(
                    "INSERT INTO telegram_users (tg_user_id, is_bot) "
                    "VALUES (:id, false) RETURNING id"
                ),
                {"id": tg_user_id_b},
            ).scalar_one()
            moderator_a = conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'Moderator A') RETURNING id"
                ),
                {"user": user_a},
            ).scalar_one()
            moderator_b = conn.execute(
                text(
                    "INSERT INTO moderators (telegram_user_id, display_name) "
                    "VALUES (:user, 'Moderator B') RETURNING id"
                ),
                {"user": user_b},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO moderator_group_assignments "
                    "(telegram_chat_id, moderator_id, assignment_role, valid_from) "
                    "VALUES (:chat, :moderator, 'primary', now())"
                ),
                {"chat": chat_pk, "moderator": moderator_a},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO moderator_group_assignments "
                        "(telegram_chat_id, moderator_id, assignment_role, valid_from) "
                        "VALUES (:chat, :moderator, 'primary', now())"
                    ),
                    {"chat": chat_pk, "moderator": moderator_b},
                )
        finally:
            trans.rollback()
