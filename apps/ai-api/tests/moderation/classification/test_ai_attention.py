"""TG-M5.1 — a live model judgement as a second opener of question items
(`specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md`), re-pointed by TG-M5.3 to the
attention judgement (`specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md` §6-§7,
D-TG-191, `tasks.md` T044).

The rule set keeps the first word on every burst; only when it declines does `open_item` consult the
burst's stored **attention judgements**, through the one gate (`judgement_proposes`,
`within_attention_window`, `vetoed`), and open `source='ai'` linked to that judgement — on TG-M3's
own anchor, `opened_at`, attribution, stamping and C10 lookback. A judgement that lands after the
burst was judged re-flags its message through E5's own mechanism (`request_rejudgement`, W2), and
the ordinary sweep converges. The classification no longer proposes or re-flags anything (W3).
Every model answer here is scripted or inserted directly — no model runtime, no network.

`sent_at` is a real wall-clock offset (the sweep's cutoff and the judgement's `created_at` are
the database's own clock, and G6 compares the two), mirroring `tests/moderation/attention/
test_sweep.py`.
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
    assemble_burst,
    match_response,
    open_item,
    request_rejudgement,
)
from app.application.moderation.attention_judgement import judge_one
from app.application.moderation.classification import classify_one
from app.infrastructure.models_moderation import (
    attention_items,
    message_attention_judgements,
    message_classifications,
    moderation_incidents,
    telegram_messages,
)
from app.scripts.rederive_chat import rederive_chat_attention
from app.workers.tasks.moderation.sweep_unjudged_bursts import (
    sweep_unjudged_bursts_all,
    sweep_unjudged_bursts_once,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.attention_judgement import conftest as attention_judgement_conftest

# Re-exported, by name, from the attention judgement package (T014's pattern): the judgement
# builders have one definition, and pytest finds a fixture by the attribute name in this module.
insert_attention_judgement = attention_judgement_conftest.insert_attention_judgement
seeded_attention_profile = attention_judgement_conftest.seeded_attention_profile

_GAP_S = 90
_MAX_AGE_S = 86400

_PROMPT_VERSION = "attention_test"
_INSTRUCTIONS = {_PROMPT_VERSION: "TEST"}

# Synthetic wording only — never real student text. No rule-set signal in either (no `؟`, no
# interrogative or support pattern on a token boundary, no mention, no reply).
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


def _settings_with_switch(settings: Any, enabled_from: datetime | None) -> Any:
    """The switch and the test-only attention instruction (D-TG-199: the opener needs both);
    `model_copy` skips the allowlist validator, so the test-only version needs no entry."""
    return settings.model_copy(
        update={
            "moderation_ai_attention_from": enabled_from,
            "moderation_attention_prompt_version": _PROMPT_VERSION,
        }
    )


async def _judge(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_pk: int,
    user_pk: int,
    around: datetime,
    ai: AiAttention | None,
) -> int | None:
    """One judgement, one transaction — exactly `evaluate_attention_once`."""
    async with session_factory() as session:
        burst = await assemble_burst(
            session,
            telegram_chat_id=chat_pk,
            telegram_user_id=user_pk,
            message_thread_id=None,
            around=around,
            gap_s=_GAP_S,
        )
        item_id = await open_item(session, burst, ai=ai)
        await session.commit()
        return item_id


async def _classify(
    session_factory: async_sessionmaker[AsyncSession],
    scripted_gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int,
    answer: dict[str, Any],
    path: str = "live",
) -> str:
    gateway, _calls = scripted_gateway(responses=[dict(answer)])
    return await classify_one(
        session_factory,
        gateway,
        ProfileRegistry(session_factory),
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        path=path,
    )


async def _attend(
    session_factory: async_sessionmaker[AsyncSession],
    scripted_gateway: Any,
    redis: Any,
    settings: Any,
    *,
    chat_pk: int,
    message_id: int,
    intent: str,
    path: str = "live",
) -> str:
    """One attention judgement, exactly `judge_attention_once` with a scripted answer."""
    gateway, _calls = scripted_gateway(responses=[{"intent": intent}])
    return await judge_one(
        session_factory,
        gateway,
        ProfileRegistry(session_factory),
        redis,
        settings,
        chat_pk=chat_pk,
        message_id=message_id,
        path=path,
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


async def _match(
    session_factory: async_sessionmaker[AsyncSession], *, chat_pk: int, message_id: int
) -> int | None:
    async with session_factory() as session:
        message = (
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
        item_id = await match_response(session, message)
        await session.commit()
        return item_id


async def _drain_existing_backlog(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """The sweep claims the shared test database's whole unjudged backlog — drain it rule-only
    first so this file's counts are deterministic regardless of suite order (`test_sweep.py`)."""
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
    """A measured group with a primary owner since yesterday, one student, and an active
    attention profile beside the active moderation one."""
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    owner = await insert_moderator(display_name="Owner")
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=owner["moderator_id"],
        valid_from=_now() - timedelta(days=2),
    )
    user_pk = await insert_user(tg_user_id=_rand_id())
    await seeded_attention_profile(active=True)
    return {"chat_pk": chat_pk, "user_pk": user_pk, "owner": owner}


