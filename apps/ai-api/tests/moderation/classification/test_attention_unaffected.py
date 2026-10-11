"""T051 — the model being slow, absent or broken changes nothing outside the classification
pipeline: TG-M3's question items and figures, and TG-M4's incidents and their derived state, are
byte-identical whether classification runs with no active model, a model that always fails, or a
working one (`contracts/classification-pipeline.md` §8 F6, FR-022, FR-067, SC-003, SC-015).

Rather than re-deriving three independent traffic sets end to end (attention items and incidents
are TG-M3/TG-M4's own write paths, already covered there), this seeds one set of question items and
one incident directly, snapshots them and their figures, then proves `classify_one` — run over the
same messages under each of the three model configurations in turn — never moves either.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from app.application.gateway import ModelTruncatedError
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.classification import classify_one
from app.application.moderation.metrics import (
    accuracy_by_rule_version,
    first_response_time_stats,
    oldest_waiting,
    unanswered_stats,
)
from app.infrastructure.models_moderation import attention_items, moderation_incidents
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_OPENED_AT = datetime(2026, 2, 10, 9, 0, 0, tzinfo=UTC)
_PERIOD_FROM = _OPENED_AT - timedelta(days=1)
_PERIOD_TO = _OPENED_AT + timedelta(days=1)

_VALID_ANSWER = {
    "category": "SPAM_OR_AD",
    "needs_response": False,
    "needs_moderation": True,
    "severity": "high",
    "confidence": 0.97,
}

# Messages 1 and 3 anchor no incident going in — a confident violation on either would now open
# one (US4), which is no longer "nothing moves" for `moderation_incidents`. Scripting them as
# ordinary, non-violating answers keeps this test's claim true for them; message 4 keeps
# `_VALID_ANSWER` (a confident, consistent violation) precisely because it *already* anchors an
# operator incident — proving R12 (an existing incident wins, nothing new opens) is the "safety
# net" the comment below refers to, not a claim that a working model never opens anything.
_BENIGN_ANSWER = {
    "category": "QUESTION_ACCESS",
    "needs_response": True,
    "needs_moderation": False,
    "severity": "none",
    "confidence": 0.9,
}


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int
) -> dict[str, Any]:
    async with session_factory() as session:
        attention_rows = (
            await session.execute(
                sa.select(attention_items)
                .where(attention_items.c.telegram_chat_id == chat_pk)
                .order_by(attention_items.c.telegram_message_id)
            )
        ).mappings().all()
        incident_rows = (
            await session.execute(
                sa.select(moderation_incidents)
                .where(moderation_incidents.c.telegram_chat_id == chat_pk)
                .order_by(moderation_incidents.c.telegram_message_id)
            )
        ).mappings().all()
        frt = await first_response_time_stats(
            session,
            period_from=_PERIOD_FROM,
            period_to=_PERIOD_TO,
            min_samples=1,
            chat_id=chat_pk,
        )
        unanswered = await unanswered_stats(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO, chat_id=chat_pk
        )
        oldest = await oldest_waiting(session, chat_id=chat_pk)
        accuracy = await accuracy_by_rule_version(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO
        )
    return {
        "attention_items": [dict(row) for row in attention_rows],
        "moderation_incidents": [dict(row) for row in incident_rows],
        "first_response_time_stats": frt,
        "unanswered_stats": unanswered,
        "oldest_waiting": oldest,
        "accuracy_by_rule_version": accuracy,
    }


def _assert_snapshots_equal(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    # `oldest_waiting` measures against wall-clock `now()` by its own contract ("right now", not
    # historical) — it grows by however long the test itself took between the two snapshots, which
    # is real but not a side effect of classification. Every other figure and every row is compared
    # for exact equality; only this one field gets a tolerance.
    actual_rest = {k: v for k, v in actual.items() if k != "oldest_waiting"}
    expected_rest = {k: v for k, v in expected.items() if k != "oldest_waiting"}
    assert actual_rest == expected_rest
    drift = actual["oldest_waiting"] - expected["oldest_waiting"]
    assert timedelta(0) <= drift < timedelta(seconds=5)


async def test_classification_never_moves_question_items_incidents_or_their_figures(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    moderator = await insert_moderator()
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=moderator["moderator_id"],
        valid_from=_OPENED_AT - timedelta(days=30),
    )
    student_pk = await insert_user(tg_user_id=random.randint(10_000_000, 2_000_000_000))
    responder_pk = await insert_user(tg_user_id=moderator["telegram_user_id"])

    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=_OPENED_AT,
        telegram_user_id=student_pk,
        original_text="عندي مشكلة في الدخول على الكورس",
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=2,
        sent_at=_OPENED_AT + timedelta(minutes=1),
        telegram_user_id=responder_pk,
        is_from_moderator=True,
        original_text="تم الحل، جرب الآن",
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=3,
        sent_at=_OPENED_AT + timedelta(minutes=5),
        telegram_user_id=student_pk,
        original_text="سؤال ثاني لسه ماحدش رد عليه",
    )
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=4,
        sent_at=_OPENED_AT + timedelta(minutes=10),
        telegram_user_id=student_pk,
        original_text="اعلان عن كورس تاني بسعر رخيص جدا انضموا الآن",
    )

    async with classification_session_factory() as session:
        await session.execute(
            attention_items.insert().values(
                telegram_chat_id=chat_pk,
                telegram_message_id=1,
                opened_at=_OPENED_AT,
                source="rule",
                rule_version=1,
                responsible_moderator_id=moderator["moderator_id"],
                status="answered",
                first_response_message_id=2,
                first_response_at=_OPENED_AT + timedelta(minutes=1),
                first_response_moderator_id=moderator["moderator_id"],
                first_response_kind="direct_reply",
            )
        )
        await session.execute(
            attention_items.insert().values(
                telegram_chat_id=chat_pk,
                telegram_message_id=3,
                opened_at=_OPENED_AT + timedelta(minutes=5),
                source="rule",
                rule_version=1,
                responsible_moderator_id=moderator["moderator_id"],
                status="open",
            )
        )
        await session.execute(
            moderation_incidents.insert().values(
                telegram_chat_id=chat_pk,
                telegram_message_id=4,
                opened_at=_OPENED_AT + timedelta(minutes=10),
                detected_at=_OPENED_AT + timedelta(minutes=11),
                source="operator",
                opened_by_user_id=1,
                category="SPAM_OR_AD",
                severity="high",
                responsible_moderator_id=moderator["moderator_id"],
            )
        )
        await session.commit()

    before = await _snapshot(
        classification_session_factory, chat_pk=chat_pk
    )

    registry = ProfileRegistry(classification_session_factory)

    # Configuration 1: no active moderation profile at all.
    async with classification_session_factory() as session:
        await session.execute(
            sa.text("UPDATE model_profiles SET is_active = false WHERE role = 'moderation'")
        )
        await session.commit()
    no_model_gateway, _ = scripted_gateway()
    for message_id in (1, 3, 4):
        outcome = await classify_one(
            classification_session_factory,
            no_model_gateway,
            registry,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path="live",
        )
        assert outcome == "no_active_model"
    after_no_model = await _snapshot(
        classification_session_factory, chat_pk=chat_pk
    )
    _assert_snapshots_equal(after_no_model, before)

    # Configuration 2: an active profile whose model always fails (a final, recorded failure —
    # not a raised transient error, since this test exercises `classify_one` directly rather than
    # the task-level retry US3 adds around it).
    async with classification_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE model_profiles SET is_active = true "
                "WHERE role = 'moderation' AND name = 'cls-test-moderation-active'"
            )
        )
        await session.commit()
    failing_gateway, failing_calls = scripted_gateway(fail_with=ModelTruncatedError)
    for message_id in (1, 3, 4):
        outcome = await classify_one(
            classification_session_factory,
            failing_gateway,
            registry,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path="live",
        )
        assert outcome in ("failed", "excluded")
    assert len(failing_calls) == 3
    after_failing_model = await _snapshot(
        classification_session_factory, chat_pk=chat_pk
    )
    _assert_snapshots_equal(after_failing_model, before)

    # Configuration 3: a working scripted profile that successfully classifies every message,
    # including the advert (message 4) at a confidence that routes `incident` — message 4 already
    # anchors an operator incident, so US4's own insert conflicts and opens nothing new (R12); the
    # other two messages get ordinary answers, so `moderation_incidents` stays byte-identical.
    working_gateway, working_calls = scripted_gateway(
        responses=[dict(_BENIGN_ANSWER), dict(_BENIGN_ANSWER), dict(_VALID_ANSWER)]
    )
    for message_id in (1, 3, 4):
        outcome = await classify_one(
            classification_session_factory,
            working_gateway,
            registry,
            classification_redis,
            classification_settings,
            chat_pk=chat_pk,
            message_id=message_id,
            path="live",
        )
        assert outcome in ("classified", "excluded")
    assert len(working_calls) == 3
    after_working_model = await _snapshot(
        classification_session_factory, chat_pk=chat_pk
    )
    _assert_snapshots_equal(after_working_model, before)
