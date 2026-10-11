"""T027 — `judge_one`, the attention judgement's one write path
(`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §2-§4, §7 W1, §8; FR-307,
FR-311-FR-314).

- An eligible, rule-declined message gets exactly one immutable judgement: its intent, the stored
  `needs_response` from `needs_response_for`, the profile, the instruction's version, the call and
  `path='live'`. A replay records nothing more.
- A message whose own words open the rules (AE2), a moderator's message and an acknowledgement
  (AE1) get one `excluded` attempt and no model call, once only.
- A final gateway error records one `failed` attempt naming the profile; a transient one is
  re-raised for the task's retry and records nothing.
- A blank instruction, no active attention profile, or a claim held elsewhere: no call, no row.
- The request is `[system = the instruction, user = redact(first-posted text)]` (P1, Finding 5),
  and no log record carries the text (P2).

No attention instruction is frozen yet (D-TG-189), so every test passes a test-only instruction
through `instructions=` and sets its version with `model_copy`, which skips the allowlist validator.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway import (
    ModelTruncatedError,
    ProviderUnreachableError,
    StructuredOutputInvalidError,
)
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.attention_judgement import judge_one
from app.application.moderation.messages import apply_edit
from app.application.moderation.text import normalize, redact
from app.domain.moderation.attention_judgement import INTENTS, needs_response_for
from app.infrastructure.models_moderation import (
    message_attention_attempts,
    message_attention_judgements,
    telegram_updates,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENT_AT = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)

_PROMPT_VERSION = "attention_test"
_INSTRUCTIONS = {_PROMPT_VERSION: "TEST"}

# Synthetic and rule-declined: `evaluate([normalize(text)])` is false for each.
_DECLINED_TEXT = "بس الرابط بايظ"
_RULE_OPENING_TEXT = "متى موعد الاختبار؟"
_URL_TEXT = "بس الرابط بايظ https://example.com/join"
_FIRST_POSTED_TEXT = "سؤال عن موعد المحاضرة القادمة"
_EDITED_TEXT = "كلام مختلف تماما بعد التعديل"

_LOGGER_NAME = "app.application.moderation.attention_judgement"


def _settings(classification_settings: Any, *, prompt: str | None = _PROMPT_VERSION) -> Any:
    return classification_settings.model_copy(
        update={"moderation_attention_prompt_version": prompt}
    )


async def _judge(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int = 1,
) -> str:
    return await judge_one(
        session_factory,
        gateway,
        ProfileRegistry(session_factory),
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        instructions=_INSTRUCTIONS,
    )


async def _judgements(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int = 1
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(message_attention_judgements).where(
                    message_attention_judgements.c.telegram_chat_id == chat_pk,
                    message_attention_judgements.c.telegram_message_id == message_id,
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def _attempts(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int = 1
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(message_attention_attempts).where(
                    message_attention_attempts.c.telegram_chat_id == chat_pk,
                    message_attention_attempts.c.telegram_message_id == message_id,
                )
            )
        ).mappings().all()
        return [dict(row) for row in rows]


async def _member_message(
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    *,
    chat_id: int,
    text: str | None = _DECLINED_TEXT,
    **kwargs: Any,
) -> int:
    chat_pk = await insert_chat(chat_id=chat_id)
    user_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_SENT_AT,
        telegram_user_id=user_pk,
        original_text=text,
        **kwargs,
    )
    return chat_pk


@pytest.mark.parametrize("intent", INTENTS)
async def test_an_eligible_message_gets_one_judgement_with_full_provenance(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
    intent: str,
) -> None:
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    profile_id = await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": intent}])

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "judged"
    assert len(calls) == 1
    rows = await _judgements(classification_session_factory, chat_pk=chat_pk)
    assert len(rows) == 1
    row = rows[0]
    assert row["intent"] == intent
    assert row["needs_response"] is needs_response_for(intent)
    assert row["model_profile_id"] == profile_id
    assert row["prompt_version"] == _PROMPT_VERSION
    assert row["model_run_id"] is not None
    assert row["path"] == "live"
    assert row["is_current"] is True
    assert await _attempts(classification_session_factory, chat_pk=chat_pk) == []


async def test_a_replay_records_nothing_more(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}, {"intent": "social"}])
    settings = _settings(classification_settings)

    first = await _judge(
        classification_session_factory, gateway, classification_redis, settings, chat_pk=chat_pk
    )
    second = await _judge(
        classification_session_factory, gateway, classification_redis, settings, chat_pk=chat_pk
    )

    assert (first, second) == ("judged", "already_judged")
    assert len(calls) == 1
    rows = await _judgements(classification_session_factory, chat_pk=chat_pk)
    assert [row["intent"] for row in rows] == ["asking"]


async def test_own_words_that_open_the_rules_are_excluded_once_with_no_call(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """AE2: the message's own words open rule set v1, so its judgement could never be read."""
    chat_pk = await _member_message(
        insert_chat,
        insert_user,
        insert_message,
        chat_id=classification_chat_id,
        text=_RULE_OPENING_TEXT,
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])
    settings = _settings(classification_settings)

    first = await _judge(
        classification_session_factory, gateway, classification_redis, settings, chat_pk=chat_pk
    )
    second = await _judge(
        classification_session_factory, gateway, classification_redis, settings, chat_pk=chat_pk
    )

    assert (first, second) == ("excluded", "already_judged")
    assert calls == []
    attempts = await _attempts(classification_session_factory, chat_pk=chat_pk)
    assert [(a["outcome"], a["reason"], a["path"]) for a in attempts] == [
        ("excluded", "rule_opens", "live")
    ]
    assert attempts[0]["model_profile_id"] is None
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