# --- 1-3: who opens ------------------------------------------------------------------------------


async def test_a_rule_question_opens_one_rule_item_with_no_model_link(
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

    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "rule"
    assert item["rule_version"] == 1
    assert item["attention_judgement_id"] is None
    assert item["message_classification_id"] is None


async def test_a_later_asking_judgement_never_adds_or_changes_a_rule_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """A message whose own words open the rules is never judged (AE2), so the late judgement here
    is a rule-declined member of the same burst."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_RULE_QUESTION,
    )
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=sent_at + timedelta(seconds=20),
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    [before] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])

    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    outcome = await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=2,
        intent="asking",
    )
    assert outcome == "judged"
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=2
    )
    assert message["attention_evaluated_at"] is not None  # an item exists — nothing to re-judge
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == [before]


async def test_an_implicit_question_the_rules_miss_opens_a_model_item(
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
    judgement_id = await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    item_id = await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["id"] == item_id
    assert item["source"] == "ai"
    assert item["rule_version"] is None
    assert item["attention_judgement_id"] == judgement_id
    assert item["message_classification_id"] is None
    assert item["status"] == "open"
    assert item["opened_at"] == sent_at
    assert item["telegram_message_id"] == 1
    assert item["responsible_moderator_id"] == seeded["owner"]["moderator_id"]
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_item_id"] == item_id
    assert message["attention_evaluated_at"] is not None


# --- 4: what never opens ------------------------------------------------------------------------


async def test_with_the_switch_blank_an_asking_judgement_opens_nothing(
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
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    assert (
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=None,
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_a_judgement_recorded_before_the_switch_opens_nothing(
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
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(enabled_from=sent_at + timedelta(minutes=1)),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_a_judgement_recorded_max_age_after_the_question_opens_nothing(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    # Decision 2 (2026-10-03): it would be born expired, against a moderator whose queue never
    # showed it.
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
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(enabled_from=sent_at - timedelta(days=1)),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_a_moderators_or_bots_message_never_opens_whatever_the_model_says(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_user: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    bot_pk = await insert_user(tg_user_id=_rand_id(), is_bot=True)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=bot_pk,
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    assert (
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=bot_pk,
            around=sent_at,
            ai=_ai(),
        )
        is None
    )


async def test_an_acknowledgement_is_never_judged_and_never_opens(
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
        original_text="تمام",
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    assert (
        await _attend(
            classification_session_factory,
            scripted_gateway,
            classification_redis,
            settings,
            chat_pk=seeded["chat_pk"],
            message_id=1,
            intent="asking",
        )
        == "excluded"
    )

    assert (
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )


# --- 5-8: both orderings, replays, catch-up ------------------------------------------------------


async def test_case_a_judged_before_the_settle_opens_at_burst_judgement(
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
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )
    # Not yet judged: the request is a no-op, the pending burst judgement will see the judgement.
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is None

    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["attention_judgement_id"] == await _judgement_id(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )


async def test_case_b_judged_after_the_settle_is_reconciled_by_the_sweep(
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
    assert (
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )

    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
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

    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["opened_at"] == sent_at  # the question's time, never the judgement's


async def test_a_needs_no_response_judgement_never_puts_a_message_back_on_the_work_list(
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
        original_text=_GREETING,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="social",
    )

    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is not None


async def test_with_the_switch_blank_the_attention_judgement_never_touches_the_work_list(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """Shadow mode: the instruction is set, the switch is blank — the judgement is recorded and
    re-flags nothing (W2)."""
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=None,
    )
    outcome = await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        _settings_with_switch(classification_settings, None),
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )

    assert outcome == "judged"
    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is not None


async def test_with_the_switch_set_the_classifier_never_touches_the_work_list(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """W3: the classification's needs-response is measurement only — a live, confident
    `needs_response=True` prediction re-flags nothing and opens nothing."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _classify(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        answer={
            "category": "QUESTION_COURSE",
            "needs_response": True,
            "needs_moderation": False,
            "severity": "none",
            "confidence": 0.95,
        },
    )

    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is not None
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


