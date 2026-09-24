"""The exact arithmetic behind every figure the Live Attention Queue's figures table displays
(`contracts/attention-metrics.md` §2-§5, T072). Quoted from the contract, once, in Python — the
panel's `apps/ai-control/app/Filament/Pages/Concerns/AttentionMetrics.php` reads the same SQL
(P9, D-TG-91). Neither side re-expresses the other's definition; a changed figure changes this
file and that one, never a third.

Every function takes its scoping and thresholds as explicit keyword arguments rather than
reading `Settings` itself, mirroring this package's existing explicit-parameter style (e.g.
`record_downtime_if_any`) — a metrics query has no business owning a settings import.
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