@pytest.mark.parametrize(
    ("build_kwargs", "expected_reason"),
    [
        ({"is_from_moderator": True}, "moderator"),
        ({"text": "شكرا"}, "acknowledgement"),
    ],
)
async def test_an_ineligible_message_is_excluded_by_its_reason_with_no_call(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
    build_kwargs: dict[str, Any],
    expected_reason: str,
) -> None:
    """AE1: the classification's own E1-E8, through the same `load_facts`."""
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id, **build_kwargs
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "excluded"
    assert calls == []
    attempts = await _attempts(classification_session_factory, chat_pk=chat_pk)
    assert [(a["outcome"], a["reason"]) for a in attempts] == [("excluded", expected_reason)]
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


@pytest.mark.parametrize("final_error", [StructuredOutputInvalidError, ModelTruncatedError])
async def test_a_final_gateway_error_records_one_failure_naming_the_profile(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
    final_error: type[Exception],
) -> None:
    """F2: recorded, never retried, and nothing opens."""
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    profile_id = await seeded_attention_profile(active=True)
    gateway, _ = scripted_gateway(fail_with=final_error)

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "failed"
    attempts = await _attempts(classification_session_factory, chat_pk=chat_pk)
    assert [(a["outcome"], a["reason"], a["model_profile_id"]) for a in attempts] == [
        ("failed", final_error.category, profile_id)  # type: ignore[attr-defined]
    ]
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


async def test_a_transient_gateway_error_is_re_raised_and_records_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """F1: the task's own retry handles it (`test_judge_attention_retry.py`)."""
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    await seeded_attention_profile(active=True)
    gateway, _ = scripted_gateway(fail_with=ProviderUnreachableError)

    with pytest.raises(ProviderUnreachableError):
        await _judge(
            classification_session_factory,
            gateway,
            classification_redis,
            _settings(classification_settings),
            chat_pk=chat_pk,
        )

    assert await _attempts(classification_session_factory, chat_pk=chat_pk) == []
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


async def test_a_blank_instruction_claims_nothing_calls_nothing_and_records_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """P4. A claim already held elsewhere proves the order: with no instruction, `judge_one` ends
    before it would even try to claim, so it reports `no_prompt`, not `claimed_elsewhere`."""
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])
    key = f"ai:mod:attention:msg:{chat_pk}:1"
    await classification_redis.set(key, "someone-else", px=60_000)
    try:
        outcome = await _judge(
            classification_session_factory,
            gateway,
            classification_redis,
            _settings(classification_settings, prompt=None),
            chat_pk=chat_pk,
        )
        assert await classification_redis.get(key) == "someone-else"
    finally:
        await classification_redis.delete(key)

    assert outcome == "no_prompt"
    assert calls == []
    assert await _attempts(classification_session_factory, chat_pk=chat_pk) == []
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


async def test_no_active_attention_profile_calls_nothing_and_records_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    await seeded_attention_profile(active=False)
    async with classification_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE model_profiles SET is_active = false "
                "WHERE role = 'attention' AND is_active = true"
            )
        )
        await session.commit()
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "no_active_model"
    assert calls == []
    assert await _attempts(classification_session_factory, chat_pk=chat_pk) == []
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


