"""T045 — the model reads the message's own captured event, never the stored row: once an
`edited_message` has been applied (`apply_edit` overwrites `telegram_messages.normalized_text`),
classifying the message still sends the **first-posted** words — the edited words appear nowhere in
the request (`contracts/classification-pipeline.md` §4 P1, FR-006).

⚠ Finding 5: a classifier that reads `telegram_messages` instead of the captured event passes every
test that never edits a message; only editing before classifying exposes it.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.application.moderation.messages import apply_edit
from app.application.moderation.text import normalize
from app.infrastructure.models_moderation import telegram_updates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 6, 9, 0, 0, tzinfo=UTC)

_FIRST_POSTED_TEXT = "سؤال عن موعد المحاضرة القادمة"
_EDITED_TEXT = "كلام مختلف تماما بعد التعديل"

_VALID_ANSWER = {
    "category": "QUESTION_COURSE",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.9,
}


async def test_classification_uses_the_first_posted_words_not_the_edited_ones(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    user_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text=_FIRST_POSTED_TEXT,
    )

    async with classification_session_factory() as session:
        edited_update_id = (
            await session.execute(
                telegram_updates.insert()
                .values(
                    bot_id=classification_bot_id,
                    update_id=random.randint(10_000_000, 2_000_000_000),
                    update_type="edited_message",
                    chat_id=classification_chat_id,
                    payload={
                        "edited_message": {
                            "message_id": 1,
                            "date": int(_SENT_AT.timestamp()) + 60,
                            "text": _EDITED_TEXT,
                        }
                    },
                )
                .returning(telegram_updates.c.id)
            )
        ).scalar_one()
        await session.commit()
    rows_matched = await apply_edit(classification_session_factory, update_row_id=edited_update_id)
    assert rows_matched == 1

    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)])
    registry = ProfileRegistry(classification_session_factory)

    outcome = await classify_one(
        classification_session_factory,
        gateway,
        registry,
        classification_redis,
        classification_settings,
        chat_pk=chat_pk,
        message_id=1,
        path="live",
    )

    assert outcome == "classified"
    assert len(calls) == 1
    user_message = calls[0].messages[1]
    # `redact` runs on `normalize`'s output, not the raw original (P1-P2) — compare against the
    # same normalised form the pipeline itself sends, not the literal Arabic (letters fold: e.g.
    # ة→ه), so this assertion actually proves *which event's words* reached the model.
    assert normalize(_FIRST_POSTED_TEXT) in user_message.content
    assert normalize(_EDITED_TEXT) not in user_message.content
    assert _EDITED_TEXT not in user_message.content
