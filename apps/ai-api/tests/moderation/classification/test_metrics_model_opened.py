"""C9 — questions the model opened, and what the humans did with them (`classification-metrics.md`
§8a, TG-M5.1). The model-opened counterpart of C3's M9: dismissed ÷ opened, with its denominator, is
the pilot's false-positive gate for AI-assisted Attention Opening. Hand-computed over a fixed
scenario: two models, every status, a rule item and an out-of-period item that must not count, and a
second group the chat filter must leave out. Never pooled across models (K3); no average (FR-049).

Amended by TG-M5.3 (`specs/011-tg-m5-3-attention-judgement/contracts/dismissal-reasons.md` K8,
K9): each row also carries the per-reason breakdown of `model_dismissed`, which sums to it.
`model_dismissed` itself, and so the pilot gate, is unchanged (K10).

Amended by TG-M5.3 again (`contracts/attention-metrics.md` §1, C9′; `tasks.md` T045): C9 is the
union of two eras, each item grouped by the record that opened it — a TG-M5.1 item by its
prediction's model, instruction and vocabulary (`era = 'classification'`), a TG-M5.3 item by its
judgement's model and attention instruction (`era = 'attention'`, no vocabulary). Never pooled
(M23′); M19's kept count is `model_kept` summed across every row (a count, not a rate).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.metrics import model_opened_question_stats
from app.infrastructure.models import model_profiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.attention_judgement import conftest as attention_judgement_conftest

# Re-exported, by name, from the attention judgement package (T014's pattern): one definition of
# the judgement builder, whose `needs_response` comes from the domain's single derivation.
insert_attention_judgement = attention_judgement_conftest.insert_attention_judgement
seeded_attention_profile = attention_judgement_conftest.seeded_attention_profile

_BASE = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


def _breakdown(row: Any) -> tuple[int, int, int, int]:
    return (
        row["dismissed_not_a_question"],
        row["dismissed_member_discussion"],
        row["dismissed_message_removed"],
        row["dismissed_other"],
    )


async def _insert_model_profile(
    session_factory: async_sessionmaker[AsyncSession], *, name: str, role: str = "moderation"
) -> int:
    async with session_factory() as session:
        row_id = (
            await session.execute(
                model_profiles.insert()
                .values(
                    name=name,
                    provider="fake",
                    model=f"fake-{name}",
                    role=role,
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
        close_reason: str | None = None,
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
        await insert_attention_item(
            telegram_chat_id=chat,
            telegram_message_id=n,
            opened_at=sent_at,
            source="ai" if model is not None else "rule",
            rule_version=None if model is not None else 1,
            status=status,
            first_response_message_id=n + 1000 if answered else None,
            first_response_at=sent_at + timedelta(minutes=1) if answered else None,
            first_response_kind="direct_reply" if answered else None,
            close_reason=close_reason,
            message_classification_id=classification_id,
        )

    # Model A, classify_v2: opened 4 — answered 1, dismissed 1, open 1, expired 1.
    await item(1, model=model_a, status="answered")
    await item(3, model=model_a, status="dismissed", close_reason="member_discussion")
    await item(4, model=model_a, status="open")
    await item(5, model=model_a, status="expired")
    # Model A, classify_v1: its own row, never pooled with classify_v2's (K3). No reason recorded.
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

    assert {r["era"] for r in rows} == {"classification"}
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

    # TG-M5.3 K8, K9: the breakdown per row, summing to `model_dismissed`.
    assert _breakdown(a2) == (0, 1, 0, 0)
    assert _breakdown(a1) == (0, 0, 0, 1)
    assert _breakdown(b2) == (0, 0, 0, 0)
    assert all(sum(_breakdown(r)) == r["model_dismissed"] for r in rows)


async def test_c9_breaks_model_dismissals_down_by_reason(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_item: Any,
) -> None:
    """K8, K9: one model's dismissals of every reason — the three the panel offers, an operator's
    free text and none at all. Free text and NULL both count as `other`."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    model = await _insert_model_profile(classification_session_factory, name=f"r-{_rand_id()}")
    reasons: list[str | None] = [
        "not_a_question",
        "member_discussion",
        "message_removed",
        "spam bot",
        None,
    ]

    for n, reason in enumerate(reasons, start=1):
        sent_at = _BASE + timedelta(minutes=n)
        await insert_message(telegram_chat_id=chat_pk, message_id=n, sent_at=sent_at)
        classification_id = await insert_prediction(
            telegram_chat_id=chat_pk,
            telegram_message_id=n,
            model_profile_id=model,
            category="QUESTION_COURSE",
            severity="none",
            needs_response=True,
            created_at=sent_at,
        )
        await insert_attention_item(
            telegram_chat_id=chat_pk,
            telegram_message_id=n,
            opened_at=sent_at,
            source="ai",
            rule_version=None,
            status="dismissed",
            close_reason=reason,
            message_classification_id=classification_id,
        )

    async with classification_session_factory() as session:
        rows = await model_opened_question_stats(
            session, period_from=_BASE, period_to=_BASE + timedelta(hours=1), chat_id=chat_pk
        )

    assert len(rows) == 1
    (row,) = rows
    assert (row["model_opened"], row["model_dismissed"], row["model_kept"]) == (5, 5, 0)
    assert _breakdown(row) == (1, 1, 1, 2)
    assert sum(_breakdown(row)) == row["model_dismissed"]


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


