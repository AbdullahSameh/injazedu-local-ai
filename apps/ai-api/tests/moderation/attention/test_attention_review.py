"""The read-only Step 3 review (`app/scripts/attention_review.py`;
`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 3). It measures and never
writes. Its output is counts only: rule literals, reasons and outcomes, never a message's text.

- **Outcomes by opener:** answered (direct or group), dismissed by reason, expired, open.
- **Which rule signal opened each rule item, against its outcome.** This is the evidence for rule
  set v2. A literal that is an item's only signal is the one a fix could remove.
- **The shadow "answered by a member" signal, against the outcome.** It is a member's direct reply,
  then the asker's acknowledgement of it, and no follow-up question from the asker. It is measured
  before anything is shown or automated.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.domain.moderation.attention import opening_signals
from app.infrastructure.models_moderation import attention_items
from app.scripts.attention_review import format_report, member_answer_candidate, review
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SENTINEL = "SENTINELWORD"


# --- The pure parts ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["متي الاختبار؟"], ("?", "متي")),
        (["ايه"], ("ايه",)),
        (["اهم شي الالغاء قبل 72 ساعه من الاختبار"], ("من",)),
        (["شكرا"], ()),
        ([None, "كم مده الاختبار"], ("كم",)),
    ],
)
def test_opening_signals_names_every_signal_present(
    texts: list[str | None], expected: tuple[str, ...]
) -> None:
    assert opening_signals(texts) == expected


@pytest.mark.parametrize(
    ("member_replies", "asker_back", "expected"),
    [
        (1, ["شكرا"], True),
        (2, ["جزاك الله خير"], True),
        (0, ["شكرا"], False),
        (1, [], False),
        (1, ["طيب كيف اسجل؟"], False),
        (1, ["شكرا", "طيب كيف اسجل؟"], False),
    ],
)
def test_member_answer_candidate(
    member_replies: int, asker_back: list[str], expected: bool
) -> None:
    assert member_answer_candidate(member_replies=member_replies, asker_back=asker_back) is expected


# --- Against the database ---------------------------------------------------------------------


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _item(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_pk: int,
    message_id: int,
    opened_at: datetime,
    status: str,
    close_reason: str | None = None,
    response: tuple[int, datetime, str] | None = None,
) -> None:
    extra: dict[str, Any] = {}
    if response is not None:
        extra = {
            "first_response_message_id": response[0],
            "first_response_at": response[1],
            "first_response_kind": response[2],
        }
    async with session_factory() as session:
        await session.execute(
            attention_items.insert().values(
                telegram_chat_id=chat_pk,
                telegram_message_id=message_id,
                opened_at=opened_at,
                source="rule",
                rule_version=1,
                status=status,
                close_reason=close_reason,
                **extra,
            )
        )
        await session.commit()


async def test_the_review_counts_outcomes_signals_and_the_shadow_signal(
    attention_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_user: Any,
    insert_message: Any,
    attention_chat_id: int,
) -> None:
    t0 = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
    chat_pk = await insert_chat(chat_id=attention_chat_id)
    askers = [await insert_user(tg_user_id=_rand_id()) for _ in range(4)]
    asker_a, asker_b, asker_c, asker_d = askers
    member = await insert_user(tg_user_id=_rand_id())
    moderator = await insert_user(tg_user_id=_rand_id())

    # A: a member answers, the asker thanks them; dismissed "Answered by a member".
    await insert_message(
        telegram_chat_id=chat_pk, message_id=1, sent_at=t0,
        telegram_user_id=asker_a, original_text="متى الاختبار؟",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=2, sent_at=t0 + timedelta(minutes=1),
        telegram_user_id=member, reply_to_message_id=1, original_text=f"الاربعاء {_SENTINEL}",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=3, sent_at=t0 + timedelta(minutes=2),
        telegram_user_id=asker_a, reply_to_message_id=2, original_text="شكرا",
    )
    await _item(
        attention_session_factory, chat_pk=chat_pk, message_id=1, opened_at=t0,
        status="dismissed", close_reason="member_answered",
    )

    # B: "ايه" alone opened it; dismissed "Member discussion"; nobody replied.
    await insert_message(
        telegram_chat_id=chat_pk, message_id=10, sent_at=t0 + timedelta(minutes=10),
        telegram_user_id=asker_b, original_text="إيه",
    )
    await _item(
        attention_session_factory, chat_pk=chat_pk, message_id=10,
        opened_at=t0 + timedelta(minutes=10), status="dismissed", close_reason="member_discussion",
    )

    # C: answered by a moderator's direct reply.
    await insert_message(
        telegram_chat_id=chat_pk, message_id=20, sent_at=t0 + timedelta(minutes=20),
        telegram_user_id=asker_c, original_text="كم مدة الاختبار",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=21, sent_at=t0 + timedelta(minutes=22),
        telegram_user_id=moderator, is_from_moderator=True, reply_to_message_id=20,
        original_text="ساعتين",
    )
    await _item(
        attention_session_factory, chat_pk=chat_pk, message_id=20,
        opened_at=t0 + timedelta(minutes=20), status="answered",
        response=(21, t0 + timedelta(minutes=22), "direct_reply"),
    )

    # D: a member replies, but the asker follows up with another question; still open.
    await insert_message(
        telegram_chat_id=chat_pk, message_id=30, sent_at=t0 + timedelta(minutes=30),
        telegram_user_id=asker_d, original_text="كم فرصه تربوي هاذي السنه ؟",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=31, sent_at=t0 + timedelta(minutes=31),
        telegram_user_id=member, reply_to_message_id=30, original_text="اثنين",
    )
    await insert_message(
        telegram_chat_id=chat_pk, message_id=32, sent_at=t0 + timedelta(minutes=32),
        telegram_user_id=asker_d, reply_to_message_id=31, original_text="طيب كيف اسجل؟",
    )
    await _item(
        attention_session_factory, chat_pk=chat_pk, message_id=30,
        opened_at=t0 + timedelta(minutes=30), status="open",
    )

    async with attention_session_factory() as session:
        report = await review(
            session, period_from=t0, period_to=t0 + timedelta(hours=1), chat_id=chat_pk
        )

    assert report.outcomes == {
        ("rule", "dismissed:member_answered"): 1,
        ("rule", "dismissed:member_discussion"): 1,
        ("rule", "answered:direct_reply"): 1,
        ("rule", "open"): 1,
    }
    # Only-signal items, by literal: B's "ايه" and C's "كم"; A and D carry "?" and a literal.
    assert report.single_signal_outcomes == {
        ("ايه", "dismissed:member_discussion"): 1,
        ("كم", "answered:direct_reply"): 1,
    }
    assert report.shadow == {
        (True, "dismissed:member_answered"): 1,
        (False, "dismissed:member_discussion"): 1,
        (False, "answered:direct_reply"): 1,
        (False, "open"): 1,
    }

    text = format_report(report)
    assert "dismissed:member_answered" in text
    assert _SENTINEL not in text
    assert "الاربعاء" not in text
