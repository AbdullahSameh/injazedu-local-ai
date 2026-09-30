"""T063 (US6) — research probe 10's fourteen-message, two-model scenario, run against every
statement of `contracts/classification-metrics.md` (C1-C8) and matched to the hand-computed
figures recorded there and in `research.md` §1 probe 10 (`tasks.md` T063, FR-046...FR-051,
SC-009, SC-012, SC-017).

Built directly through `conftest.py`'s builders (`insert_message`, `insert_prediction`,
`insert_incident`, `insert_action`, `insert_attention_item`) rather than through `classify_one` —
this test proves the **figures**, not the pipeline that produces the rows they read (US1-US4
already prove that). Every row placed here is scoped to one chat and one period window, so a
second, unrelated run of the suite against the same database cannot contaminate these counts
(mirrors `tests/moderation/incidents/test_metrics.py`'s own discipline).

The scenario (research §1 probe 10, `tasks.md` T063):

- **Three question items** (C1): a rule-kept item (`I1`, a two-message burst — a greeting anchor
  the model calls chit-chat, then a genuine question the model says needs an answer — C6's own
  fixture too, M17), a rule-dismissed item (`I2`, the model agrees the dismissal was right) and an
  operator-added item (`I3`, the model catches what the rules missed).
- **Two unverified messages** (C2): one per model — a message each says needs an answer where no
  question item exists at all.
- **Four incidents** (C3): two independent operator flags (`i1` agreed and same-category, `i2`
  disagreed and closed as a false positive), one list-prompted operator flag (`i3`, agreed and
  same-category) and one model-opened incident (`i4`, closed as a false positive) — `fp_closures`
  spans `i2` and `i4`; `fp_model_raised` counts only `i4` (`i2`'s prediction disagreed).
- **One possible-violation entry** (C4): a live `possible_violation` prediction (`M11`) that
  anchors no incident.
- **Three more messages** (C5): one excluded, one failed, one not yet classified — with the eleven
  above, `14 = 11 + 1 + 1 + 1`.
- **Detection latency** (C8): the model's own incident (`i4`) at 4s; the three operator incidents
  (`i1`, `i2`, `i3`) at 30s / 120s / 180s — median 120s, p90 168s (`percentile_cont` interpolating
  between the 120s and 180s samples).

Model A classifies every message above except `M6` (Model B's own unverified message) — Model B
never appears in C1 or C3, proving K3's "never pooled" the only way it can be proven: by a model
simply having no row where it did nothing.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.moderation.metrics import (
    accuracy_by_rule_version,
    classification_labels_for_items,
    classification_question_stats,
    classification_unverified_stats,
    classification_violation_stats,
    classification_volume_stats,
    detection_latency_stats,
    possible_violations,
)
from app.infrastructure.config import Settings
from app.infrastructure.models import model_profiles
from app.infrastructure.models_moderation import message_classification_attempts, telegram_messages
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_BASE = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


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


async def _link_to_item(
    session_factory: async_sessionmaker[AsyncSession], *, message_pk: int, item_id: int
) -> None:
    """Sets a burst message's `attention_item_id` directly — C1/C6's join follows this column,
    not a second derivation (`data-model.md` §1 of TG-M3)."""
    async with session_factory() as session:
        await session.execute(
            telegram_messages.update()
            .where(telegram_messages.c.id == message_pk)
            .values(attention_item_id=item_id)
        )
        await session.commit()


async def _insert_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_pk: int,
    message_id: int,
    outcome: str,
    reason: str,
    model_profile_id: int | None = None,
) -> None:
    async with session_factory() as session:
        await session.execute(
            message_classification_attempts.insert().values(
                telegram_chat_id=chat_pk,
                telegram_message_id=message_id,
                path="live",
                outcome=outcome,
                reason=reason,
                model_profile_id=model_profile_id,
            )
        )
        await session.commit()


async def test_probe_10_scenario_matches_every_hand_computed_figure(
    classification_session_factory: async_sessionmaker[AsyncSession],
    classification_chat_id: int,
    insert_chat: Any,
    insert_message: Any,
    insert_prediction: Any,
    insert_incident: Any,
    insert_action: Any,
    insert_attention_item: Any,
) -> None:
    chat_pk = await insert_chat(chat_id=classification_chat_id)
    model_a = await _insert_model_profile(
        classification_session_factory, name=f"model-a-{_rand_id()}"
    )
    model_b = await _insert_model_profile(
        classification_session_factory, name=f"model-b-{_rand_id()}"
    )

    period_from = _BASE - timedelta(hours=1)
    period_to = _BASE + timedelta(hours=6)

    def sent_at(n: int) -> datetime:
        return _BASE + timedelta(minutes=n)

    async def message(n: int, **overrides: Any) -> int:
        return await insert_message(
            telegram_chat_id=chat_pk, message_id=n, sent_at=sent_at(n), **overrides
        )

    async def prediction(n: int, model_profile_id: int, **overrides: Any) -> int:
        return await insert_prediction(
            telegram_chat_id=chat_pk,
            telegram_message_id=n,
            model_profile_id=model_profile_id,
            created_at=sent_at(n),
            **overrides,
        )

    # --- C1: three question items -------------------------------------------------------------

    await message(1, original_text="السلام عليكم")
    await prediction(
        1, model_a, category="CHITCHAT", severity="none", needs_response=False, route="none",
        confidence="0.910",
    )
    item1 = await insert_attention_item(
        telegram_chat_id=chat_pk, telegram_message_id=1, opened_at=sent_at(1),
        source="rule", rule_version=1, status="open",
    )
    m2_pk = await message(2, original_text="هل الاختبار الاسبوع القادم؟")
    await _link_to_item(classification_session_factory, message_pk=m2_pk, item_id=item1)
    await prediction(
        2, model_a, category="QUESTION_COURSE", severity="none", needs_response=True,
        route="none", confidence="0.930",
    )

    await message(3, original_text="مبروك عليكم")
    await prediction(
        3, model_a, category="CHITCHAT", severity="none", needs_response=False, route="none",
        confidence="0.900",
    )
    await insert_attention_item(
        telegram_chat_id=chat_pk, telegram_message_id=3, opened_at=sent_at(3),
        source="rule", rule_version=1, status="dismissed",
    )

    await message(4, original_text="ما هي خطوات التسجيل في المقرر؟")
    await prediction(
        4, model_a, category="QUESTION_ACCESS", severity="none", needs_response=True,
        route="none", confidence="0.940",
    )
    await insert_attention_item(
        telegram_chat_id=chat_pk, telegram_message_id=4, opened_at=sent_at(4),
        source="operator", rule_version=None, status="open",
    )

    # --- C2: one unverified message per model, never pooled ------------------------------------

    await message(5, original_text="هل يوجد تمديد لموعد التسليم؟")
    await prediction(
        5, model_a, category="QUESTION_COURSE", severity="none", needs_response=True,
        route="none", confidence="0.920",
    )
    await message(6, original_text="متى ينزل الجدول الجديد؟")
    await prediction(
        6, model_b, category="QUESTION_COURSE", severity="none", needs_response=True,
        route="none", confidence="0.900",
    )

    # --- C3/C8: four incidents -------------------------------------------------------------

    await message(7, original_text="اعلان اول عن كورس خارجي")
    await prediction(
        7, model_a, category="SPAM_OR_AD", needs_moderation=True, severity="medium",
        route="possible_violation", route_reason="uncertain", confidence="0.700",
    )
    await insert_incident(
        telegram_chat_id=chat_pk, telegram_message_id=7,
        opened_at=sent_at(7), detected_at=sent_at(7) + timedelta(seconds=30),
        category="SPAM_OR_AD", severity="medium", source="operator", opened_by_user_id=1,
    )

    await message(8, original_text="رسالة عادية اساء الفهم من احد المشرفين")
    await prediction(
        8, model_a, category="CHITCHAT", severity="none", needs_moderation=False, route="none",
        confidence="0.850",
    )
    i2 = await insert_incident(
        telegram_chat_id=chat_pk, telegram_message_id=8,
        opened_at=sent_at(8), detected_at=sent_at(8) + timedelta(seconds=120),
        category="SPAM_OR_AD", severity="low", source="operator", opened_by_user_id=1,
    )
    await insert_action(
        telegram_chat_id=chat_pk, action_type="panel_false_positive",
        occurred_at=sent_at(8) + timedelta(minutes=30), panel_user_id=1,
        moderation_incident_id=i2, note="model disagreed too — false alarm",
    )

    await message(9, original_text="اعلان ثاني بصيغة مسيئة")
    m9_pred = await prediction(
        9, model_a, category="ABUSE", needs_moderation=True, severity="medium",
        route="possible_violation", route_reason="uncertain", confidence="0.750",
    )
    await insert_incident(
        telegram_chat_id=chat_pk, telegram_message_id=9,
        opened_at=sent_at(9), detected_at=sent_at(9) + timedelta(seconds=180),
        category="ABUSE", severity="medium", source="operator", opened_by_user_id=1,
        prompted_by_classification_id=m9_pred,
    )

    await message(10, original_text="اعلان عن كورس بسعر مخفض جدا انضموا الان")
    m10_pred = await prediction(
        10, model_a, category="SPAM_OR_AD", needs_moderation=True, severity="high",
        route="incident", confidence="0.930",
    )
    i4 = await insert_incident(
        telegram_chat_id=chat_pk, telegram_message_id=10,
        opened_at=sent_at(10), detected_at=sent_at(10) + timedelta(seconds=4),
        category="SPAM_OR_AD", severity="high", source="ai", opened_by_user_id=None,
        message_classification_id=m10_pred,
    )
    await insert_action(
        telegram_chat_id=chat_pk, action_type="panel_false_positive",
        occurred_at=sent_at(10) + timedelta(minutes=30), panel_user_id=1,
        moderation_incident_id=i4, note="model misread an announcement as an advert",
    )

    # --- C4: exactly one listed, unanchored possible violation ----------------------------------

    await message(11, original_text="اعلان ثالث مشكوك فيه")
    m11_pred = await prediction(
        11, model_a, category="SPAM_OR_AD", needs_moderation=True, severity="low",
        route="possible_violation", route_reason="uncertain", confidence="0.650",
    )

    # --- C5: excluded / failed / not-yet-classified ---------------------------------------------

    await message(12, original_text=None, media_kind="photo")
    await _insert_attempt(
        classification_session_factory, chat_pk=chat_pk, message_id=12,
        outcome="excluded", reason="media",
    )

    await message(13, original_text="نص عادي فشل تصنيفه")
    await _insert_attempt(
        classification_session_factory, chat_pk=chat_pk, message_id=13,
        outcome="failed", reason="model_timeout", model_profile_id=model_a,
    )

    await message(14, original_text="رسالة لم تصنف بعد")

    # --- C1 -------------------------------------------------------------------------------------

    async with classification_session_factory() as session:
        c1 = await classification_question_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    by_label = {row["label"]: row for row in c1 if row["model_profile_id"] == model_a}
    assert by_label["rule_kept"]["classified"] == 1
    assert by_label["rule_kept"]["judged_needs_response"] == 1
    assert by_label["rule_dismissed"]["classified"] == 1
    assert by_label["rule_dismissed"]["judged_needs_response"] == 0
    assert by_label["operator_added"]["classified"] == 1
    assert by_label["operator_added"]["judged_needs_response"] == 1
    assert not any(row["model_profile_id"] == model_b for row in c1)

    # --- C2: never pooled, one row per model -----------------------------------------------------

    async with classification_session_factory() as session:
        c2 = await classification_unverified_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    c2_by_model = {row["model_profile_id"]: row["unverified_needs_response"] for row in c2}
    assert c2_by_model == {model_a: 1, model_b: 1}

    # --- C3 -------------------------------------------------------------------------------------

    async with classification_session_factory() as session:
        c3 = await classification_violation_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    [row] = [r for r in c3 if r["model_profile_id"] == model_a]
    assert row["indep_flags"] == 2
    assert row["indep_agreed"] == 1
    assert row["indep_same_cat"] == 1
    assert row["prompted_flags"] == 1
    assert row["prompted_agreed"] == 1
    assert row["prompted_same_cat"] == 1
    assert row["fp_closures"] == 2
    assert row["fp_model_raised"] == 1
    assert row["model_opened"] == 1
    assert row["model_opened_fp"] == 1

    # --- C4 -------------------------------------------------------------------------------------

    async with classification_session_factory() as session:
        c4 = await possible_violations(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    assert [row["id"] for row in c4] == [m11_pred]

    # --- C5: 14 = 11 + 1 + 1 + 1 -----------------------------------------------------------------

    async with classification_session_factory() as session:
        c5 = await classification_volume_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    assert c5["messages"] == 14
    assert c5["classified"] == 11
    assert c5["excluded"] == 1
    assert c5["failed"] == 1
    assert c5["not_classified_yet"] == 1
    assert c5["excluded_by_reason"] == {"media": 1}
    assert c5["failed_by_reason"] == {"model_timeout": 1}

    # --- C6: the burst's needs-response message wins over its greeting anchor -------------------

    async with classification_session_factory() as session:
        c6 = await classification_labels_for_items(session, item_ids=[item1])
    assert c6[item1]["labelled_message"] == 2
    assert c6[item1]["category"] == "QUESTION_COURSE"

    # --- C7: TG-M3's own baseline, unchanged, operator additions in the NULL-version row --------

    async with classification_session_factory() as session:
        c7 = await accuracy_by_rule_version(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    c7_by_version = {
        row["rule_version"]: row for row in c7 if row["rule_opened"] or row["operator_added"]
    }
    assert len(c7_by_version) == 2
    assert c7_by_version[1]["rule_opened"] == 2
    assert c7_by_version[1]["rule_dismissed"] == 1
    assert c7_by_version[None]["operator_added"] == 1

    # --- C8: detection latency by opener ----------------------------------------------------------

    async with classification_session_factory() as session:
        c8 = await detection_latency_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
    assert c8["ai"]["flagged"] == 1
    assert c8["ai"]["median"] == 4
    assert c8["operator"]["flagged"] == 3
    assert c8["operator"]["median"] == 120
    assert c8["operator"]["p90"] == 168

    # --- SC-009: recomputing after changing both thresholds gives identical figures -------------
    # No C1-C8 statement reads `Settings` at all — every routing decision was already stored on
    # the prediction row at insert time (D-TG-142) — so mutating the live thresholds after the
    # fact changes nothing any of these functions return.
    Settings(
        DATABASE_URL="postgresql://unused/unused",
        REDIS_URL="redis://unused/0",
        MODERATION_CONFIDENCE_FLOOR=0.10,
        MODERATION_INCIDENT_CONFIDENCE=0.99,
    )
    async with classification_session_factory() as session:
        c3_again = await classification_violation_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
        c5_again = await classification_volume_stats(
            session, period_from=period_from, period_to=period_to, chat_id=chat_pk
        )
    assert c3_again == c3
    assert c5_again == c5
