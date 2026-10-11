"""T058 — the exact arithmetic of `contracts/incident-metrics.md` §2-§4, asserted against
hand-computed values (`app/application/moderation/metrics.py`'s `incident_outcome_stats`,
`incident_timing_stats`, `detection_latency_stats`). Incidents are built directly through
`conftest.py`'s `insert_incident`/`insert_action`, `detected_at` placed as an offset from the
database's own `now()` (`db_now`) — the outcome SQL reads `now()` for "missed" and "within
window", so a "settled" incident is dated days in the past and one "within window" minutes ago,
rather than faking the clock (SC-024).

`conftest.py`'s fixtures commit real rows rather than rolling back a transaction, so every test
here scopes its own assertions to a `chat_id` (or a freshly-created moderator id) it alone
created — never a bare period count over the whole table — so a run of the full suite, or a
second run against the same database, cannot contaminate another test's figures.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from app.application.moderation.metrics import (
    detection_latency_stats,
    incident_outcome_stats,
    incident_timing_stats,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MAX_AGE_S = 86400  # 24h, MODERATION_INCIDENT_MAX_AGE_S's default
_FAR_PAST = timedelta(days=10)
_PANEL_USER_ID = 1


def _rand_id() -> int:
    return random.randint(10_000_000, 2_000_000_000)


async def _new_incident(
    insert_message: Any,
    insert_incident: Any,
    *,
    chat_pk: int,
    opened_at: Any,
    detected_at: Any,
    sender_telegram_user_id: int | None = None,
    responsible_moderator_id: int | None = None,
) -> tuple[int, int]:
    """Returns `(incident_id, message_id)` — evidence branch (a) (reaction) needs the anchor's own
    `message_id` as `target_message_id`, and branch (c) (membership) needs a ban's
    `subject_telegram_user_id` to equal the anchor's own sender, so both are handed back rather
    than only the incident id."""
    message_id = random.randint(1, 1_000_000_000)
    await insert_message(
        telegram_chat_id=chat_pk,
        message_id=message_id,
        sent_at=opened_at,
        telegram_user_id=sender_telegram_user_id,
    )
    incident_id = await insert_incident(
        telegram_chat_id=chat_pk,
        telegram_message_id=message_id,
        opened_at=opened_at,
        detected_at=detected_at,
        category="SPAM_OR_AD",
        severity="low",
        responsible_moderator_id=responsible_moderator_id,
    )
    return incident_id, message_id


async def test_outcomes_partition_flagged_and_handled_share(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """M7, M9: `handled + missed + within_window + false_positive == flagged`, always; the
    handled share excludes within-window incidents from its denominator entirely."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    # handled: resolved well within the ceiling.
    subject_id = await insert_user(tg_user_id=_rand_id())
    handled_id, _ = await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=now - _FAR_PAST,
        detected_at=now - _FAR_PAST,
        sender_telegram_user_id=subject_id,
    )
    update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=now - _FAR_PAST + timedelta(hours=1),
        subject_telegram_user_id=subject_id,
        source_update_id=update_id,
    )

    # missed: the ceiling has passed with no resolution.
    await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=now - _FAR_PAST,
        detected_at=now - _FAR_PAST,
    )

    # within window: detected minutes ago, ceiling far off, unresolved.
    await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=now - timedelta(minutes=10),
        detected_at=now - timedelta(minutes=5),
    )

    # false positive: closed, must be excluded from handled/missed/within_window.
    fp_id, _ = await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=now - _FAR_PAST,
        detected_at=now - _FAR_PAST,
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        action_strength=None,
        occurred_at=now - _FAR_PAST + timedelta(hours=1),
        panel_user_id=_PANEL_USER_ID,
        moderation_incident_id=fp_id,
        note="not actually spam",
    )

    async with incident_session_factory() as session:
        stats = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )

    assert stats["flagged"] == 4
    assert stats["handled"] == 1
    assert stats["missed"] == 1
    assert stats["within_window"] == 1
    assert stats["false_positive"] == 1
    assert (
        stats["handled"] + stats["missed"] + stats["within_window"] + stats["false_positive"]
        == stats["flagged"]
    )
    assert stats["handled_share"] == 1 / (1 + 1)


