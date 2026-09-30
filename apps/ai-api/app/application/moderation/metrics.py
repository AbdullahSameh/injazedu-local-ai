"""The exact arithmetic behind every figure the Live Attention Queue's figures table displays
(`contracts/attention-metrics.md` §2-§5, T072), every incident figure the Incidents list's
figures table displays (`contracts/incident-metrics.md` §2-§4, T060) — and, appended by TG-M5
(T067), every classification figure C1-C8 of
`specs/008-tg-m5-ai-classification/contracts/classification-metrics.md` behind the Classification
Accuracy page, the Possible Violations list and the queue's "Model's view" column. Quoted from the
contracts, once, in Python — the panel's `apps/ai-control/app/Filament/Pages/Concerns/
AttentionMetrics.php`, `.../Concerns/ClassificationMetrics.php` and
`apps/ai-control/app/Filament/Resources/Incidents/Concerns/IncidentMetrics.php` read the same SQL
(P9, D-TG-91, D-TG-118, D-TG-156). Neither side re-expresses the other's definition; a changed
figure changes this file and that one, never a third.

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
from sqlalchemy.dialects.postgresql import ARRAY
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
# describe no rule set that ever ran. `chat_id` is optional (default unscoped, TG-M3's own
# behaviour); TG-M5's C7 (`classification-metrics.md` §8) is this same statement with
# `AND (:chat_id IS NULL OR telegram_chat_id = :chat_id)` added, verbatim, never a second query.
_ACCURACY_SQL = sa.text(
    """
    SELECT
      count(*) FILTER (WHERE source = 'rule')                                 AS rule_opened,
      count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed')        AS rule_dismissed,
      count(*) FILTER (WHERE source = 'operator')                             AS operator_added,
      rule_version
    FROM attention_items
    WHERE opened_at >= :period_from AND opened_at < :period_to
      AND (:chat_id IS NULL OR telegram_chat_id = :chat_id)
    GROUP BY rule_version
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))


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

