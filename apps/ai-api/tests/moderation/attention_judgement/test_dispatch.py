"""T029 — dispatch (`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §1 J1,
§9 L1).

`derive_message` sends `judge_attention(chat_pk, message_id)` for every newly inserted message,
**before** `classify_message` and under the same condition: once each, after the insert has
committed. A duplicate delivery sends neither. A moderator's message sends both (each judgement
records the moderator's exclusion itself). `schedule_classification=False` and `rederive_chat`
send neither: only the live dispatch judges.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from app.application.moderation import messages as messages_module
from app.application.moderation.identities import map_moderator
from app.application.moderation.messages import derive_message
from app.infrastructure.models_moderation import telegram_messages, telegram_updates
from app.scripts.rederive_chat import rederive_chat
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 10, 3, 9, 0, 0, tzinfo=UTC)


async def _insert_message_update(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    chat_id: int,
    message_id: int,
    from_user: dict[str, Any] | None = None,
) -> int:
    body: dict[str, Any] = {
        "message_id": message_id,
        "date": int(_SENT_AT.timestamp()),
        "text": "hi",
    }
    if from_user is not None:
        body["from"] = from_user
    async with session_factory() as session:
        row_id = (
            await session.execute(
                telegram_updates.insert()
                .values(
                    bot_id=bot_id,
                    update_id=random.randint(10_000_000, 2_000_000_000),
                    update_type="message",
                    chat_id=chat_id,
                    payload={"message": body},
                )
                .returning(telegram_updates.c.id)
            )
        ).scalar_one()
        await session.commit()
        return row_id


def _patch_sends(monkeypatch: Any, database_url: str) -> list[tuple[str, tuple[Any, ...], bool]]:
    """Records every model dispatch in order, as `(actor, args, row_committed)`. Whether the row
    is visible is checked from a separate connection at the moment of the send, which is what
    "after commit" means for a worker picking the message up."""
    sent: list[tuple[str, tuple[Any, ...], bool]] = []

    def _recorder(name: str) -> Any:
        def _send(*args: Any, **_kwargs: Any) -> None:
            chat_pk, message_id = args[0], args[1]
            engine = sa.create_engine(database_url)
            try:
                with engine.connect() as conn:
                    committed = (
                        conn.execute(
                            sa.select(sa.func.count())
                            .select_from(telegram_messages)
                            .where(
                                telegram_messages.c.telegram_chat_id == chat_pk,
                                telegram_messages.c.message_id == message_id,
                            )
                        ).scalar_one()
                        == 1
                    )
            finally:
                engine.dispose()
            sent.append((name, args, committed))

        return _send

    monkeypatch.setattr(messages_module.judge_attention, "send", _recorder("judge_attention"))
    monkeypatch.setattr(messages_module.classify_message, "send", _recorder("classify_message"))
    monkeypatch.setattr(
        messages_module.evaluate_attention, "send_with_options", lambda *a, **k: None
    )
    monkeypatch.setattr(messages_module.match_response, "send", lambda *a, **k: None)
    return sent


async def test_judge_attention_is_sent_once_before_classify_message_after_commit(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_test_database_url: str,
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch, classification_test_database_url)
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    inserted_id = await derive_message(classification_session_factory, update_row_id=update_row_id)

    assert inserted_id is not None
    assert sent == [
        ("judge_attention", (chat_pk, 1), True),
        ("classify_message", (chat_pk, 1, "live"), True),
    ]


async def test_a_duplicate_delivery_sends_neither(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_test_database_url: str,
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch, classification_test_database_url)
    await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    assert await derive_message(classification_session_factory, update_row_id=update_row_id)
    assert await derive_message(classification_session_factory, update_row_id=update_row_id) is None

    assert [name for name, _, _ in sent] == ["judge_attention", "classify_message"]


async def test_a_moderators_message_sends_both(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_test_database_url: str,
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch, classification_test_database_url)
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    tg_user_id = random.randint(10_000_000, 2_000_000_000)
    await map_moderator(classification_session_factory, tg_user_id=tg_user_id, display_name="Mod")
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
        from_user={"id": tg_user_id, "is_bot": False, "first_name": "Mod"},
    )

    assert await derive_message(classification_session_factory, update_row_id=update_row_id)

    assert [(name, args) for name, args, _ in sent] == [
        ("judge_attention", (chat_pk, 1)),
        ("classify_message", (chat_pk, 1, "live")),
    ]


async def test_schedule_classification_false_sends_neither(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_test_database_url: str,
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch, classification_test_database_url)
    await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    assert await derive_message(
        classification_session_factory,
        update_row_id=update_row_id,
        schedule_classification=False,
    )

    assert sent == []


async def test_rederive_chat_sends_neither(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_test_database_url: str,
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    """L1: history is never judged."""
    sent = _patch_sends(monkeypatch, classification_test_database_url)
    await insert_chat(chat_id=classification_chat_id)
    await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    report = await rederive_chat(classification_session_factory, chat_id=classification_chat_id)

    assert report.derived == 1
    assert sent == []
