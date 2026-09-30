"""T033 — `derive_message` sends `classify_message` exactly once per newly-inserted message, after
its insert has committed; a duplicate delivery and `schedule_classification=False` send nothing;
a moderator's message is still sent (its exclusion is recorded by the classifier, not skipped
here); `rederive_chat` never schedules classification — history is classified only by the
catch-up command (`contracts/classification-pipeline.md` §1 Q1-Q2, FR-001, D-TG-149).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from app.application.moderation import messages as messages_module
from app.application.moderation.identities import map_moderator
from app.application.moderation.messages import derive_message
from app.infrastructure.models_moderation import telegram_updates
from app.scripts.rederive_chat import rederive_chat
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 4, 9, 0, 0, tzinfo=UTC)


async def _insert_message_update(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    bot_id: int,
    chat_id: int,
    message_id: int,
    sent_at: datetime = _SENT_AT,
    from_user: dict[str, Any] | None = None,
) -> int:
    body: dict[str, Any] = {
        "message_id": message_id,
        "date": int(sent_at.timestamp()),
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


def _patch_sends(monkeypatch: Any) -> dict[str, list[Any]]:
    sent: dict[str, list[Any]] = {"classify": [], "evaluate": [], "match": []}
    monkeypatch.setattr(
        messages_module.classify_message,
        "send",
        lambda *a, **kw: sent["classify"].append((a, kw)),
    )
    monkeypatch.setattr(
        messages_module.evaluate_attention,
        "send_with_options",
        lambda *a, **kw: sent["evaluate"].append((a, kw)),
    )
    monkeypatch.setattr(
        messages_module.match_response, "send", lambda *a, **kw: sent["match"].append((a, kw))
    )
    return sent


async def test_a_newly_derived_message_sends_classify_message_once_after_commit(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch)
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    inserted_id = await derive_message(classification_session_factory, update_row_id=update_row_id)

    assert inserted_id is not None
    assert sent["classify"] == [((chat_pk, 1, "live"), {})]


async def test_a_duplicate_delivery_sends_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch)
    await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    first = await derive_message(classification_session_factory, update_row_id=update_row_id)
    second = await derive_message(classification_session_factory, update_row_id=update_row_id)

    assert first is not None
    assert second is None
    assert len(sent["classify"]) == 1


async def test_a_moderators_message_is_still_sent(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch)
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

    inserted_id = await derive_message(classification_session_factory, update_row_id=update_row_id)

    assert inserted_id is not None
    assert sent["classify"] == [((chat_pk, 1, "live"), {})]
    assert len(sent["match"]) == 1


async def test_schedule_classification_false_sends_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch)
    await insert_chat(chat_id=classification_chat_id)
    update_row_id = await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    inserted_id = await derive_message(
        classification_session_factory,
        update_row_id=update_row_id,
        schedule_classification=False,
    )

    assert inserted_id is not None
    assert sent["classify"] == []


async def test_rederive_chat_sends_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    monkeypatch: Any,
) -> None:
    sent = _patch_sends(monkeypatch)
    await insert_chat(chat_id=classification_chat_id)
    await _insert_message_update(
        classification_session_factory,
        bot_id=classification_bot_id,
        chat_id=classification_chat_id,
        message_id=1,
    )

    report = await rederive_chat(classification_session_factory, chat_id=classification_chat_id)

    assert report.derived == 1
    assert sent["classify"] == []