# §4 — Detection latency, amended for TG-M5 (`classification-metrics.md` C8, D-TG-159): grouped
# by `i.source` — one row per opener. Still a figure about the system, never about a moderator
# (M16) — it takes no `moderator_id` parameter by construction. Includes false positives (M17): a
# wrong flag took exactly as long to raise as a right one.
_DETECTION_LATENCY_SQL = sa.text(
    """
    SELECT i.source,
           count(*)                                                         AS flagged,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY lat)                 AS latency_median,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY lat)                 AS latency_p90,
           max(lat)                                                         AS latency_max
    FROM (
      SELECT i.source, extract(epoch FROM i.detected_at - i.opened_at) AS lat
      FROM moderation_incidents i
      WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
        AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
    ) i
    GROUP BY i.source
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
) -> dict[str, dict[str, Any]]:
    """§4, amended for TG-M5 (`classification-metrics.md` C8, D-TG-159): one block per opener,
    keyed `'operator'` / `'ai'`. Still a figure about the system, never about a moderator — this
    function takes no `moderator_id` parameter by construction (M16). Includes false positives
    (M17). p90 suppression judged on each row's **own** `flagged` count (M13, M20). A source with
    no incidents in the period has no key at all — never a zero-filled block."""
    rows = (
        await session.execute(
            _DETECTION_LATENCY_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        flagged = row["flagged"]
        suppressed = flagged < min_samples
        result[row["source"]] = {
            "flagged": flagged,
            "median": row["latency_median"],
            "p90": None if suppressed else row["latency_p90"],
            "p90_suppressed": suppressed,
            "max": row["latency_max"],
        }
    return result


async def accuracy_by_rule_version(
    session: AsyncSession,
    *,
    period_from: datetime,
    period_to: datetime,
    chat_id: int | None = None,
) -> list[dict[str, Any]]:
    """§5: precision and recall per `rule_version` (M15) — TG-M5's baseline for whether a model
    is actually better than the rules rather than merely newer (`classification-metrics.md` C7,
    D-TG-156). `precision` is `None` when `rule_opened` is zero (nothing to measure); `recall` is
    always labelled an approximation (M16), since it can only see the misses an operator happened
    to notice and add. `chat_id` defaults unscoped, matching every existing caller.
    """
    rows = (
        await session.execute(
            _ACCURACY_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
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


# --- TG-M5: AI Classification (contracts/classification-metrics.md C1-C6) ---
#
# Every statement below is quoted verbatim from the contract; `ClassificationMetrics.php` quotes
# the identical SQL on the panel side (D-TG-156). K1: a period selects by the message's own
# **platform send time**, never `created_at` and never `detected_at`. K3: every figure is grouped
# by `(model_profile_id, prompt_version, taxonomy_version)` and never pooled across them — a
# number that mixes two models describes no model that ever ran. K4: only current predictions
# count. No `avg(` appears anywhere in this section (FR-049).

# §2 — C1: questions the humans labelled. M1: an item's messages are its anchor plus every
# message its burst linked to it. M2-M4: the three human labels TG-M3 recorded, read as "of
# rule-kept/rule-dismissed/operator-added, how many the model agrees need an answer" — `classified`
# is always the denominator.
_CLASSIFICATION_QUESTION_SQL = sa.text(
    """
    WITH items AS (
      SELECT ai.id, ai.telegram_chat_id, ai.telegram_message_id,
             CASE WHEN ai.source = 'rule' AND ai.status <> 'dismissed' THEN 'rule_kept'
                  WHEN ai.source = 'rule'                             THEN 'rule_dismissed'
                  ELSE 'operator_added' END AS label
      FROM attention_items ai
      WHERE ai.source IN ('rule','operator')
        AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
        AND (:chat_id IS NULL OR ai.telegram_chat_id = :chat_id)
    ), judged AS (
      SELECT i.id, i.label, c.model_profile_id, c.prompt_version, c.taxonomy_version,
             bool_or(c.needs_response) AS any_needs_response
      FROM items i
      JOIN telegram_messages m
        ON m.telegram_chat_id = i.telegram_chat_id
       AND (m.attention_item_id = i.id OR m.message_id = i.telegram_message_id)
      JOIN message_classifications c
        ON c.telegram_chat_id = m.telegram_chat_id
       AND c.telegram_message_id = m.message_id AND c.is_current
      GROUP BY 1, 2, 3, 4, 5
    )
    SELECT model_profile_id, prompt_version, taxonomy_version, label,
           count(*) AS classified,
           count(*) FILTER (WHERE any_needs_response) AS judged_needs_response
    FROM judged GROUP BY 1, 2, 3, 4
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §3 — C2: model-only judgements, unverified. M5: a message the model says needs an answer where
# no question item exists at all — never counted as right and never as wrong.
_CLASSIFICATION_UNVERIFIED_SQL = sa.text(
    """
    SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version,
           count(*) AS unverified_needs_response
    FROM message_classifications c
    JOIN telegram_messages m
      ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
    WHERE c.is_current AND c.needs_response
      AND m.sent_at >= :period_from AND m.sent_at < :period_to
      AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
      AND m.attention_item_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM attention_items a
        WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
      )
    GROUP BY 1, 2, 3
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §4 — C3: violations the humans labelled, and the model's own incidents. M6: independent operator
# flags and list-prompted ones reported apart — only the independent row is evidence of agreement.
# M9: `model_opened_fp` over `model_opened` is the model's incident false-positive count — the
# figure Finding 2 makes the real control on automatic opening.
_CLASSIFICATION_VIOLATION_SQL = sa.text(
    """
    WITH inc AS (
      SELECT i.*, s.status
      FROM moderation_incidents i JOIN moderation_incident_state s ON s.incident_id = i.id
      WHERE i.opened_at >= :period_from AND i.opened_at < :period_to
        AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
    )
    SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
      ) AS indep_flags,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
          AND c.needs_moderation
      ) AS indep_agreed,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
          AND c.needs_moderation AND c.category = inc.category
      ) AS indep_same_cat,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
      ) AS prompted_flags,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
          AND c.needs_moderation
      ) AS prompted_agreed,
      count(*) FILTER (
        WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
          AND c.needs_moderation AND c.category = inc.category
      ) AS prompted_same_cat,
      count(*) FILTER (WHERE inc.status = 'closed_false_positive') AS fp_closures,
      count(*) FILTER (
        WHERE inc.status = 'closed_false_positive' AND c.needs_moderation
      ) AS fp_model_raised,
      count(*) FILTER (WHERE inc.source = 'ai') AS model_opened,
      count(*) FILTER (
        WHERE inc.source = 'ai' AND inc.status = 'closed_false_positive'
      ) AS model_opened_fp
    FROM inc
    JOIN message_classifications c
      ON c.telegram_chat_id = inc.telegram_chat_id
     AND c.telegram_message_id = inc.telegram_message_id AND c.is_current
    GROUP BY 1, 2, 3
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §5 — C4: the possible-violations list. M12: membership is read, never stored — a row leaves the
# list the moment its message anchors an incident, whoever opened it.
_POSSIBLE_VIOLATIONS_SQL = sa.text(
    """
    SELECT c.id, c.telegram_chat_id, c.telegram_message_id, m.sent_at, m.original_text,
           c.category, c.severity, c.confidence, c.route_reason, p.name AS model,
           c.prompt_version, c.created_at
    FROM message_classifications c
    JOIN telegram_messages m
      ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
    JOIN model_profiles p ON p.id = c.model_profile_id
    WHERE c.is_current AND c.route = 'possible_violation'
      AND NOT EXISTS (
        SELECT 1 FROM moderation_incidents i
        WHERE i.telegram_chat_id = c.telegram_chat_id
          AND i.telegram_message_id = c.telegram_message_id
      )
      AND m.sent_at >= :period_from AND m.sent_at < :period_to
      AND (:chat_id IS NULL OR c.telegram_chat_id = :chat_id)
    ORDER BY m.sent_at DESC
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §6 — C5: what happened to every message. M14: the four outcomes partition every message —
# `messages = classified + excluded + failed + not_classified_yet`, always.
_CLASSIFICATION_VOLUME_SQL = sa.text(
    """
    SELECT count(*) AS messages,
           count(*) FILTER (WHERE c.id IS NOT NULL) AS classified,
           count(*) FILTER (WHERE c.id IS NULL AND x.id IS NOT NULL) AS excluded,
           count(*) FILTER (
             WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NOT NULL
           ) AS failed,
           count(*) FILTER (
             WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NULL
           ) AS not_classified_yet
    FROM telegram_messages m
    LEFT JOIN message_classifications c
      ON c.telegram_chat_id = m.telegram_chat_id
     AND c.telegram_message_id = m.message_id AND c.is_current
    LEFT JOIN message_classification_attempts x
      ON x.telegram_chat_id = m.telegram_chat_id
     AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
    LEFT JOIN LATERAL (
      SELECT a.id FROM message_classification_attempts a
      WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
        AND a.outcome = 'failed'
      ORDER BY a.created_at DESC, a.id DESC LIMIT 1
    ) f ON true
    WHERE m.sent_at >= :period_from AND m.sent_at < :period_to
      AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# M15's breakdowns: the same joins as C5, grouped by reason — exclusions by their one reason,
# failures by the **latest** failure's reason (mirrors C5's own `LATERAL` tie-break).
_CLASSIFICATION_EXCLUDED_BY_REASON_SQL = sa.text(
    """
    SELECT x.reason, count(*) AS n
    FROM message_classification_attempts x
    JOIN telegram_messages m
      ON m.telegram_chat_id = x.telegram_chat_id AND m.message_id = x.telegram_message_id
    WHERE x.outcome = 'excluded'
      AND m.sent_at >= :period_from AND m.sent_at < :period_to
      AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
    GROUP BY x.reason
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

_CLASSIFICATION_FAILED_BY_REASON_SQL = sa.text(
    """
    SELECT f.reason, count(*) AS n
    FROM telegram_messages m
    JOIN LATERAL (
      SELECT a.reason FROM message_classification_attempts a
      WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
        AND a.outcome = 'failed'
      ORDER BY a.created_at DESC, a.id DESC LIMIT 1
    ) f ON true
    WHERE NOT EXISTS (
        SELECT 1 FROM message_classifications c
        WHERE c.telegram_chat_id = m.telegram_chat_id
          AND c.telegram_message_id = m.message_id AND c.is_current
      )
      AND NOT EXISTS (
        SELECT 1 FROM message_classification_attempts x
        WHERE x.telegram_chat_id = m.telegram_chat_id
          AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
      )
      AND m.sent_at >= :period_from AND m.sent_at < :period_to
      AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
    GROUP BY f.reason
    """
).bindparams(sa.bindparam("chat_id", type_=sa.BigInteger))

# §7 — C6: the model's label on a waiting question. M17: the label shown is the earliest of the
# item's messages the model judged to need an answer; if none, the earliest classified message —
# a greeting that anchors a burst does not hide the question after it.
_CLASSIFICATION_LABELS_FOR_ITEMS_SQL = sa.text(
    """
    SELECT DISTINCT ON (ai.id)
           ai.id AS item_id, m.message_id AS labelled_message, c.category, c.confidence
    FROM attention_items ai
    JOIN telegram_messages m
      ON m.telegram_chat_id = ai.telegram_chat_id
     AND (m.attention_item_id = ai.id OR m.message_id = ai.telegram_message_id)
    JOIN message_classifications c
      ON c.telegram_chat_id = m.telegram_chat_id
     AND c.telegram_message_id = m.message_id AND c.is_current
    WHERE ai.id = ANY(:item_ids)
    ORDER BY ai.id, c.needs_response DESC, m.sent_at, m.message_id
    """
).bindparams(sa.bindparam("item_ids", type_=ARRAY(sa.BigInteger)))


async def classification_question_stats(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None = None
) -> list[dict[str, Any]]:
    """C1: one row per `(model, prompt_version, taxonomy_version, label)` — `classified` is
    always the denominator (M4); a model that never classified any of an item's messages has no
    row for that item at all."""
    rows = (
        await session.execute(
            _CLASSIFICATION_QUESTION_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def classification_unverified_stats(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None = None
) -> list[dict[str, Any]]:
    """C2: one row per model — never pooled (K3), so two models each with an unverified message
    of their own are reported as two separate rows, never summed into one."""
    rows = (
        await session.execute(
            _CLASSIFICATION_UNVERIFIED_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def classification_violation_stats(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None = None
) -> list[dict[str, Any]]:
    """C3: one row per model — independent and list-prompted flags reported apart (M6), category
    agreement counted only among the flags the model agreed need moderation (M7)."""
    rows = (
        await session.execute(
            _CLASSIFICATION_VIOLATION_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def possible_violations(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None = None
) -> list[dict[str, Any]]:
    """C4: exactly the Possible Violations page's own rows — read here identically to
    `App\\Filament\\Pages\\Concerns\\ClassificationMetrics::possibleViolations` (D-TG-156), so a
    test can assert the two sides agree without duplicating either query's own logic."""
    rows = (
        await session.execute(
            _POSSIBLE_VIOLATIONS_SQL,
            {"period_from": period_from, "period_to": period_to, "chat_id": chat_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def classification_volume_stats(
    session: AsyncSession, *, period_from: datetime, period_to: datetime, chat_id: int | None = None
) -> dict[str, Any]:
    """C5 plus M15's by-reason breakdowns: `messages == classified + excluded + failed +
    not_classified_yet`, always (M14, probe 10: 14 = 11 + 1 + 1 + 1). `excluded_by_reason` and
    `failed_by_reason` are the same joins C5 makes, grouped by reason — a message counts in at
    most one of the two, mirroring C5's own precedence."""
    params = {"period_from": period_from, "period_to": period_to, "chat_id": chat_id}
    row = (await session.execute(_CLASSIFICATION_VOLUME_SQL, params)).mappings().one()
    excluded_rows = (
        (await session.execute(_CLASSIFICATION_EXCLUDED_BY_REASON_SQL, params)).mappings().all()
    )
    failed_rows = (
        (await session.execute(_CLASSIFICATION_FAILED_BY_REASON_SQL, params)).mappings().all()
    )
    return {
        "messages": row["messages"],
        "classified": row["classified"],
        "excluded": row["excluded"],
        "failed": row["failed"],
        "not_classified_yet": row["not_classified_yet"],
        "excluded_by_reason": {r["reason"]: r["n"] for r in excluded_rows},
        "failed_by_reason": {r["reason"]: r["n"] for r in failed_rows},
    }


async def classification_labels_for_items(
    session: AsyncSession, *, item_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """C6: the label shown for each of `item_ids`, keyed by item id — an item with no classified
    message is simply absent (M18: the caller falls back to C5's status of its anchor)."""
    rows = (
        await session.execute(_CLASSIFICATION_LABELS_FOR_ITEMS_SQL, {"item_ids": item_ids})
    ).mappings().all()
    return {row["item_id"]: dict(row) for row in rows}