async def test_c9_prime_keeps_the_classification_era_and_the_attention_era_apart(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_item: Any,
    insert_attention_judgement: Any,
) -> None:
    """C9′, M23′: one TG-M5.1 item (classification-linked) and two TG-M5.3 items
    (judgement-linked) under two attention models — three rows, each grouped by the record that
    opened it, never pooled; M19's kept count is `model_kept` summed across all three."""
    chat_pk = await insert_chat(chat_id=-_rand_id())
    moderation_model = await _insert_model_profile(
        classification_session_factory, name=f"m-{_rand_id()}"
    )
    attention_a = await _insert_model_profile(
        classification_session_factory, name=f"aa-{_rand_id()}", role="attention"
    )
    attention_b = await _insert_model_profile(
        classification_session_factory, name=f"ab-{_rand_id()}", role="attention"
    )

    # Classification era: opened 1, answered.
    await insert_message(telegram_chat_id=chat_pk, message_id=1, sent_at=_BASE)
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1001, sent_at=_BASE + timedelta(minutes=1)
    )
    classification_id = await insert_prediction(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        model_profile_id=moderation_model,
        category="QUESTION_COURSE",
        severity="none",
        needs_response=True,
        prompt_version="classify_v2",
        created_at=_BASE,
    )
    await insert_attention_item(
        telegram_chat_id=chat_pk,
        telegram_message_id=1,
        opened_at=_BASE,
        source="ai",
        rule_version=None,
        status="answered",
        first_response_message_id=1001,
        first_response_at=_BASE + timedelta(minutes=1),
        first_response_kind="direct_reply",
        message_classification_id=classification_id,
    )

    # Attention era: model A opened 1, dismissed as member discussion; model B opened 1, open.
    for n, model, status, close_reason in (
        (2, attention_a, "dismissed", "member_discussion"),
        (3, attention_b, "open", None),
    ):
        sent_at = _BASE + timedelta(minutes=n)
        await insert_message(telegram_chat_id=chat_pk, message_id=n, sent_at=sent_at)
        judgement_id = await insert_attention_judgement(
            telegram_chat_id=chat_pk,
            telegram_message_id=n,
            intent="asking",
            created_at=sent_at,
            model_profile_id=model,
        )
        await insert_attention_item(
            telegram_chat_id=chat_pk,
            telegram_message_id=n,
            opened_at=sent_at,
            source="ai",
            rule_version=None,
            status=status,
            close_reason=close_reason,
            attention_judgement_id=judgement_id,
        )

    async with classification_session_factory() as session:
        rows = await model_opened_question_stats(
            session, period_from=_BASE, period_to=_BASE + timedelta(hours=1), chat_id=chat_pk
        )

    by_era_and_model = {(r["era"], r["model_profile_id"]): r for r in rows}
    assert set(by_era_and_model) == {
        ("classification", moderation_model),
        ("attention", attention_a),
        ("attention", attention_b),
    }
    era_c = by_era_and_model[("classification", moderation_model)]
    assert (era_c["prompt_version"], era_c["taxonomy_version"]) == ("classify_v2", 1)
    assert (era_c["model_opened"], era_c["model_dismissed"], era_c["model_kept"]) == (1, 0, 1)
    assert (era_c["model_answered"], era_c["model_unanswered"]) == (1, 0)
    era_a = by_era_and_model[("attention", attention_a)]
    assert (era_a["prompt_version"], era_a["taxonomy_version"]) == ("attention_test", None)
    assert (era_a["model_opened"], era_a["model_dismissed"], era_a["model_kept"]) == (1, 1, 0)
    assert _breakdown(era_a) == (0, 1, 0, 0)
    era_b = by_era_and_model[("attention", attention_b)]
    assert (era_b["model_opened"], era_b["model_dismissed"], era_b["model_kept"]) == (1, 0, 1)
    assert (era_b["model_answered"], era_b["model_unanswered"]) == (0, 1)
    assert all(sum(_breakdown(r)) == r["model_dismissed"] for r in rows)

    # M19: rule misses the model caught and nobody dismissed, across both eras.
    assert sum(r["model_kept"] for r in rows) == 2