async def test_missed_late_resolution_stays_missed_after_settling(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """SC-024: a resolution thirty hours after flagging under a 24h ceiling is **missed**, even
    though the incident's own status reads `resolved`; recomputing yields the same count."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    detected_at = now - timedelta(hours=40)
    subject_id = await insert_user(tg_user_id=_rand_id())
    await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=detected_at,
        detected_at=detected_at,
        sender_telegram_user_id=subject_id,
    )
    update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=detected_at + timedelta(hours=30),
        subject_telegram_user_id=subject_id,
        source_update_id=update_id,
    )

    period_from = now - timedelta(days=5)
    period_to = now + timedelta(days=1)

    async with incident_session_factory() as session:
        first = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
        second = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )

    assert first["missed"] == 1
    assert first["handled"] == 0
    assert first == second


async def test_late_arriving_evidence_dated_inside_the_window_is_handled(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """M10: resolution evidence *dated* inside the ceiling counts as handled however late it was
    *inserted* — the arithmetic reads the evidence's own moment, never the insertion time."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    detected_at = now - _FAR_PAST
    subject_id = await insert_user(tg_user_id=_rand_id())
    await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=detected_at,
        detected_at=detected_at,
        sender_telegram_user_id=subject_id,
    )
    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    async with incident_session_factory() as session:
        before = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
    assert before["missed"] == 1

    # The resolution is dated one hour after the flag (well inside the ceiling), inserted now.
    update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=detected_at + timedelta(hours=1),
        subject_telegram_user_id=subject_id,
        source_update_id=update_id,
    )

    async with incident_session_factory() as session:
        after = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
    assert after["missed"] == 0
    assert after["handled"] == 1


async def test_acknowledged_not_handled_excludes_handled_and_false_positive(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """M8: acknowledged but never resolved, past the ceiling — counted beside missed/within-window,
    never inside handled."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    detected_at = now - _FAR_PAST
    _, message_id = await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=detected_at,
        detected_at=detected_at,
    )
    mod = await insert_moderator()
    ack_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=detected_at + timedelta(minutes=5),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=message_id,
        source_update_id=ack_update_id,
    )

    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    async with incident_session_factory() as session:
        stats = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )

    assert stats["missed"] == 1
    assert stats["handled"] == 0
    assert stats["acknowledged_not_handled"] == 1


async def test_timings_samples_median_p90_max_and_pre_flag_evidence(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """M11-M13: each timing is its own earliest evidence minus `detected_at`; pre-flag evidence
    lands in `before_flagging` and in no percentile or maximum (no negative sample ever appears);
    p90 is withheld below `min_samples`, judged on each timing's own count."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    ack_offsets_s = [60, 120, 180]  # three acknowledgement samples
    for offset in ack_offsets_s:
        detected_at = now - _FAR_PAST
        _, message_id = await _new_incident(
            insert_message,
            insert_incident,
            chat_pk=chat_pk,
            opened_at=detected_at,
            detected_at=detected_at,
        )
        mod = await insert_moderator()
        ack_update_id = await captured_update("message_reaction", {}, chat_id=None)
        await insert_action(
            telegram_chat_id=chat_pk,
            action_type="reaction",
            action_strength="acknowledgement",
            occurred_at=detected_at + timedelta(seconds=offset),
            actor_telegram_user_id=mod["telegram_user_id"],
            actor_moderator_id=mod["moderator_id"],
            target_message_id=message_id,
            source_update_id=ack_update_id,
        )

    # One incident acknowledged *before* it was flagged.
    detected_at = now - _FAR_PAST
    _, pre_flag_message_id = await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=detected_at - timedelta(hours=1),
        detected_at=detected_at,
    )
    mod = await insert_moderator()
    pre_flag_update_id = await captured_update("message_reaction", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="reaction",
        action_strength="acknowledgement",
        occurred_at=detected_at - timedelta(minutes=10),
        actor_telegram_user_id=mod["telegram_user_id"],
        actor_moderator_id=mod["moderator_id"],
        target_message_id=pre_flag_message_id,
        source_update_id=pre_flag_update_id,
    )

    async with incident_session_factory() as session:
        suppressed = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=10, chat_id=chat_pk
        )
        not_suppressed = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=2, chat_id=chat_pk
        )

    ack = suppressed["acknowledgement"]
    assert ack["samples"] == 3
    assert ack["before_flagging"] == 1
    assert ack["median"] == 120.0
    assert ack["max"] == 180.0
    assert ack["p90"] is None
    assert ack["p90_suppressed"] is True

    ack_ns = not_suppressed["acknowledgement"]
    assert ack_ns["p90"] is not None
    assert ack_ns["p90_suppressed"] is False

    # No confirmation or enforcement evidence exists anywhere in this fixture.
    assert suppressed["confirmation"]["samples"] == 0
    assert suppressed["confirmation"]["median"] is None
    assert suppressed["confirmation"]["max"] is None
    assert suppressed["enforcement"]["samples"] == 0


