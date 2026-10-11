"""T032, T067 — C10a and C10b, the attention judgement's coverage, intents and timeliness, and
C10c, the operator-added items by anchor status and burst size
(`specs/011-tg-m5-3-attention-judgement/contracts/attention-metrics.md` §2, M26-M32). C10c's
scenario is its own, below the C10a/C10b tests.

One hand-computed scenario in one group, period `[BASE − 1 h, BASE + 6 h)`:

| # | Record(s) | C10a | C10b |
|---|---|---|---|
| 1 | A `asking` at `sent_at + 90 s` | judged | A: asking, on time (the gap exactly) |
| 2 | A `discussion` at `+91 s` | judged | A: discussion, late |
| 3 | B `informing` at `+10 s` | judged | B: informing, on time |
| 4 | excluded `rule_opens` | excluded | — |
| 5 | excluded `moderator` | excluded | — |
| 6 | failed `provider_unreachable`, then `model_truncated` | failed (latest) | — |
| 7 | failed `model_timeout`, then A `asking` at `+5 s` | judged (wins) | A: asking, on time |
| 8 | nothing | not judged yet | — |
| 9 | nothing | not judged yet | — |
| 10 | A `social`, `path = 'catch_up'` | judged | never (live only) |

Not counted: message 11, judged but posted after the period, and message 12 in another group.

So C10a reads 10 = 5 + 2 + 1 + 2, with exclusions `rule_opens` 1 and `moderator` 1, and failures
by latest reason `model_truncated` 1 (message 7's failure is behind its judgement). C10b reads
model A: judged 3, asking 2, discussion 1, on time 2; model B: judged 1, informing 1, on time 1.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.metrics import (
    attention_judgement_intent_stats,
    attention_judgement_volume_stats,
    attention_operator_added_stats,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_BASE = datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC)
_PERIOD_FROM = _BASE - timedelta(hours=1)
_PERIOD_TO = _BASE + timedelta(hours=6)
_GAP_S = 90


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _scenario(
    *,
    insert_chat: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
    seeded_attention_profile: Any,
) -> dict[str, int]:
    chat = await insert_chat(chat_id=-_rand_id())
    other_chat = await insert_chat(chat_id=-_rand_id())
    model_a = await seeded_attention_profile(active=False)
    model_b = await seeded_attention_profile(active=False)

    def sent(n: int) -> datetime:
        return _BASE + timedelta(minutes=n)

    for n in range(1, 11):
        await insert_message(telegram_chat_id=chat, message_id=n, sent_at=sent(n))
    await insert_message(
        telegram_chat_id=chat, message_id=11, sent_at=_PERIOD_TO + timedelta(minutes=1)
    )
    await insert_message(telegram_chat_id=other_chat, message_id=12, sent_at=sent(12))

    async def judge(n: int, model: int, intent: str, after_s: int, **kwargs: Any) -> None:
        await insert_attention_judgement(
            telegram_chat_id=kwargs.pop("chat", chat),
            telegram_message_id=n,
            intent=intent,
            model_profile_id=model,
            created_at=sent(n) + timedelta(seconds=after_s),
            **kwargs,
        )

    async def attempt(n: int, outcome: str, reason: str, after_s: int) -> None:
        await insert_attention_attempt(
            telegram_chat_id=chat,
            telegram_message_id=n,
            outcome=outcome,
            reason=reason,
            model_profile_id=model_a if outcome == "failed" else None,
            created_at=sent(n) + timedelta(seconds=after_s),
        )

    await judge(1, model_a, "asking", _GAP_S)
    await judge(2, model_a, "discussion", _GAP_S + 1)
    await judge(3, model_b, "informing", 10)
    await attempt(4, "excluded", "rule_opens", 1)
    await attempt(5, "excluded", "moderator", 1)
    await attempt(6, "failed", "provider_unreachable", 30)
    await attempt(6, "failed", "model_truncated", 60)
    await attempt(7, "failed", "model_timeout", 2)
    await judge(7, model_a, "asking", 5)
    await judge(10, model_a, "social", 5, path="catch_up")
    await insert_attention_judgement(
        telegram_chat_id=chat,
        telegram_message_id=11,
        intent="asking",
        model_profile_id=model_a,
    )
    await judge(12, model_a, "asking", 5, chat=other_chat)

    return {"chat": chat, "model_a": model_a, "model_b": model_b}


async def test_c10a_partitions_every_message_with_its_breakdowns(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
    seeded_attention_profile: Any,
) -> None:
    ids = await _scenario(
        insert_chat=insert_chat,
        insert_message=insert_message,
        insert_attention_judgement=insert_attention_judgement,
        insert_attention_attempt=insert_attention_attempt,
        seeded_attention_profile=seeded_attention_profile,
    )

    async with classification_session_factory() as session:
        volume = await attention_judgement_volume_stats(
            session, period_from=_PERIOD_FROM, period_to=_PERIOD_TO, chat_id=ids["chat"]
        )

    assert volume == {
        "messages": 10,
        "judged": 5,
        "excluded": 2,
        "failed": 1,
        "not_judged_yet": 2,
        "excluded_by_reason": {"rule_opens": 1, "moderator": 1},
        "failed_by_reason": {"model_truncated": 1},
    }
    assert volume["messages"] == (
        volume["judged"] + volume["excluded"] + volume["failed"] + volume["not_judged_yet"]
    )


async def test_c10b_counts_intents_and_on_time_per_model_live_only(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
    seeded_attention_profile: Any,
) -> None:
    ids = await _scenario(
        insert_chat=insert_chat,
        insert_message=insert_message,
        insert_attention_judgement=insert_attention_judgement,
        insert_attention_attempt=insert_attention_attempt,
        seeded_attention_profile=seeded_attention_profile,
    )

    async with classification_session_factory() as session:
        rows = await attention_judgement_intent_stats(
            session,
            period_from=_PERIOD_FROM,
            period_to=_PERIOD_TO,
            chat_id=ids["chat"],
            gap_s=_GAP_S,
        )

    by_model = {(r["model_profile_id"], r["prompt_version"]): r for r in rows}
    assert set(by_model) == {(ids["model_a"], "attention_test"), (ids["model_b"], "attention_test")}

    def counts(row: dict[str, Any]) -> tuple[int, ...]:
        return (
            row["judged"],
            row["asking"],
            row["discussion"],
            row["informing"],
            row["social"],
            row["offering"],
            row["other"],
            row["on_time"],
        )

    # judged, asking, discussion, informing, social, offering, other, on_time
    assert counts(by_model[(ids["model_a"], "attention_test")]) == (3, 2, 1, 0, 0, 0, 0, 2)
    assert counts(by_model[(ids["model_b"], "attention_test")]) == (1, 0, 0, 1, 0, 0, 0, 1)


async def test_c10b_on_time_moves_with_the_gap(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
    seeded_attention_profile: Any,
) -> None:
    """`:gap_s` is the panel's `MODERATION_BURST_GAP_S`: at 91 s, message 2 is on time too."""
    ids = await _scenario(
        insert_chat=insert_chat,
        insert_message=insert_message,
        insert_attention_judgement=insert_attention_judgement,
        insert_attention_attempt=insert_attention_attempt,
        seeded_attention_profile=seeded_attention_profile,
    )

    async with classification_session_factory() as session:
        rows = await attention_judgement_intent_stats(
            session,
            period_from=_PERIOD_FROM,
            period_to=_PERIOD_TO,
            chat_id=ids["chat"],
            gap_s=_GAP_S + 1,
        )

    model_a = next(r for r in rows if r["model_profile_id"] == ids["model_a"])
    assert (model_a["judged"], model_a["on_time"]) == (3, 3)