async def test_a_claim_held_elsewhere_calls_nothing_and_records_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])
    key = f"ai:mod:attention:msg:{chat_pk}:1"
    await classification_redis.set(key, "someone-else", px=60_000)
    try:
        outcome = await _judge(
            classification_session_factory,
            gateway,
            classification_redis,
            _settings(classification_settings),
            chat_pk=chat_pk,
        )
        assert await classification_redis.get(key) == "someone-else"
    finally:
        await classification_redis.delete(key)

    assert outcome == "claimed_elsewhere"
    assert calls == []
    assert await _attempts(classification_session_factory, chat_pk=chat_pk) == []
    assert await _judgements(classification_session_factory, chat_pk=chat_pk) == []


async def test_the_request_is_the_instruction_and_the_redacted_text_only(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """P1: no sender, group, time, reply target or neighbouring message — two messages only."""
    chat_pk = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id, text=_URL_TEXT
    )
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "asking"}])

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "judged"
    assert len(calls) == 1
    system_message, user_message = calls[0].messages
    assert (system_message.role, system_message.content) == ("system", "TEST")
    assert (user_message.role, user_message.content) == ("user", redact(normalize(_URL_TEXT)))
    assert "«رابط»" in user_message.content
    assert "example.com" not in user_message.content


async def test_after_an_edit_the_first_posted_words_are_judged(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_bot_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """Finding 5: the captured event, never the row an edit overwrote."""
    chat_pk = await _member_message(
        insert_chat,
        insert_user,
        insert_message,
        chat_id=classification_chat_id,
        text=_FIRST_POSTED_TEXT,
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
    assert await apply_edit(classification_session_factory, update_row_id=edited_update_id) == 1
    await seeded_attention_profile(active=True)
    gateway, calls = scripted_gateway(responses=[{"intent": "informing"}])

    outcome = await _judge(
        classification_session_factory,
        gateway,
        classification_redis,
        _settings(classification_settings),
        chat_pk=chat_pk,
    )

    assert outcome == "judged"
    user_message = calls[0].messages[1]
    assert normalize(_FIRST_POSTED_TEXT) in user_message.content
    assert normalize(_EDITED_TEXT) not in user_message.content


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured_records() -> Iterator[_CaptureHandler]:
    """Attached to the module's own logger rather than through `caplog`, for the reason
    `tests/moderation/classification/test_classification_logs.py` records: elsewhere in the suite
    the root handlers are replaced and Alembic's `fileConfig` disables existing loggers, so
    `caplog`'s root capture stops seeing these records in a full run."""
    log = logging.getLogger(_LOGGER_NAME)
    original_level, original_propagate, original_disabled = (
        log.level,
        log.propagate,
        log.disabled,
    )
    handler = _CaptureHandler()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.disabled = False
    log.addHandler(handler)
    try:
        yield handler
    finally:
        log.removeHandler(handler)
        log.setLevel(original_level)
        log.propagate = original_propagate
        log.disabled = original_disabled


async def test_no_log_record_carries_message_text(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    scripted_gateway: Any,
    seeded_attention_profile: Any,
    classification_redis: Any,
    classification_settings: Any,
    captured_records: _CaptureHandler,
) -> None:
    """P2, N1, across judged, excluded and failed."""
    judged_chat = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id
    )
    excluded_chat = await _member_message(
        insert_chat,
        insert_user,
        insert_message,
        chat_id=classification_chat_id - 1,
        text=_RULE_OPENING_TEXT,
    )
    failed_chat = await _member_message(
        insert_chat, insert_user, insert_message, chat_id=classification_chat_id - 2
    )
    await seeded_attention_profile(active=True)
    settings = _settings(classification_settings)

    judged_gateway, _ = scripted_gateway(responses=[{"intent": "asking"}])
    failed_gateway, _ = scripted_gateway(fail_with=StructuredOutputInvalidError)
    outcomes = [
        await _judge(
            classification_session_factory,
            judged_gateway,
            classification_redis,
            settings,
            chat_pk=judged_chat,
        ),
        await _judge(
            classification_session_factory,
            judged_gateway,
            classification_redis,
            settings,
            chat_pk=excluded_chat,
        ),
        await _judge(
            classification_session_factory,
            failed_gateway,
            classification_redis,
            settings,
            chat_pk=failed_chat,
        ),
    ]

    assert outcomes == ["judged", "excluded", "failed"]
    assert captured_records.records, "expected at least the failure to be logged"
    markers = {
        text_
        for raw in (_DECLINED_TEXT, _RULE_OPENING_TEXT)
        for text_ in (raw, normalize(raw), redact(normalize(raw)))
    }
    for record in captured_records.records:
        values = [record.getMessage()] + [v for v in vars(record).values() if isinstance(v, str)]
        for value in values:
            for marker in markers:
                assert marker not in value