async def test_false_positives_excluded_from_timings_but_present_in_latency(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_action: Any,
    db_now: Any,
) -> None:
    """M15 (§4 note), M17: a closed incident contributes no timing sample, but its detection
    latency — how long it took to raise the flag — is included, a wrong flag having taken exactly
    as long to raise as a right one."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    opened_at = now - _FAR_PAST - timedelta(minutes=42)
    detected_at = now - _FAR_PAST
    fp_id, _ = await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=opened_at,
        detected_at=detected_at,
    )
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="panel_false_positive",
        action_strength=None,
        occurred_at=detected_at + timedelta(minutes=5),
        panel_user_id=_PANEL_USER_ID,
        moderation_incident_id=fp_id,
        note="false alarm",
    )

    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    async with incident_session_factory() as session:
        timings = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
        latency = await detection_latency_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )

    assert timings["acknowledgement"]["samples"] == 0
    assert timings["confirmation"]["samples"] == 0
    assert timings["enforcement"]["samples"] == 0
    # TG-M5, D-TG-159: grouped by opener — this incident is `source='operator'` (the fixture's
    # default), so it is the `'operator'` block, not a bare figure.
    assert latency["operator"]["flagged"] == 1
    assert latency["operator"]["median"] == 42 * 60


async def test_detection_latency_takes_no_moderator_parameter() -> None:
    """M16: the function's own signature is the guarantee — a latency figure cannot be attributed
    to a moderator by construction."""
    import inspect

    signature = inspect.signature(detection_latency_stats)
    assert "moderator_id" not in signature.parameters


async def test_zero_rows_return_none_never_zero(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    db_now: Any,
) -> None:
    """M18: `percentile_cont` and `max` over zero qualifying rows return `NULL`, rendered here as
    `None` — never a `0`."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    period_from = now + timedelta(days=100)
    period_to = now + timedelta(days=101)

    async with incident_session_factory() as session:
        outcome = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
        timings = await incident_timing_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )
        latency = await detection_latency_stats(
            session, period_from=period_from, period_to=period_to, min_samples=1, chat_id=chat_pk
        )

    assert outcome["flagged"] == 0
    assert outcome["handled_share"] is None
    assert timings["acknowledgement"]["median"] is None
    assert timings["acknowledgement"]["max"] is None
    # TG-M5, D-TG-159: `GROUP BY source` over zero rows returns zero rows — no key at all, never
    # a zero-filled block for a source that never flagged anything in the period.
    assert latency == {}


async def test_period_selection_by_detected_at_boundary_inclusive_exclusive(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    db_now: Any,
) -> None:
    """M1: `detected_at >= period_from AND detected_at < period_to` — never `opened_at`, never
    `created_at`. The lower bound is inclusive; the upper bound is exclusive."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    boundary = now - timedelta(days=1)
    await _new_incident(
        insert_message, insert_incident, chat_pk=chat_pk, opened_at=boundary, detected_at=boundary
    )

    async with incident_session_factory() as session:
        inclusive = await incident_outcome_stats(
            session,
            period_from=boundary,
            period_to=boundary + timedelta(days=1),
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
        exclusive = await incident_outcome_stats(
            session,
            period_from=boundary + timedelta(microseconds=1),
            period_to=boundary + timedelta(days=1),
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )
        excluded_by_upper = await incident_outcome_stats(
            session,
            period_from=boundary - timedelta(days=1),
            period_to=boundary,
            max_age_s=_MAX_AGE_S,
            chat_id=chat_pk,
        )

    assert inclusive["flagged"] == 1
    assert exclusive["flagged"] == 0
    assert excluded_by_upper["flagged"] == 0


async def test_per_moderator_figures_follow_responsible_moderator_never_the_actor(
    incident_session_factory: async_sessionmaker[AsyncSession],
    insert_chat: Any,
    insert_message: Any,
    insert_incident: Any,
    insert_user: Any,
    insert_moderator: Any,
    insert_action: Any,
    captured_update: Any,
    db_now: Any,
) -> None:
    """M2: per-moderator figures filter on `responsible_moderator_id` — the owner snapshotted at
    detection — never on the actor who happened to perform the resolving evidence."""
    now = await db_now()
    chat_pk = await insert_chat(chat_id=-_rand_id())
    detected_at = now - _FAR_PAST
    responsible = await insert_moderator(display_name="Responsible")
    actor = await insert_moderator(display_name="Actor")

    await _new_incident(
        insert_message,
        insert_incident,
        chat_pk=chat_pk,
        opened_at=detected_at,
        detected_at=detected_at,
        responsible_moderator_id=responsible["moderator_id"],
    )
    subject_id = await insert_user(tg_user_id=_rand_id())
    update_id = await captured_update("chat_member", {}, chat_id=None)
    await insert_action(
        telegram_chat_id=chat_pk,
        action_type="ban",
        action_strength="enforcement",
        occurred_at=detected_at + timedelta(hours=1),
        actor_telegram_user_id=actor["telegram_user_id"],
        actor_moderator_id=actor["moderator_id"],
        subject_telegram_user_id=subject_id,
        source_update_id=update_id,
    )

    period_from = now - timedelta(days=30)
    period_to = now + timedelta(days=1)

    async with incident_session_factory() as session:
        by_responsible = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            moderator_id=responsible["moderator_id"],
        )
        by_actor = await incident_outcome_stats(
            session,
            period_from=period_from,
            period_to=period_to,
            max_age_s=_MAX_AGE_S,
            moderator_id=actor["moderator_id"],
        )

    assert by_responsible["flagged"] == 1
    assert by_actor["flagged"] == 0