async def test_replays_and_concurrent_judgements_converge_on_one_item(
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
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    for _ in range(2):
        await _attend(
            classification_session_factory,
            scripted_gateway,
            classification_redis,
            settings,
            chat_pk=seeded["chat_pk"],
            message_id=1,
            intent="asking",
        )

    async def judge() -> int | None:
        return await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )

    results = await asyncio.gather(judge(), judge(), judge())
    await judge()
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    items = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert len(items) == 1
    assert set(results) == {items[0]["id"]}


async def test_an_attention_judgement_racing_an_open_burst_judgement_still_converges(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """The burst judgement declines and holds `chat_lock` uncommitted while the attention
    judgement is recorded: `judge_one` waits for the lock, then re-flags the now-judged message —
    never lost."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))

    async with classification_session_factory() as judging:
        burst = await assemble_burst(
            judging,
            telegram_chat_id=seeded["chat_pk"],
            telegram_user_id=seeded["user_pk"],
            message_thread_id=None,
            around=sent_at,
            gap_s=_GAP_S,
        )
        assert await open_item(judging, burst, ai=_ai()) is None
        attending = asyncio.create_task(
            _attend(
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

    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"


async def test_request_rejudgement_is_a_no_op_once_an_item_exists_or_before_judgement(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
) -> None:
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_RULE_QUESTION,
    )
    async with classification_session_factory() as session:
        assert (
            await request_rejudgement(session, telegram_chat_id=seeded["chat_pk"], message_id=1)
            is False
        )  # not judged yet — the pending burst judgement will see the attention judgement
        await session.commit()
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=None,
    )
    async with classification_session_factory() as session:
        assert (
            await request_rejudgement(session, telegram_chat_id=seeded["chat_pk"], message_id=1)
            is False
        )  # an item already covers it (E4)
        await session.commit()


async def test_a_catch_up_judgement_never_reopens_judgement_or_opens_an_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """W2 re-flags only after a live insert; A1 never opens from a catch-up row (N3)."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
        path="catch_up",
    )

    message = await _message(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert message["attention_evaluated_at"] is not None
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())
    assert (
        await _judge(
            classification_session_factory,
            chat_pk=seeded["chat_pk"],
            user_pk=seeded["user_pk"],
            around=sent_at,
            ai=_ai(),
        )
        is None
    )
    assert await _items(classification_session_factory, chat_pk=seeded["chat_pk"]) == []


# --- 9-10: response tracking is TG-M3's, unchanged ----------------------------------------------


