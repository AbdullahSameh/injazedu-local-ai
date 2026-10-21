"""T041 — opening a question item from the attention judgement
(`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §6, §7 W2; D-TG-191,
D-TG-199; FR-318-FR-323).

The rule set keeps the first word on every burst. Only when it declines does `open_item` read the
burst members' current attention judgements, in `(sent_at, message_id)` order, and open
`source='ai'` from the first one passing A1-A2 (`judgement_proposes`), G5-G6
(`within_attention_window`) and V (`vetoed`, on the member's current classification). The item
links that judgement and never a classification (`ck_attention_ai_link`), on TG-M3's own anchor,
`opened_at` and attribution. A judgement that lands after its burst was judged re-flags its
message in the same transaction (W2), and the sweep converges (Case B).

Every model answer is scripted or inserted directly: no model runtime, no network. `sent_at` is a
real wall-clock offset, since the sweep's cutoff and a judgement's `created_at` are the database's
own clock (as in `tests/moderation/classification/test_ai_attention.py`).
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.gateway.registry import ProfileRegistry
from app.application.moderation.attention import (
    AiAttention,
    ai_attention_from_settings,
    assemble_burst,
    open_item,
)
from app.application.moderation.attention_judgement import judge_one
from app.domain.moderation.attention_judgement import INTENTS
from app.infrastructure.models_moderation import (
    attention_items,
    message_attention_judgements,
    telegram_messages,
)
from app.workers.tasks.moderation.evaluate_attention import evaluate_attention_once
from app.workers.tasks.moderation.sweep_unjudged_bursts import (
    sweep_unjudged_bursts_all,
    sweep_unjudged_bursts_once,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_GAP_S = 90
_MAX_AGE_S = 86400

_PROMPT_VERSION = "attention_test"
_INSTRUCTIONS = {_PROMPT_VERSION: "TEST"}

# Synthetic wording only. `_IMPLICIT_QUESTION` and `_GREETING` carry no rule-set signal (no `؟`,
# no interrogative or support pattern on a token boundary, no mention, no reply).
_IMPLICIT_QUESTION = "في محاضرة بكرة"
_RULE_QUESTION = "متى المحاضرة؟"
_GREETING = "السلام عليكم يا شباب"


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _ai(*, enabled_from: datetime | None = None) -> AiAttention:
    return AiAttention(
        enabled_from=enabled_from if enabled_from is not None else _now() - timedelta(days=1),
        max_age_s=_MAX_AGE_S,
    )


def _settings(
    classification_settings: Any,
    *,
    switch: datetime | None = None,
    prompt: str | None = _PROMPT_VERSION,
) -> Any:
    """The switch defaults to yesterday; `model_copy` skips the allowlist validator, so the
    test-only instruction stands in for a frozen one (D-TG-189)."""
    return classification_settings.model_copy(
        update={
            "moderation_ai_attention_from": (
                switch if switch is not None else _now() - timedelta(days=1)
            ),
            "moderation_attention_prompt_version": prompt,
        }
    )


async def _open(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_pk: int,
    user_pk: int,
    around: datetime,
    ai: AiAttention | None,
) -> int | None:
    """One burst judgement, one transaction: exactly `evaluate_attention_once`."""
    return await evaluate_attention_once(
        session_factory,
        telegram_chat_id=chat_pk,
        telegram_user_id=user_pk,
        message_thread_id=None,
        around=around,
        gap_s=_GAP_S,
        ai=ai,
    )


async def _judge_attention(
    session_factory: async_sessionmaker[AsyncSession],
    scripted_gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int,
    intent: str,
) -> str:
    gateway, _calls = scripted_gateway(responses=[{"intent": intent}])
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


async def _items(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    sa.select(attention_items)
                    .where(attention_items.c.telegram_chat_id == chat_pk)
                    .order_by(attention_items.c.id)
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


async def _message(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    sa.select(telegram_messages).where(
                        telegram_messages.c.telegram_chat_id == chat_pk,
                        telegram_messages.c.message_id == message_id,
                    )
                )
            )
            .mappings()
            .one()
        )
        return dict(row)


async def _judgement_id(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(message_attention_judgements.c.id).where(
                    message_attention_judgements.c.telegram_chat_id == chat_pk,
                    message_attention_judgements.c.telegram_message_id == message_id,
                    message_attention_judgements.c.is_current.is_(True),
                )
            )
        ).scalar_one()


async def _drain_existing_backlog(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """The sweep claims the shared test database's whole unjudged backlog: drain it rule-only
    first, so this file's counts do not depend on suite order (`test_sweep.py`)."""
    await sweep_unjudged_bursts_all(session_factory, gap_s=0)