# --- C10c: operator-added items, by anchor status and burst size (T067, M30-M32) -----------------
#
# One group, period `[BASE − 1 h, BASE + 6 h)`, anchors ten minutes apart so no two neighbour. The
# anchors are from one member, apart from #6, a channel posting as itself (`sender_chat`, no user):
#
# | # | Anchor's attention record | Its neighbour (same sender unless noted) | C10c |
# |---|---|---|---|
# | 1 | `asking` | none | judged_asking, single |
# | 2 | `asking` | same thread, exactly `+90 s` | judged_asking, multi |
# | 3 | `discussion` | same thread, `+91 s` | judged_discussion, single |
# | 4 | excluded `rule_opens` | same thread, exactly `−90 s` | excluded_rule_opens, multi |
# | 5 | failed | another thread, `+30 s` | failed, single |
# | 6 | nothing (`sender_chat`) | the same channel, `+10 s` | none, single (M30) |
# | 7 | nothing | same thread (a topic), `+30 s` | none, multi |
# | 8 | failed, then `discussion` | none | judged_discussion, single (the judgement wins) |
#
# Not counted: a rule item on an `asking` message (#9), an operator item opened after the period
# (#10), and an operator item in another group (#11).

_C10C_GAP_S = 90


async def _c10c_scenario(
    *,
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_attention_item: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
) -> int:
    chat = await insert_chat(chat_id=-_rand_id())
    other_chat = await insert_chat(chat_id=-_rand_id())
    member = await insert_user(tg_user_id=_rand_id())
    channel = -_rand_id()

    def sent(n: int) -> datetime:
        return _BASE + timedelta(minutes=10 * n)

    async def message(n: int, at: datetime, **kwargs: Any) -> None:
        sender: dict[str, Any] = (
            {"sender_chat_id": kwargs.pop("sender_chat_id")}
            if "sender_chat_id" in kwargs
            else {"telegram_user_id": member}
        )
        await insert_message(
            telegram_chat_id=kwargs.pop("chat", chat),
            message_id=n,
            sent_at=at,
            **sender,
            **kwargs,
        )

    async def operator_item(n: int, **kwargs: Any) -> None:
        await insert_attention_item(
            telegram_chat_id=kwargs.pop("chat", chat),
            telegram_message_id=n,
            opened_at=kwargs.pop("opened_at", sent(n)),
            source=kwargs.pop("source", "operator"),
            rule_version=kwargs.pop("rule_version", None),
        )

    async def judge(n: int, intent: str) -> None:
        await insert_attention_judgement(
            telegram_chat_id=chat,
            telegram_message_id=n,
            intent=intent,
            created_at=sent(n) + timedelta(seconds=5),
        )

    async def attempt(n: int, outcome: str, reason: str) -> None:
        await insert_attention_attempt(
            telegram_chat_id=chat,
            telegram_message_id=n,
            outcome=outcome,
            reason=reason,
            created_at=sent(n) + timedelta(seconds=2),
        )

    # Neighbours take message ids from 101 upwards; they are never anchors.
    await message(1, sent(1))
    await judge(1, "asking")

    await message(2, sent(2))
    await message(102, sent(2) + timedelta(seconds=_C10C_GAP_S))
    await judge(2, "asking")

    await message(3, sent(3))
    await message(103, sent(3) + timedelta(seconds=_C10C_GAP_S + 1))
    await judge(3, "discussion")

    await message(4, sent(4))
    await message(104, sent(4) - timedelta(seconds=_C10C_GAP_S))
    await attempt(4, "excluded", "rule_opens")

    await message(5, sent(5))
    await message(105, sent(5) + timedelta(seconds=30), message_thread_id=7)
    await attempt(5, "failed", "model_truncated")

    await message(6, sent(6), sender_chat_id=channel)
    await message(106, sent(6) + timedelta(seconds=10), sender_chat_id=channel)

    await message(7, sent(7), message_thread_id=7)
    await message(107, sent(7) + timedelta(seconds=30), message_thread_id=7)

    await message(8, sent(8))
    await attempt(8, "failed", "model_timeout")
    await judge(8, "discussion")

    await message(9, sent(9))
    await judge(9, "asking")

    await message(10, sent(10))
    await message(11, sent(11), chat=other_chat)

    for n in range(1, 9):
        await operator_item(n)
    await operator_item(9, source="rule", rule_version=1)
    await operator_item(10, opened_at=_PERIOD_TO + timedelta(minutes=1))
    await operator_item(11, chat=other_chat)

    return chat


