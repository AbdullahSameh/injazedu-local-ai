"""T044 — the model sees only the redacted, first-posted words: the provider receives exactly two
messages (`system` = `classify_v1.md`, `user` = the redacted text), phone numbers in every digit
system, emails, links (with and without a scheme) and handles are replaced, Latin words mixed into
Arabic survive untouched, and no sender, handle, id or timestamp ever reaches the request. With the
gateway's debugging capture on, `model_runs.request_payload` holds only the already-redacted text
(`contracts/classification-pipeline.md` §4 P2-P3, P5, FR-007, FR-008, SC-005).

⚠ Redaction tested on a bare string passes while the gateway's own capture stores the original —
only a real `AccountingWriter` with `capture_payloads=True` proves the boundary end to end.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.infrastructure.models import model_runs
from app.infrastructure.models_moderation import message_classifications
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 2, 5, 9, 0, 0, tzinfo=UTC)

_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "prompts" / "moderation" / "classify_v1.md"
)
_INSTRUCTION = _PROMPT_PATH.read_text(encoding="utf-8")

_LATIN_PHONE = "0501234567"
# Built from digit code points, not typed glyphs, so the fixture is exactly right: Arabic-Indic
# is U+0660 + d, Eastern Arabic-Indic is U+06F0 + d (`app/application/moderation/text.py` step 6).
_ARABIC_INDIC_PHONE = "".join(chr(0x0660 + int(d)) for d in "0552134567")
_EASTERN_PHONE = "".join(chr(0x06F0 + int(d)) for d in "0669876543")
_EMAIL = "student@example.com"
_URL_WITH_SCHEME = "https://example.com/join"
_URL_NO_SCHEME = "www.another-course.example"
_HANDLE = "@moderator123"
_SENDER_USERNAME = "definitely_not_redacted_username"

_ORIGINAL_TEXT = (
    f"اتصل بي على {_LATIN_PHONE} او {_ARABIC_INDIC_PHONE} او {_EASTERN_PHONE} "
    f"وراسلني على {_EMAIL} وزور {_URL_WITH_SCHEME} او {_URL_NO_SCHEME} "
    f"وتواصل مع {_HANDLE} thanks for the help شكرا جزيلا"
)

_VALID_ANSWER = {
    "category": "QUESTION_COURSE",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.9,
}


async def _fetch_request_payload(
    session_factory: async_sessionmaker[AsyncSession], *, model_run_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(model_runs.c.request_payload).where(model_runs.c.id == model_run_id)
            )
        ).one()
        return dict(row.request_payload)


async def test_provider_receives_only_redacted_text_and_capture_stores_only_redaction(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    sender_tg_user_id = random.randint(10_000_000, 2_000_000_000)
    user_pk = await insert_user(tg_user_id=sender_tg_user_id, username=_SENDER_USERNAME)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text=_ORIGINAL_TEXT,
    )
    gateway, calls = scripted_gateway(responses=[dict(_VALID_ANSWER)], capture_payloads=True)
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
    request = calls[0]
    assert len(request.messages) == 2
    system_message, user_message = request.messages
    assert system_message.role == "system"
    assert system_message.content == _INSTRUCTION
    assert user_message.role == "user"

    redacted = user_message.content
    assert redacted.count("«رقم»") == 3
    assert "«بريد»" in redacted
    assert redacted.count("«رابط»") == 2
    assert "«مستخدم»" in redacted
    assert "thanks for the help" in redacted

    for original in (
        _LATIN_PHONE,
        _ARABIC_INDIC_PHONE,
        _EASTERN_PHONE,
        _EMAIL,
        _URL_WITH_SCHEME,
        _URL_NO_SCHEME,
        _HANDLE,
    ):
        assert original not in redacted

    for leak in (_SENDER_USERNAME, str(sender_tg_user_id), str(int(_SENT_AT.timestamp()))):
        assert leak not in system_message.content
        assert leak not in redacted

    async with classification_session_factory() as session:
        prediction_row = (
            await session.execute(
                sa.select(message_classifications.c.model_run_id).where(
                    message_classifications.c.telegram_chat_id == chat_pk,
                    message_classifications.c.telegram_message_id == 1,
                )
            )
        ).one()
    assert prediction_row.model_run_id is not None

    payload = await _fetch_request_payload(
        classification_session_factory, model_run_id=prediction_row.model_run_id
    )
    payload_messages = payload["messages"]
    assert len(payload_messages) == 2
    assert payload_messages[0]["content"] == _INSTRUCTION
    stored_user_content = payload_messages[1]["content"]
    assert stored_user_content == redacted
    for original in (
        _LATIN_PHONE,
        _ARABIC_INDIC_PHONE,
        _EASTERN_PHONE,
        _EMAIL,
        _URL_WITH_SCHEME,
        _URL_NO_SCHEME,
        _HANDLE,
        _SENDER_USERNAME,
    ):
        assert original not in stored_user_content