@pytest.fixture
async def seeded(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_seeded_profile: None,
    seeded_attention_profile: Any,
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_assignment: Any,
) -> dict[str, Any]:
    """A measured group with a primary owner since two days ago, one student, the active
    moderation profile (for the veto's classifications) and an active attention profile."""
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    owner = await insert_moderator(display_name="Owner")
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=owner["moderator_id"],
        valid_from=_now() - timedelta(days=2),
    )
    user_pk = await insert_user(tg_user_id=_rand_id())
    async with classification_session_factory() as session:
        moderation_profile_id = (
            await session.execute(
                sa.text("SELECT id FROM model_profiles WHERE role = 'moderation' AND is_active")
            )
        ).scalar_one()
    attention_profile_id = await seeded_attention_profile(active=True)
    return {
        "chat_pk": chat_pk,
        "user_pk": user_pk,
        "owner": owner,
        "moderation_profile_id": moderation_profile_id,
        "attention_profile_id": attention_profile_id,
    }


# --- 1-2: rules first; then the judgement -------------------------------------------------------


async def test_1_a_rule_signalled_burst_opens_a_rule_item_and_ignores_an_asking_judgement(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_RULE_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    await _open(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert (item["source"], item["rule_version"]) == ("rule", 1)
    assert item["attention_judgement_id"] is None
    assert item["message_classification_id"] is None


async def test_2_a_rule_declined_burst_opens_from_its_asking_member_on_the_bursts_anchor(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    greeting_at = _now() - timedelta(minutes=10)
    question_at = greeting_at + timedelta(seconds=20)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=greeting_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_GREETING,
    )
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=question_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="social"
    )
    question_judgement = await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=2, intent="asking"
    )

    item_id = await _open(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=question_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["id"] == item_id
    assert (item["source"], item["rule_version"]) == ("ai", None)
    assert item["attention_judgement_id"] == question_judgement
    assert item["message_classification_id"] is None
    assert item["telegram_message_id"] == 1  # the burst's earliest member (B2)
    assert item["opened_at"] == greeting_at
    assert item["responsible_moderator_id"] is None  # TG-M2.1 G1
    for message_id in (1, 2):
        message = await _message(
            classification_session_factory, chat_pk=seeded["chat_pk"], message_id=message_id
        )
        assert message["attention_item_id"] == item_id


@pytest.mark.parametrize("intent", [intent for intent in INTENTS if intent != "asking"])
async def test_a_judgement_of_any_other_intent_opens_nothing(
    intent: str,
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent=intent
    )

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is not None


# --- 3-4: V, the member's current classification -------------------------------------------------


@pytest.mark.parametrize("category", ["SPAM_OR_AD", "ABUSE"])
async def test_3_a_vetoed_member_is_skipped_and_a_later_unvetoed_asking_member_opens(
    category: str,
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_judgement: Any,
) -> None:
    first_at = _now() - timedelta(minutes=10)
    second_at = first_at + timedelta(seconds=30)
    for message_id, at in ((1, first_at), (2, second_at)):
        await insert_message(
            telegram_chat_id=seeded["chat_pk"],
            message_id=message_id,
            sent_at=at,
            telegram_user_id=seeded["user_pk"],
            original_text=_IMPLICIT_QUESTION,
        )
    await insert_prediction(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        model_profile_id=seeded["moderation_profile_id"],
        category=category,
        needs_moderation=True,
        severity="high",
        route="incident",
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )
    second_judgement = await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=2, intent="asking"
    )

    await _open(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=second_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["attention_judgement_id"] == second_judgement
    assert (item["telegram_message_id"], item["opened_at"]) == (1, first_at)


@pytest.mark.parametrize("category", ["SPAM_OR_AD", "ABUSE"])
async def test_3_a_burst_whose_only_asking_member_is_vetoed_opens_nothing(
    category: str,
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_prediction(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        model_profile_id=seeded["moderation_profile_id"],
        category=category,
        needs_moderation=True,
        severity="high",
        route="incident",
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


@pytest.mark.parametrize("category", ["CHITCHAT", None])
async def test_4_chitchat_and_a_missing_classification_do_not_veto(
    category: str | None,
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    if category is not None:
        await insert_prediction(
            telegram_chat_id=seeded["chat_pk"],
            telegram_message_id=1,
            model_profile_id=seeded["moderation_profile_id"],
            category=category,
            severity="none",
        )
    judgement_id = await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    await _open(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert (item["source"], item["attention_judgement_id"]) == ("ai", judgement_id)


# --- 5-7: the window, catch-up, and the two settings ---------------------------------------------


async def test_5_a_judgement_recorded_before_the_switch_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        intent="asking",
        created_at=sent_at + timedelta(seconds=2),
    )

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(enabled_from=sent_at + timedelta(minutes=1)),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_5_a_judgement_recorded_max_age_after_the_question_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(seconds=_MAX_AGE_S + 60)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(enabled_from=sent_at - timedelta(days=1)),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_6_a_catch_up_judgement_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        intent="asking",
        path="catch_up",
    )

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_7_the_switch_set_with_the_attention_prompt_blank_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
    classification_settings: Any,
) -> None:
    """D-TG-199, FR-322: a judgement recorded earlier, still inside the window, opens nothing
    once the instruction is blank, because no judgement path builds a switch."""
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )
    settings = _settings(classification_settings, prompt=None)

    ai = ai_attention_from_settings(settings)

    assert ai is None
    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=ai,
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


# --- 8-10: both orderings, and replays -----------------------------------------------------------


async def test_8_case_a_judged_before_the_settle_opens_at_the_settle(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings(classification_settings)

    outcome = await _judge_attention(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )
    assert outcome == "judged"
    # Not judged yet: the request is a no-op, and the pending settle reads the judgement.
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is None

    await _open(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=ai_attention_from_settings(settings),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["attention_judgement_id"] == await _judgement_id(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )


async def test_9_case_b_judged_after_the_settle_is_reflagged_and_the_sweep_opens(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings(classification_settings)
    ai = ai_attention_from_settings(settings)
    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=ai,
        )
        is None
    )

    await _judge_attention(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is None  # back on the authoritative work list

    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=ai)

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["opened_at"] == sent_at  # the question's time, never the judgement's


async def test_9_the_reflag_commits_with_the_judgement_while_a_burst_judgement_holds_the_lock(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """W2: the burst judgement declines and holds `chat_lock` uncommitted while the attention
    judgement is recorded. `judge_one` waits for the lock inside its own transaction, then re-flags
    the now-judged message: the judgement and the request commit together, and nothing is lost."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings(classification_settings)
    ai = ai_attention_from_settings(settings)

    async with classification_session_factory() as judging:
        burst = await assemble_burst(
            judging,
            telegram_chat_id=seeded["chat_pk"],
            telegram_user_id=seeded["user_pk"],
            message_thread_id=None,
            around=sent_at,
            gap_s=_GAP_S,
        )
        assert await open_item(judging, burst, ai=ai) is None
        attending = asyncio.create_task(
            _judge_attention(
                classification_session_factory,
                scripted_gateway,
                classification_redis,
                settings,
                chat_pk=seeded["chat_pk"],
                message_id=1,
                intent="asking",
            )
        )
        await asyncio.sleep(0.5)
        assert not attending.done()  # blocked on the burst judgement's chat_lock
        await judging.commit()
    assert await attending == "judged"

    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=ai)

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"


async def test_10_replays_and_concurrent_judgements_converge_on_one_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings(classification_settings)
    ai = ai_attention_from_settings(settings)
    outcomes = [
        await _judge_attention(
            classification_session_factory,
            scripted_gateway,
            classification_redis,
            settings,
            chat_pk=seeded["chat_pk"],
            message_id=1,
            intent="asking",
        )
        for _ in range(2)
    ]
    assert outcomes == ["judged", "already_judged"]

    async def burst_judgement() -> int | None:
        return await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=ai,
        )

    results = await asyncio.gather(burst_judgement(), burst_judgement(), burst_judgement())
    await burst_judgement()
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=ai)

    items = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert len(items) == 1
    assert set(results) == {items[0]["id"]}


# --- 11: history is kept -------------------------------------------------------------------------


async def test_11_a_historical_tg_m5_1_item_keeps_its_classification_link(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_prediction: Any,
    insert_attention_item: Any,
    insert_attention_judgement: Any,
    fetch_attention_item: Any,
) -> None:
    """D-TG-198: nothing reprocesses or backfills. A re-judgement over a burst a TG-M5.1 item
    already covers converges on it (E4), and its link stays the classification's."""
    sent_at = _now() - timedelta(minutes=10)
    message_pk = await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    prediction_id = await insert_prediction(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        model_profile_id=seeded["moderation_profile_id"],
        category="QUESTION_COURSE",
        severity="none",
        needs_response=True,
    )
    item_id = await insert_attention_item(
        telegram_chat_id=seeded["chat_pk"],
        telegram_message_id=1,
        opened_at=sent_at,
        source="ai",
        rule_version=None,
        message_classification_id=prediction_id,
    )
    async with classification_session_factory() as session:
        await session.execute(
            telegram_messages.update()
            .where(telegram_messages.c.id == message_pk)
            .values(attention_item_id=item_id, attention_evaluated_at=None)
        )
        await session.commit()
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )
    before = await fetch_attention_item(item_id=item_id)

    assert (
        await _open(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        == item_id
    )

    after = await fetch_attention_item(item_id=item_id)
    assert after == before
    assert after["message_classification_id"] == prediction_id
    assert after["attention_judgement_id"] is None
    assert len(await _items(classification_session_factory, chat_pk=seeded["chat_pk"])) == 1