async def test_a_moderators_direct_reply_answers_a_model_item(
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
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )
    item_id = await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    reply_at = sent_at + timedelta(seconds=150)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=seeded["owner"]["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="نعم الساعة ٨",
    )

    assert (
        await _match(classification_session_factory, chat_pk=seeded["chat_pk"], message_id=2)
        == item_id
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["status"] == "answered"
    assert item["first_response_kind"] == "direct_reply"
    assert item["first_response_message_id"] == 2
    assert item["first_response_at"] == reply_at
    assert item["first_response_moderator_id"] == seeded["owner"]["moderator_id"]
    assert (item["first_response_at"] - item["opened_at"]).total_seconds() == 150


async def test_a_moderators_group_message_answers_only_the_oldest_open_item(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_user: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    other_pk = await insert_user(tg_user_id=_rand_id())
    first_at = _now() - timedelta(minutes=20)
    second_at = _now() - timedelta(minutes=15)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=first_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=second_at,
        telegram_user_id=other_pk,
        original_text=_RULE_QUESTION,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )
    model_item = await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=first_at,
        ai=_ai(),
    )
    rule_item = await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=other_pk,
        around=second_at,
        ai=_ai(),
    )
    answer_at = _now() - timedelta(minutes=5)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=3,
        sent_at=answer_at,
        telegram_user_id=seeded["owner"]["telegram_user_id"],
        is_from_moderator=True,
        original_text="المحاضرة بكرة الساعة ٨",
    )

    assert (
        await _match(classification_session_factory, chat_pk=seeded["chat_pk"], message_id=3)
        == model_item
    )

    by_id = {
        item["id"]: item
        for item in await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    }
    assert by_id[model_item]["status"] == "answered"
    assert by_id[model_item]["first_response_kind"] == "group_message"
    assert by_id[rule_item]["status"] == "open"  # C3: one message never clears a backlog


async def test_a_question_answered_before_the_late_judgement_opens_already_answered(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """TG-M3 C10: the item exists historically and the lookback closes it in the same transaction
    that opens it — it is never seen open, and its response time is the real one."""
    await _drain_existing_backlog(classification_session_factory)
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )
    reply_at = sent_at + timedelta(seconds=40)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=reply_at,
        telegram_user_id=seeded["owner"]["telegram_user_id"],
        is_from_moderator=True,
        reply_to_message_id=1,
        original_text="نعم",
    )
    assert (
        await _match(classification_session_factory, chat_pk=seeded["chat_pk"], message_id=2)
        is None
    )

    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["status"] == "answered"
    assert item["first_response_kind"] == "direct_reply"
    assert (item["first_response_at"] - item["opened_at"]).total_seconds() == 40


# --- 11: the clock and the owner are the burst's, never the model's ------------------------------


async def test_opened_at_is_the_bursts_earliest_member_even_when_the_model_flagged_a_later_one(
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

    item_id = await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=question_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["telegram_message_id"] == 1
    assert item["opened_at"] == greeting_at
    assert item["attention_judgement_id"] == question_judgement
    for message_id in (1, 2):
        message = await _message(
            classification_session_factory, chat_pk=seeded["chat_pk"], message_id=message_id
        )
        assert message["attention_item_id"] == item_id


async def test_an_edited_member_keeps_its_first_posted_judgement_and_the_e3_clock(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    # Decision 3 (2026-10-03): the judgement of the first-posted words still counts; the anchor
    # and the clock are E3's — the edited member, at `edited_at`.
    sent_at = _now() - timedelta(minutes=10)
    edited_at = sent_at + timedelta(seconds=15)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
        edited_at=edited_at,
    )
    await insert_attention_judgement(
        telegram_chat_id=seeded["chat_pk"], telegram_message_id=1, intent="asking"
    )

    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["opened_at"] == edited_at


async def test_the_responsible_moderator_is_the_owner_at_the_question_not_at_judgement(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    classification_seeded_profile: None,
    seeded_attention_profile: Any,
    insert_chat: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_assignment: Any,
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    await _drain_existing_backlog(classification_session_factory)
    await seeded_attention_profile(active=True)
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    before = await insert_moderator(display_name="Before")
    after = await insert_moderator(display_name="After")
    sent_at = _now() - timedelta(minutes=10)
    handover_at = sent_at + timedelta(minutes=2)
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=before["moderator_id"],
        valid_from=sent_at - timedelta(days=1),
        valid_to=handover_at,
    )
    await insert_assignment(
        telegram_chat_id=chat_pk,
        moderator_id=after["moderator_id"],
        valid_from=handover_at,
    )
    user_pk = await insert_user(tg_user_id=_rand_id())
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=user_pk,
        original_text=_IMPLICIT_QUESTION,
    )
    await _judge(
        classification_session_factory, chat_pk=chat_pk, user_pk=user_pk, around=sent_at, ai=_ai()
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=chat_pk,
        message_id=1,
        intent="asking",
    )
    await sweep_unjudged_bursts_once(classification_session_factory, gap_s=_GAP_S, ai=_ai())

    [item] = await _items(classification_session_factory, chat_pk=chat_pk)
    assert item["responsible_moderator_id"] == before["moderator_id"]