async def test_c10c_splits_operator_added_items_by_anchor_status_and_burst_size(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_attention_item: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
) -> None:
    chat = await _c10c_scenario(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        insert_attention_item=insert_attention_item,
        insert_attention_judgement=insert_attention_judgement,
        insert_attention_attempt=insert_attention_attempt,
    )

    async with classification_session_factory() as session:
        rows = await attention_operator_added_stats(
            session,
            period_from=_PERIOD_FROM,
            period_to=_PERIOD_TO,
            chat_id=chat,
            gap_s=_C10C_GAP_S,
        )

    assert {(r["anchor_status"], r["multi_message"]): r["items"] for r in rows} == {
        ("judged_asking", False): 1,
        ("judged_asking", True): 1,
        ("judged_discussion", False): 2,
        ("excluded_rule_opens", True): 1,
        ("failed", False): 1,
        ("none", False): 1,
        ("none", True): 1,
    }
    assert sum(r["items"] for r in rows) == 8


async def test_c10c_multi_message_moves_with_the_gap(
    classification_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    insert_attention_item: Any,
    insert_attention_judgement: Any,
    insert_attention_attempt: Any,
) -> None:
    """`:gap_s` is `MODERATION_BURST_GAP_S`: at 91 s, #3's neighbour is inside the gap. A channel
    anchor stays single whatever the gap (M30)."""
    chat = await _c10c_scenario(
        insert_chat=insert_chat,
        insert_user=insert_user,
        insert_message=insert_message,
        insert_attention_item=insert_attention_item,
        insert_attention_judgement=insert_attention_judgement,
        insert_attention_attempt=insert_attention_attempt,
    )

    async with classification_session_factory() as session:
        rows = await attention_operator_added_stats(
            session,
            period_from=_PERIOD_FROM,
            period_to=_PERIOD_TO,
            chat_id=chat,
            gap_s=_C10C_GAP_S + 1,
        )

    counts = {(r["anchor_status"], r["multi_message"]): r["items"] for r in rows}
    assert counts[("judged_discussion", True)] == 1
    assert counts[("judged_discussion", False)] == 1
    assert counts[("none", False)] == 1
