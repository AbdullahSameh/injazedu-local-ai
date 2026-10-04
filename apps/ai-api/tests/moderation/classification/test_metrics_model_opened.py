"""C9 — questions the model opened, and what the humans did with them (`classification-metrics.md`
§8a, TG-M5.1). The model-opened counterpart of C3's M9: dismissed ÷ opened, with its denominator, is
the pilot's false-positive gate for AI-assisted Attention Opening. Hand-computed over a fixed
scenario: two models, every status, a rule item and an out-of-period item that must not count, and a
second group the chat filter must leave out. Never pooled across models (K3); no average (FR-049).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.metrics import model_opened_question_stats
from app.infrastructure.models import model_profiles
from app.infrastructure.models_moderation import attention_items
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_BASE = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _insert_model_profile(
    session_factory: async_sessionmaker[AsyncSession], *, name: str
) -> int:
    async with session_factory() as session:
        row_id = (
            await session.execute(
                model_profiles.insert()
                .values(
                    name=name,
                    provider="fake",
                    model=f"fake-{name}",
                    role="moderation",
                    params={},
                    is_active=False,
                )
                .returning(model_profiles.c.id)
            )
        ).scalar_one()
        await session.commit()
        return row_id


async def test_c9_counts_each_models_opened_questions_by_outcome(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_item: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())
    other_chat_pk = await insert_chat(chat_id=-_rand_id())
    model_a = await _insert_model_profile(classification_session_factory, name=f"a-{_rand_id()}")
    model_b = await _insert_model_profile(classification_session_factory, name=f"b-{_rand_id()}")
    period_from = _BASE - timedelta(hours=1)
    period_to = _BASE + timedelta(hours=6)

    async def item(
        n: int,
        *,
        model: int | None,
        status: str,
        chat: int = chat_pk,
        at: datetime | None = None,
        prompt_version: str = "classify_v2",
    ) -> None:
        sent_at = at if at is not None else _BASE + timedelta(minutes=n)
        await insert_message(telegram_chat_id=chat, message_id=n, sent_at=sent_at)
        answered = status == "answered"
        if answered:
            await insert_message(
                telegram_chat_id=chat, message_id=n + 1000, sent_at=sent_at + timedelta(minutes=1)
            )
        classification_id = None
        if model is not None:
            classification_id = await insert_prediction(
                telegram_chat_id=chat,
                telegram_message_id=n,
                model_profile_id=model,
                category="QUESTION_COURSE",
                severity="none",
                needs_response=True,
                prompt_version=prompt_version,
                created_at=sent_at,
            )
        item_id = await insert_attention_item(
            telegram_chat_id=chat,
            telegram_message_id=n,
            opened_at=sent_at,
            source="ai" if model is not None else "rule",
            rule_version=None if model is not None else 1,
            status=status,
            first_response_message_id=n + 1000 if answered else None,
            first_response_at=sent_at + timedelta(minutes=1) if answered else None,
            first_response_kind="direct_reply" if answered else None,
        )
        if classification_id is not None:
            async with classification_session_factory() as session:
                await session.execute(
                    attention_items.update()
                    .where(attention_items.c.id == item_id)
                    .values(message_classification_id=classification_id)
                )
                await session.commit()

    # Model A, classify_v2: opened 4 — answered 1, dismissed 1, open 1, expired 1.
    await item(1, model=model_a, status="answered")
    await item(3, model=model_a, status="dismissed")
    await item(4, model=model_a, status="open")
    await item(5, model=model_a, status="expired")
    # Model A, classify_v1: its own row, never pooled with classify_v2's (K3).
    await item(6, model=model_a, status="dismissed", prompt_version="classify_v1")
    # Model B: opened 1, answered.
    await item(7, model=model_b, status="answered")
    # Not counted: a rule item, an out-of-period model item, another group's model item.
    await item(9, model=None, status="open")
    await item(10, model=model_a, status="open", at=period_to + timedelta(minutes=1))
    await item(11, model=model_a, status="dismissed", chat=other_chat_pk)

    async with classification_session_factory() as session:
        rows = await model_opened_question_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )

    by_key = {(r["model_profile_id"], r["prompt_version"]): r for r in rows}
    assert set(by_key) == {
        (model_a, "classify_v2"),
        (model_a, "classify_v1"),
        (model_b, "classify_v2"),
    }
    a2 = by_key[(model_a, "classify_v2")]
    assert (a2["model_opened"], a2["model_dismissed"], a2["model_kept"]) == (4, 1, 3)
    assert (a2["model_answered"], a2["model_unanswered"]) == (1, 2)
    a1 = by_key[(model_a, "classify_v1")]
    assert (a1["model_opened"], a1["model_dismissed"], a1["model_kept"]) == (1, 1, 0)
    b2 = by_key[(model_b, "classify_v2")]
    assert (b2["model_opened"], b2["model_dismissed"], b2["model_answered"]) == (1, 0, 1)
    assert all(r["taxonomy_version"] == 1 for r in rows)


async def test_c9_with_no_model_opened_question_has_no_row(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=-_rand_id())

    async with classification_session_factory() as session:
        rows = await model_opened_question_stats(
            session, period_from=_BASE, period_to=_BASE + timedelta(days=1), chat_id=chat_pk
        )

    assert rows == []  # M22: no data is not zero
