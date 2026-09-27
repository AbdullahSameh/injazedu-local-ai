"""The exact arithmetic behind every figure the Live Attention Queue's figures table displays
(`contracts/attention-metrics.md` §2-§5, T072), and — appended by TG-M4 (T060) — every incident
figure the Incidents list's figures table displays (`contracts/incident-metrics.md` §2-§4).
Quoted from the contracts, once, in Python — the panel's `apps/ai-control/app/Filament/Pages/
Concerns/AttentionMetrics.php` and `apps/ai-control/app/Filament/Resources/Incidents/Concerns/
IncidentMetrics.php` read the same SQL (P9, D-TG-91, D-TG-118). Neither side re-expresses the
other's definition; a changed figure changes this file and that one, never a third.

Every function takes its scoping and thresholds as explicit keyword arguments rather than
reading `Settings` itself, mirroring this package's existing explicit-parameter style (e.g.
`record_downtime_if_any`) — a metrics query has no business owning a settings import. Every
incident statement here reads `moderation_incident_state` (`data-model.md` §3.2) and never
recomputes a status (lifecycle contract N6); no `avg(` appears anywhere in this file (M14).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# §2 — First Response Time. Only `status = 'answered'` contributes (M3): `open`, `expired` and
# `dismissed` items contribute no value, not zero. `percentile_cont` returns NULL over zero rows
# (M8), which this query lets through unchanged — the caller never turns that NULL into a 0.
_FIRST_RESPONSE_TIME_SQL = sa.text(
    """
    SELECT
      count(*)                                          AS answered,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY frt)  AS median_frt,
      percentile_cont(0.9) WITHIN GROUP (ORDER BY frt)  AS p90_frt,
      max(frt)                                          AS max_frt
    FROM (
      SELECT extract(epoch FROM (first_response_at - opened_at)) AS frt
      FROM attention_items
      WHERE status = 'answered'
        AND opened_at >= :period_from AND opened_at < :period_to
        AND (:moderator_id IS NULL OR responsible_moderator_id = :moderator_id)
        AND (:chat_id      IS NULL OR telegram_chat_id        = :chat_id)
    ) s
    """
).bindparams(
    sa.bindparam("moderator_id", type_=sa.BigInteger),
    sa.bindparam("chat_id", type_=sa.BigInteger),
)

# §3 — Unanswered. `dismissed` items leave the calculation entirely, out of both numerator and
# denominator (M10); `expired` items stay in the unanswered count permanently (M11).
_UNANSWERED_SQL = sa.text(
    """
    SELECT count(*) FILTER (WHERE status IN ('open','expired'))      AS unanswered,
           count(*) FILTER (WHERE status = 'expired')                AS expired,
           count(*) FILTER (WHERE status <> 'dismissed')             AS opened
    FROM attention_items
    WHERE opened_at >= :period_from AND opened_at < :period_to
      AND (:moderator_id IS NULL OR responsible_moderator_id = :moderator_id)
      AND (:chat_id      IS NULL OR telegram_chat_id        = :chat_id)
    """
).bindparams(
    sa.bindparam("moderator_id", type_=sa.BigInteger),
    sa.bindparam("chat_id", type_=sa.BigInteger),
)

# §4 — Oldest still waiting. `status = 'open'` only (M12) — expired items are excluded so one
# abandoned question cannot pin this figure forever. Ignores the period window (M13): a live
# statement about now, not a historical one.
_OLDEST_WAITING_SQL = sa.text(
    """
    SELECT max(now() - opened_at) AS oldest_waiting
    FROM attention_items
    WHERE status = 'open'
      AND (:chat_id IS NULL OR telegram_chat_id = :chat_id)
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §5 — Rule-set accuracy, grouped by `rule_version` always (M15) — pooling versions would
# describe no rule set that ever ran.
_ACCURACY_SQL = sa.text(
    """
    SELECT
      count(*) FILTER (WHERE source = 'rule')                                 AS rule_opened,
      count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed')        AS rule_dismissed,
      count(*) FILTER (WHERE source = 'operator')                             AS operator_added,
      rule_version
    FROM attention_items
    WHERE opened_at >= :period_from AND opened_at < :period_to
    GROUP BY rule_version
    """
)