# --- decision 1: one message, two units of work, each from its own judgement -------------------


@pytest.mark.parametrize(
    ("answer", "expected_route", "incident_opens"),
    [
        (
            {
                "category": "COMPLAINT",
                "needs_response": True,
                "needs_moderation": True,
                "severity": "medium",
                "confidence": 0.95,
            },
            "possible_violation",
            False,
        ),
        (
            {
                "category": "OTHER",
                "needs_response": True,
                "needs_moderation": True,
                "severity": "high",
                "confidence": 0.95,
            },
            "incident",
            True,
        ),
    ],
)
async def test_an_incident_from_the_classification_and_a_question_from_the_attention_judgement(
    answer: dict[str, Any],
    expected_route: str,
    incident_opens: bool,
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, Any],
    insert_message: Any,
    scripted_gateway: Any,
    classification_redis: Any,
    classification_settings: Any,
) -> None:
    """On one message: the classification routes the violation side (and opens an incident when
    confident), the attention judgement opens the question item — each from its own record, and
    the item links the judgement, never the prediction (O3′)."""
    sent_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=sent_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    settings = _settings_with_switch(classification_settings, _now() - timedelta(days=1))
    await _classify(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        answer=answer,
    )
    await _attend(
        classification_session_factory,
        scripted_gateway,
        classification_redis,
        settings,
        chat_pk=seeded["chat_pk"],
        message_id=1,
        intent="asking",
    )
    await _judge(
        classification_session_factory,
        chat_pk=seeded["chat_pk"],
        user_pk=seeded["user_pk"],
        around=sent_at,
        ai=_ai(),
    )

    async with classification_session_factory() as session:
        route = (
            await session.execute(
                sa.select(message_classifications.c.route).where(
                    message_classifications.c.telegram_chat_id == seeded["chat_pk"],
                    message_classifications.c.telegram_message_id == 1,
                )
            )
        ).scalar_one()
        incidents = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(moderation_incidents)
                .where(moderation_incidents.c.telegram_chat_id == seeded["chat_pk"])
            )
        ).scalar_one()
    assert route == expected_route
    assert incidents == (1 if incident_opens else 0)
    [item] = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert item["source"] == "ai"
    assert item["attention_judgement_id"] == await _judgement_id(
        classification_session_factory, chat_pk=seeded["chat_pk"], message_id=1
    )
    assert item["message_classification_id"] is None


# --- re-derivation reaches the same answer as live judgement -------------------------------------


async def test_rederive_with_attention_reaches_the_live_answer_and_never_reaches_back(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    seeded: dict[str, Any],
    insert_message: Any,
    insert_attention_judgement: Any,
) -> None:
    switched_on_at = _now() - timedelta(minutes=30)
    before_at = _now() - timedelta(minutes=50)
    after_at = _now() - timedelta(minutes=10)
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=1,
        sent_at=before_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    await insert_message(
        telegram_chat_id=seeded["chat_pk"],
        message_id=2,
        sent_at=after_at,
        telegram_user_id=seeded["user_pk"],
        original_text=_IMPLICIT_QUESTION,
    )
    for message_id, recorded_at in (
        (1, before_at + timedelta(seconds=2)),
        (2, after_at + timedelta(seconds=2)),
    ):
        await insert_attention_judgement(
            telegram_chat_id=seeded["chat_pk"],
            telegram_message_id=message_id,
            intent="asking",
            created_at=recorded_at,
        )

    report = await rederive_chat_attention(
        classification_session_factory,
        chat_id=classification_chat_id,
        gap_s=_GAP_S,
        max_age_s=_MAX_AGE_S,
        ai=_ai(enabled_from=switched_on_at),
    )

    items = await _items(classification_session_factory, chat_pk=seeded["chat_pk"])
    assert report.opened == 1
    assert [(item["telegram_message_id"], item["source"]) for item in items] == [(2, "ai")]