async def first_response_time_stats(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    min_samples: int,
    moderator_id: int | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """§2: median, p90 and max first-response time over answered items whose `opened_at` falls
    in `[period_from, period_to)` (M1, M2). `answered` is always returned beside the percentiles
    (M5). `p90_frt` is `None` — with `p90_suppressed=True` — below `min_samples` (M6), so a
    figure built from too few points is never rendered as if it were authoritative. No average
    is computed anywhere in this module (M7).
    """
    row = (
        await session.execute(
            _FIRST_RESPONSE_TIME_SQL,
            {
                "period_from": period_from,
                "period_to": period_to,
                "moderator_id": moderator_id,
                "chat_id": chat_id,
            },
        )
    ).mappings().one()
    answered = row["answered"]
    suppressed = answered < min_samples
    return {
        "answered": answered,
        "median_frt": row["median_frt"],
        "p90_frt": None if suppressed else row["p90_frt"],
        "p90_suppressed": suppressed,
        "max_frt": row["max_frt"],
    }


async def unanswered_stats(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    moderator_id: int | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """§3: the unanswered count and its share of `opened` (M9) — never a bare number.
    `dismissed` items are excluded from both `unanswered` and `opened` (M10); `expired` items
    stay counted in `unanswered` permanently, with their own count shown alongside (M11).
    `unanswered_share` is `None`, not `0`, when nothing was asked (`opened == 0`).
    """
    row = (
        await session.execute(
            _UNANSWERED_SQL,
            {
                "period_from": period_from,
                "period_to": period_to,
                "moderator_id": moderator_id,
                "chat_id": chat_id,
            },
        )
    ).mappings().one()
    opened = row["opened"]
    unanswered = row["unanswered"]
    return {
        "unanswered": unanswered,
        "expired": row["expired"],
        "opened": opened,
        "unanswered_share": (unanswered / opened) if opened else None,
    }


async def oldest_waiting(
    session: AsyncSession, *, chat_id: int | None = None
) -> timedelta | None:
    """§4: how long the longest-waiting open item has been waiting, right now (M12-M14).
    Ignores the period window on purpose — this figure is never historical. `None` when nothing
    is open, never a zero duration.
    """
    result: timedelta | None = (
        await session.execute(_OLDEST_WAITING_SQL, {"chat_id": chat_id})
    ).scalar_one()
    return result


# --- TG-M4: Policy Incidents (contracts/incident-metrics.md §2-§4) ---
#
# Every statement below is quoted verbatim from the contract; `IncidentMetrics.php` quotes the
# identical SQL on the panel side (D-TG-118). Selection is always by `detected_at` — the
# **detection** moment, never `opened_at` and never `created_at` (M1).

# §2 — Outcomes. `handled`/`missed`/`within_window` partition every incident that is not a false
# positive (M4-M7): `handled + missed + within_window + false_positive = flagged`, always.
_INCIDENT_OUTCOME_SQL = sa.text(
    """
    SELECT
      count(*)                                                                    AS flagged,
      count(*) FILTER (WHERE s.status = 'closed_false_positive')                  AS false_positive,
      count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                         AND s.resolved_at <= i.detected_at + make_interval(secs => :max_age_s))
                                                                                    AS handled,
      count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                         AND (s.resolved_at IS NULL
                              OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s))
                         AND now() >  i.detected_at + make_interval(secs => :max_age_s))
                                                                                    AS missed,
      count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                         AND s.resolved_at IS NULL
                         AND now() <= i.detected_at + make_interval(secs => :max_age_s))
                                                                          AS within_window,
      count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                         AND (s.resolved_at IS NULL
                              OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s))
                         AND s.first_acknowledgement_at
                             <= i.detected_at + make_interval(secs => :max_age_s))
                                                                        AS acknowledged_not_handled
    FROM moderation_incidents i
    JOIN moderation_incident_state s ON s.incident_id = i.id
    WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
      AND (:moderator_id IS NULL OR i.responsible_moderator_id = :moderator_id)
      AND (:chat_id      IS NULL OR i.telegram_chat_id        = :chat_id)
    """
).bindparams(
    sa.bindparam("max_age_s", type_=sa.Integer),
    sa.bindparam("moderator_id", type_=sa.BigInteger),
    sa.bindparam("chat_id", type_=sa.BigInteger),
)

# §3 — The three timings, each its own earliest evidence minus the detection moment (M11).
# Evidence before the flag is counted in `*_before_flagging` and contributes to no percentile and
# no maximum (M12) — no negative or zero stand-in is ever produced.
_INCIDENT_TIMING_SQL = sa.text(
    """
    SELECT
      count(*) FILTER (WHERE t_ack  >= 0)                                    AS ack_samples,
      count(*) FILTER (WHERE t_ack  <  0)                                    AS ack_before_flagging,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY t_ack) FILTER (WHERE t_ack >= 0) AS ack_median,
      percentile_cont(0.9) WITHIN GROUP (ORDER BY t_ack) FILTER (WHERE t_ack >= 0) AS ack_p90,
      max(t_ack)  FILTER (WHERE t_ack  >= 0)                                 AS ack_max,

      count(*) FILTER (WHERE t_conf >= 0)                                  AS conf_samples,
      count(*) FILTER (WHERE t_conf <  0)                                  AS conf_before_flagging,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_median,
      percentile_cont(0.9) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_p90,
      max(t_conf) FILTER (WHERE t_conf >= 0)                                 AS conf_max,

      count(*) FILTER (WHERE t_enf  >= 0)                                    AS enf_samples,
      count(*) FILTER (WHERE t_enf  <  0)                                    AS enf_before_flagging,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY t_enf) FILTER (WHERE t_enf >= 0) AS enf_median,
      percentile_cont(0.9) WITHIN GROUP (ORDER BY t_enf) FILTER (WHERE t_enf >= 0) AS enf_p90,
      max(t_enf)  FILTER (WHERE t_enf  >= 0)                                 AS enf_max
    FROM (
      SELECT extract(epoch FROM s.first_acknowledgement_at - i.detected_at) AS t_ack,
             extract(epoch FROM s.first_confirmation_at    - i.detected_at) AS t_conf,
             extract(epoch FROM s.first_enforcement_at     - i.detected_at) AS t_enf
      FROM moderation_incidents i
      JOIN moderation_incident_state s ON s.incident_id = i.id
      WHERE s.status <> 'closed_false_positive'
        AND i.detected_at >= :period_from AND i.detected_at < :period_to
        AND (:moderator_id IS NULL OR i.responsible_moderator_id = :moderator_id)
        AND (:chat_id      IS NULL OR i.telegram_chat_id        = :chat_id)
    ) t
    """
).bindparams(
    sa.bindparam("moderator_id", type_=sa.BigInteger),
    sa.bindparam("chat_id", type_=sa.BigInteger),
)

# §4 — Detection latency: a figure about the system, never about a moderator (M16) — it takes no
# `moderator_id` parameter by construction. Includes false positives (M17): a wrong flag took
# exactly as long to raise as a right one.
_DETECTION_LATENCY_SQL = sa.text(
    """
    SELECT count(*)                                                         AS flagged,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY lat)                 AS latency_median,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY lat)                 AS latency_p90,
           max(lat)                                                         AS latency_max
    FROM (
      SELECT extract(epoch FROM i.detected_at - i.opened_at) AS lat
      FROM moderation_incidents i
      WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
        AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
    ) l
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))


async def incident_outcome_stats(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    max_age_s: int,
    moderator_id: int | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """§2: outcome counts over incidents whose `detected_at` falls in `[period_from, period_to)`
    (M1, M2). `handled_share` is computed here from the row, `handled / (handled + missed)`, never
    with within-window incidents in the denominator (M9); `None`, not `0`, when that denominator
    is zero. `acknowledged_not_handled` is the acknowledged share of `missed + within_window`
    (M8), shown beside them and never counted as handled.
    """
    row = (
        await session.execute(
            _INCIDENT_OUTCOME_SQL,
            {
                "period_from": period_from,
                "period_to": period_to,
                "max_age_s": max_age_s,
                "moderator_id": moderator_id,
                "chat_id": chat_id,
            },
        )
    ).mappings().one()
    handled = row["handled"]
    missed = row["missed"]
    denominator = handled + missed
    return {
        "flagged": row["flagged"],
        "false_positive": row["false_positive"],
        "handled": handled,
        "missed": missed,
        "within_window": row["within_window"],
        "acknowledged_not_handled": row["acknowledged_not_handled"],
        "handled_share": (handled / denominator) if denominator else None,
    }


def _timing_block(row: sa.RowMapping, prefix: str, min_samples: int) -> dict[str, Any]:
    samples = row[f"{prefix}_samples"]
    suppressed = samples < min_samples
    return {
        "samples": samples,
        "before_flagging": row[f"{prefix}_before_flagging"],
        "median": row[f"{prefix}_median"],
        "p90": None if suppressed else row[f"{prefix}_p90"],
        "p90_suppressed": suppressed,
        "max": row[f"{prefix}_max"],
    }


async def incident_timing_stats(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    min_samples: int,
    moderator_id: int | None = None,
    chat_id: int | None = None,
) -> dict[str, dict[str, Any]]:
    """§3: median, p90 and max for each of the three timings — acknowledgement, confirmation,
    enforcement — each judged on its **own** sample count against `min_samples` (M13). False
    positives are excluded (they have no timing, M15 §4 note). Pre-flag evidence lands in
    `before_flagging` and in no percentile or maximum (M12). `None` — never `0` — over zero
    qualifying rows (M18). No average anywhere (M14).
    """
    row = (
        await session.execute(
            _INCIDENT_TIMING_SQL,
            {
                "period_from": period_from,
                "period_to": period_to,
                "moderator_id": moderator_id,
                "chat_id": chat_id,
            },
        )
    ).mappings().one()
    return {
        "acknowledgement": _timing_block(row, "ack", min_samples),
        "confirmation": _timing_block(row, "conf", min_samples),
        "enforcement": _timing_block(row, "enf", min_samples),
    }


async def detection_latency_stats(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    min_samples: int,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """§4: a figure about the system, never about a moderator — this function takes no
    `moderator_id` parameter by construction (M16). Includes false positives (M17). p90
    suppression as every other timing, on `flagged`'s own count (M13)."""
    row = (
        await session.execute(
            _DETECTION_LATENCY_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().one()
    flagged = row["flagged"]
    suppressed = flagged < min_samples
    return {
        "flagged": flagged,
        "median": row["latency_median"],
        "p90": None if suppressed else row["latency_p90"],
        "p90_suppressed": suppressed,
        "max": row["latency_max"],
    }


async def accuracy_by_rule_version(
    session: AsyncSession, *, period_from: datetime, period_to: datetime
) -> list[dict[str, Any]]:
    """§5: precision and recall per `rule_version` (M15) — TG-M5's baseline for whether a model
    is actually better than the rules rather than merely newer. `precision` is `None` when
    `rule_opened` is zero (nothing to measure); `recall` is always labelled an approximation
    (M16), since it can only see the misses an operator happened to notice and add.
    """
    rows = (
        await session.execute(
            _ACCURACY_SQL, {"period_from": period_from, "period_to": period_to}
        )
    ).mappings().all()
    results: list[dict[str, Any]] = []
    for row in rows:
        rule_opened = row["rule_opened"]
        rule_dismissed = row["rule_dismissed"]
        operator_added = row["operator_added"]
        precision = 1 - (rule_dismissed / rule_opened) if rule_opened else None
        denominator = rule_opened + operator_added
        recall = (rule_opened / denominator) if denominator else None
        results.append(
            {
                "rule_version": row["rule_version"],
                "rule_opened": rule_opened,
                "rule_dismissed": rule_dismissed,
                "operator_added": operator_added,
                "precision": precision,
                "recall": recall,
            }
        )
    return results
