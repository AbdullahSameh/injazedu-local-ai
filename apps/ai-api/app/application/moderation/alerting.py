"""TG-M6 firing and reading (`contracts/alerting.md` §3, §4 V2, §6 U1-U5).

Two halves, both reading only the derived state (FR-521) and writing only `alerts` (F7):

- **The render inputs** (T515): `load_alert`, `subject_live` and `build_render_input` turn one
  `alerts` row and the views into `alert_render.RenderInput`. No state is recomputed here: an item's
  state is `attention_items.status`, an incident's is `moderation_incident_state.status`, and the
  assignee is the assignee view's.
- **The evaluator framework** (T517): the rule in force per (chat, trigger), a registry of one
  set-based statement per trigger, the shared insert (dedupe key, repeat index, quiet hours, one
  insert per subject per run) and the refresh scan.

Nothing here calls Telegram: `alert_delivery.py` is the only provider caller (D-TG-227). No text is
stored or logged; the excerpt exists only inside a `RenderInput` (D-TG-221).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alert_render import (
    Person,
    RenderInput,
    SubjectEnd,
    render_state,
)
from app.application.moderation.assignments import team_at
from app.application.moderation.messages import extract_text
from app.domain.moderation.alerting import (
    MAX_EDIT_ATTEMPTS,
    SUBJECT_OF,
    SubjectType,
    Trigger,
    dedupe_key,
    due_repeat_index,
    in_quiet_hours,
    parse_quiet_hours,
)
from app.infrastructure.models_moderation import (
    alerts,
    moderators,
    telegram_users,
)

logger = logging.getLogger(__name__)

# The subject's own status words for a group alert: a chat has no status column of its own.
CHAT_LIVE = "live"
CHAT_ENDED = "ended"

_LIVE_INCIDENT = ("open", "acknowledged")
_HEALTHY_STANDINGS = ("administrator", "unknown")


@dataclass(frozen=True)
class RenderSettings:
    """What rendering needs from the configuration: the panel's base URL (blank → no panel button)
    and the text retention age (U4)."""

    panel_base_url: str | None
    retention_days: int


@dataclass(frozen=True)
class AlertRef:
    """The `alerts` columns firing, delivery and refresh read."""

    id: int
    alert_rule_id: int
    trigger: Trigger
    telegram_chat_id: int
    subject_type: SubjectType
    subject_id: int
    episode_at: datetime | None
    repeat_index: int
    rule_values: dict[str, Any]
    fired_at: datetime
    delivery_status: str
    sent_chat_id: int | None = None
    sent_message_id: int | None = None
    rendered_state: dict[str, Any] | None = None
    excerpt_shown: bool = False
    final_at: datetime | None = None
    edit_attempts: int = 0

    @classmethod
    def from_row(cls, row: Any) -> AlertRef:
        return cls(
            id=int(row["id"]),
            alert_rule_id=int(row["alert_rule_id"]),
            trigger=Trigger(row["trigger"]),
            telegram_chat_id=int(row["telegram_chat_id"]),
            subject_type=SubjectType(row["subject_type"]),
            subject_id=int(row["subject_id"]),
            episode_at=row["episode_at"],
            repeat_index=int(row["repeat_index"]),
            rule_values=dict(row["rule_values"] or {}),
            fired_at=row["fired_at"],
            delivery_status=row["delivery_status"],
            sent_chat_id=row["sent_chat_id"],
            sent_message_id=row["sent_message_id"],
            rendered_state=row["rendered_state"],
            excerpt_shown=bool(row["excerpt_shown"]),
            final_at=row["final_at"],
            edit_attempts=int(row["edit_attempts"]),
        )


async def load_alert(session: AsyncSession, alert_id: int) -> AlertRef | None:
    row = (
        (await session.execute(sa.select(alerts).where(alerts.c.id == alert_id)))
        .mappings()
        .one_or_none()
    )
    return None if row is None else AlertRef.from_row(row)


async def _now(session: AsyncSession) -> datetime:
    now: datetime = (await session.execute(sa.select(sa.func.now()))).scalar_one()
    return now


# --- does the subject still qualify? (V2, U2, U5) ---


async def subject_live(session: AsyncSession, alert: AlertRef) -> bool:
    """F1's "qualifies while", read from the derived state at this instant. The threshold was
    crossed at firing and only grows, so an item or incident lives while its status does; a group
    alert lives while its episode is the chat's current one and the chat is still monitored."""
    if alert.subject_type is SubjectType.ATTENTION_ITEM:
        status = (
            await session.execute(
                sa.text("SELECT status FROM attention_items WHERE id = :id"),
                {"id": alert.subject_id},
            )
        ).scalar_one_or_none()
        return status == "open"
    if alert.subject_type is SubjectType.INCIDENT:
        status = (
            await session.execute(
                sa.text("SELECT status FROM moderation_incident_state WHERE incident_id = :id"),
                {"id": alert.subject_id},
            )
        ).scalar_one_or_none()
        return status in _LIVE_INCIDENT
    chat = (
        (
            await session.execute(
                sa.text(
                    "SELECT is_monitored, last_event_at, bot_status, bot_status_at "
                    "FROM telegram_chats WHERE id = :id"
                ),
                {"id": alert.subject_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if chat is None or not chat["is_monitored"]:
        return False
    if alert.trigger is Trigger.GROUP_SILENT:
        return bool(chat["last_event_at"] == alert.episode_at)
    return bool(
        chat["bot_status_at"] == alert.episode_at
        and chat["bot_status"] not in _HEALTHY_STANDINGS
    )


# --- the render inputs (T515) ---


async def _people(session: AsyncSession, moderator_ids: list[int]) -> dict[int, Person]:
    """Declared moderators by id, with the platform id their mention links to (D-TG-225)."""
    wanted = sorted({m for m in moderator_ids if m is not None})
    if not wanted:
        return {}
    rows = (
        await session.execute(
            sa.select(moderators.c.id, moderators.c.display_name, telegram_users.c.tg_user_id)
            .join(telegram_users, telegram_users.c.id == moderators.c.telegram_user_id)
            .where(moderators.c.id.in_(wanted))
        )
    ).all()
    return {
        int(row.id): Person(
            moderator_id=int(row.id), name=row.display_name, tg_user_id=row.tg_user_id
        )
        for row in rows
    }


@dataclass(frozen=True)
class _Anchor:
    message_id: int
    sent_at: datetime
    text: str | None
    removed: bool
    aged_out: bool


async def _anchor(
    session: AsyncSession, chat_pk: int, message_id: int, *, now: datetime, retention_days: int
) -> _Anchor:
    """The anchor's first-posted words, re-extracted from its own captured event (never the
    possibly edited row), its purge markers and its age against the retention window (U4)."""
    row = (
        (
            await session.execute(
                sa.text(
                    "SELECT m.sent_at, m.text_purged_at, u.payload, u.update_type, "
                    "       u.payload_purged_at "
                    "FROM telegram_messages m "
                    "LEFT JOIN telegram_updates u ON u.id = m.source_update_id "
                    "WHERE m.telegram_chat_id = :chat AND m.message_id = :message"
                ),
                {"chat": chat_pk, "message": message_id},
            )
        )
        .mappings()
        .one()
    )
    removed = row["text_purged_at"] is not None or row["payload_purged_at"] is not None
    aged_out = row["sent_at"] <= now - timedelta(days=retention_days)
    text: str | None = None
    if not removed and not aged_out and row["payload"] is not None:
        body = row["payload"].get(row["update_type"]) or {}
        text, _normalized = extract_text(body)
    return _Anchor(
        message_id=message_id,
        sent_at=row["sent_at"],
        text=text,
        removed=removed,
        aged_out=aged_out,
    )


async def _chat(session: AsyncSession, chat_pk: int) -> Any:
    return (
        (
            await session.execute(
                sa.text(
                    "SELECT id, chat_id, chat_type, title, username, is_monitored, "
                    "       last_event_at, bot_status, bot_status_at "
                    "FROM telegram_chats WHERE id = :id"
                ),
                {"id": chat_pk},
            )
        )
        .mappings()
        .one()
    )


async def _team(session: AsyncSession, chat_pk: int, now: datetime) -> tuple[Person, ...]:
    ids = await team_at(session, telegram_chat_id=chat_pk, t=now)
    people = await _people(session, ids)
    return tuple(people[i] for i in ids if i in people)


def _base(alert: AlertRef, chat: Any, settings: RenderSettings) -> dict[str, Any]:
    max_repeats = alert.rule_values.get("max_repeats")
    return {
        "alert_id": alert.id,
        "trigger": alert.trigger,
        "subject_id": alert.subject_id,
        "chat_pk": int(chat["id"]),
        "repeat_index": alert.repeat_index,
        "max_repeats": int(max_repeats) if max_repeats is not None else None,
        "fired_at": alert.fired_at,
        "group_title": chat["title"],
        "chat_type": chat["chat_type"],
        "chat_platform_id": int(chat["chat_id"]),
        "chat_username": chat["username"],
        "panel_base_url": settings.panel_base_url,
    }


async def _item_input(
    session: AsyncSession, alert: AlertRef, settings: RenderSettings, now: datetime
) -> RenderInput:
    item = (
        (
            await session.execute(
                sa.text(
                    "SELECT i.telegram_chat_id, i.telegram_message_id, i.opened_at, i.status, "
                    "       i.first_response_at, i.first_response_moderator_id, "
                    "       i.closed_at, i.closed_by_user_id, i.closed_by_moderator_id, "
                    "       a.assigned_moderator_id, a.assigned_via "
                    "FROM attention_items i "
                    "LEFT JOIN attention_item_assignee a ON a.attention_item_id = i.id "
                    "WHERE i.id = :id"
                ),
                {"id": alert.subject_id},
            )
        )
        .mappings()
        .one()
    )
    chat = await _chat(session, int(item["telegram_chat_id"]))
    anchor = await _anchor(
        session,
        int(item["telegram_chat_id"]),
        int(item["telegram_message_id"]),
        now=now,
        retention_days=settings.retention_days,
    )
    people = await _people(
        session,
        [
            item["assigned_moderator_id"],
            item["first_response_moderator_id"],
            item["closed_by_moderator_id"],
        ],
    )
    status = item["status"]
    end: SubjectEnd | None = None
    if status == "answered":
        responder = people.get(item["first_response_moderator_id"])
        end = SubjectEnd(
            kind="answered_moderator" if responder else "answered_member",
            at=item["first_response_at"],
            actor=responder,
            actor_kind="moderator" if responder else None,
        )
    elif status == "dismissed":
        closer = people.get(item["closed_by_moderator_id"])
        end = SubjectEnd(
            kind="dismissed",
            at=item["closed_at"],
            actor=closer,
            actor_kind="moderator" if closer else "panel_user",
        )
    elif status == "expired":
        end = SubjectEnd(kind="expired", at=item["closed_at"])
    assignee = people.get(item["assigned_moderator_id"])
    return RenderInput(
        **_base(alert, chat, settings),
        status=status,
        end=end,
        anchor_message_id=anchor.message_id,
        anchor_text=anchor.text,
        text_removed=anchor.removed,
        text_aged_out=anchor.aged_out,
        opened_at=item["opened_at"],
        posted_at=anchor.sent_at,
        assignee=assignee,
        assigned_via=item["assigned_via"] if assignee else None,
        team=() if assignee or end else await _team(session, int(chat["id"]), now),
    )


async def _incident_input(
    session: AsyncSession, alert: AlertRef, settings: RenderSettings, now: datetime
) -> RenderInput:
    incident = (
        (
            await session.execute(
                sa.text(
                    "SELECT i.telegram_chat_id, i.telegram_message_id, i.opened_at, "
                    "       i.detected_at, i.source, i.category, i.severity, "
                    "       s.status, s.resolved_at, s.resolution_kind, "
                    "       s.resolved_by_moderator_id, s.resolved_by_telegram_user_id, "
                    "       s.resolved_by_anonymous, s.resolved_by_user_id, "
                    "       s.closed_at, s.closed_by_user_id, s.closed_by_moderator_id, "
                    "       a.assigned_moderator_id, a.assigned_via "
                    "FROM moderation_incidents i "
                    "JOIN moderation_incident_state s ON s.incident_id = i.id "
                    "LEFT JOIN moderation_incident_assignee a ON a.incident_id = i.id "
                    "WHERE i.id = :id"
                ),
                {"id": alert.subject_id},
            )
        )
        .mappings()
        .one()
    )
    chat = await _chat(session, int(incident["telegram_chat_id"]))
    anchor = await _anchor(
        session,
        int(incident["telegram_chat_id"]),
        int(incident["telegram_message_id"]),
        now=now,
        retention_days=settings.retention_days,
    )
    people = await _people(
        session,
        [
            incident["assigned_moderator_id"],
            incident["resolved_by_moderator_id"],
            incident["closed_by_moderator_id"],
        ],
    )
    status = incident["status"]
    end: SubjectEnd | None = None
    if status == "closed_false_positive":
        closer = people.get(incident["closed_by_moderator_id"])
        end = SubjectEnd(
            kind="false_positive",
            at=incident["closed_at"],
            actor=closer,
            actor_kind="moderator" if closer else "panel_user",
        )
    elif status == "resolved":
        resolver = people.get(incident["resolved_by_moderator_id"])
        if resolver is not None:
            actor_kind = "moderator"
        elif incident["resolved_by_anonymous"]:
            actor_kind = "anonymous"
        elif incident["resolved_by_telegram_user_id"] is not None:
            actor_kind = "administrator"
        else:
            actor_kind = "panel_user"
        end = SubjectEnd(
            kind="resolved",
            at=incident["resolved_at"],
            actor=resolver,
            actor_kind=actor_kind,
            how=incident["resolution_kind"],
        )
    assignee = people.get(incident["assigned_moderator_id"])
    return RenderInput(
        **_base(alert, chat, settings),
        status=status,
        end=end,
        anchor_message_id=anchor.message_id,
        anchor_text=anchor.text,
        text_removed=anchor.removed,
        text_aged_out=anchor.aged_out,
        opened_at=incident["opened_at"],
        posted_at=anchor.sent_at,
        detected_at=incident["detected_at"],
        category=incident["category"],
        severity=incident["severity"],
        opener=incident["source"],
        assignee=assignee,
        assigned_via=incident["assigned_via"] if assignee else None,
        team=() if assignee or end else await _team(session, int(chat["id"]), now),
    )


def _chat_input(alert: AlertRef, chat: Any, settings: RenderSettings) -> RenderInput:
    """U5: a group alert ends when its episode moves. The standing shown is the one at firing:
    the stored `rendered_state` once posted, else the chat's current one (its episode is current
    at delivery, V2)."""
    end: SubjectEnd | None = None
    if alert.trigger is Trigger.GROUP_SILENT:
        moved = chat["last_event_at"] is not None and (
            alert.episode_at is None or chat["last_event_at"] > alert.episode_at
        )
        if moved:
            end = SubjectEnd(kind="resumed", at=chat["last_event_at"])
        bot_status = None
    else:
        moved = chat["bot_status_at"] is not None and (
            alert.episode_at is None or chat["bot_status_at"] > alert.episode_at
        )
        if moved:
            end = SubjectEnd(
                kind="standing_changed", at=chat["bot_status_at"], new_status=chat["bot_status"]
            )
        stored = (alert.rendered_state or {}).get("bot_status")
        bot_status = stored if stored is not None else (None if moved else chat["bot_status"])
    return RenderInput(
        **_base(alert, chat, settings),
        status=CHAT_ENDED if end else CHAT_LIVE,
        end=end,
        episode_at=alert.episode_at,
        bot_status=bot_status,
    )


async def build_render_input(
    session: AsyncSession,
    alert: AlertRef,
    settings: RenderSettings,
    *,
    now: datetime | None = None,
) -> RenderInput:
    """One alert's `RenderInput`, from the derived state at `now` (the database's, by default)."""
    instant = now or await _now(session)
    if alert.subject_type is SubjectType.ATTENTION_ITEM:
        return await _item_input(session, alert, settings, instant)
    if alert.subject_type is SubjectType.INCIDENT:
        return await _incident_input(session, alert, settings, instant)
    return _chat_input(alert, await _chat(session, alert.subject_id), settings)


# --- the evaluator framework (T517, F1-F8) ---

# R5: the rule in force for (chat, trigger) is the chat's own row if one exists, enabled or not,
# else the global row. Ordering `telegram_chat_id IS NULL` puts the chat's row first, and the
# outer `is_enabled` then lets a disabled chat row mute the trigger for that chat. The destination
# is never monitored (D2), so `is_monitored` also keeps it out.
RULE_IN_FORCE = """
rule_in_force AS (
    SELECT c.id AS chat_pk, r.id AS rule_id, r.threshold_s, r.min_severity, r.categories,
           r.openers, r.enabled_at
    FROM telegram_chats c
    JOIN LATERAL (
        SELECT * FROM alert_rules r
        WHERE r.trigger = :trigger
          AND (r.telegram_chat_id = c.id OR r.telegram_chat_id IS NULL)
        ORDER BY r.telegram_chat_id IS NULL, r.id
        LIMIT 1
    ) r ON true
    WHERE c.is_monitored AND r.is_enabled
)
"""

# One statement per trigger, added by the stories (T519, T526, T527, T544, T545). Each is a
# `SELECT` over `rule_in_force` returning exactly
# `(rule_id, chat_pk, subject_type, subject_id, episode_at, qualified_at)`, with "now" as the
# statement's own `now()` (F1). The framework applies FR-515's `qualified_at >= enabled_at`.
STATEMENTS: dict[Trigger, str] = {}


def register_statement(trigger: Trigger, statement: str) -> None:
    STATEMENTS[trigger] = statement


# F1, `question_waiting` (US1, T519): an open item waiting at least the threshold. Its qualifying
# moment is `opened_at + threshold`. The item's state is `attention_items.status`, never
# recomputed. Written as `opened_at <= now() - threshold` so `ix_attention_open` serves it.
QUESTION_WAITING = """
SELECT f.rule_id, f.chat_pk, 'attention_item'::text AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at,
       i.opened_at + f.threshold_s * interval '1 second' AS qualified_at
FROM rule_in_force f
JOIN attention_items i ON i.telegram_chat_id = f.chat_pk
WHERE i.status = 'open'
  AND i.opened_at <= now() - f.threshold_s * interval '1 second'
"""

register_statement(Trigger.QUESTION_WAITING, QUESTION_WAITING)

# F1, the two incident triggers (US2, T526). An incident qualifies while
# `moderation_incident_state.status` is `open` or `acknowledged` (never recomputed, FR-521) and the
# rule's filters match (R4, a NULL filter matches everything):
# - `min_severity` in the order `low < medium < high`, as `domain.alerting.severity_at_least`;
#   an unknown value matches nothing (`array_position` is NULL);
# - `categories` and `openers` as JSONB arrays containing the incident's `category` and `source`.
# The FR-515 bound is repeated inside each statement so the state view is evaluated only for
# incidents that can still qualify; the framework applies it again.
_INCIDENT_FILTERS = """
  AND (f.min_severity IS NULL
       OR array_position(ARRAY['low', 'medium', 'high'], i.severity::text)
          >= array_position(ARRAY['low', 'medium', 'high'], f.min_severity::text))
  AND (f.categories IS NULL OR f.categories @> jsonb_build_array(i.category))
  AND (f.openers IS NULL OR f.openers @> jsonb_build_array(i.source))
"""

# `incident_flagged`: qualifying moment `detected_at`.
INCIDENT_FLAGGED = (
    """
SELECT f.rule_id, f.chat_pk, 'incident'::text AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at,
       i.detected_at AS qualified_at
FROM rule_in_force f
JOIN moderation_incidents i ON i.telegram_chat_id = f.chat_pk
JOIN moderation_incident_state s ON s.incident_id = i.id
WHERE i.detected_at >= f.enabled_at
  AND s.status IN ('open', 'acknowledged')
"""
    + _INCIDENT_FILTERS
)

# `incident_unhandled`: measured from `detected_at`, not `opened_at` (an operator may open an
# incident on an old message); qualifying moment `detected_at + threshold`.
INCIDENT_UNHANDLED = (
    """
SELECT f.rule_id, f.chat_pk, 'incident'::text AS subject_type, i.id AS subject_id,
       NULL::timestamptz AS episode_at,
       i.detected_at + f.threshold_s * interval '1 second' AS qualified_at
FROM rule_in_force f
JOIN moderation_incidents i ON i.telegram_chat_id = f.chat_pk
JOIN moderation_incident_state s ON s.incident_id = i.id
WHERE i.detected_at <= now() - f.threshold_s * interval '1 second'
  AND i.detected_at + f.threshold_s * interval '1 second' >= f.enabled_at
  AND s.status IN ('open', 'acknowledged')
"""
    + _INCIDENT_FILTERS
)

register_statement(Trigger.INCIDENT_FLAGGED, INCIDENT_FLAGGED)
register_statement(Trigger.INCIDENT_UNHANDLED, INCIDENT_UNHANDLED)

# F1, the two health triggers (US5, T544, D-TG-214). The subject is the chat itself, and the
# episode is the instant that opened it: a newer one is a new episode, with its own alert and its
# own dedupe key (U5). `rule_in_force` already keeps unmonitored chats out, and with them the
# destination (D2).
#
# `group_silent`: no event for at least the threshold. Episode `last_event_at`; qualifying moment
# `last_event_at + threshold`. A chat never seen (`last_event_at` NULL) has no episode.
GROUP_SILENT = """
SELECT f.rule_id, f.chat_pk, 'chat'::text AS subject_type, c.id AS subject_id,
       c.last_event_at AS episode_at,
       c.last_event_at + f.threshold_s * interval '1 second' AS qualified_at
FROM rule_in_force f
JOIN telegram_chats c ON c.id = f.chat_pk
WHERE c.last_event_at IS NOT NULL
  AND c.last_event_at <= now() - f.threshold_s * interval '1 second'
"""

# `bot_not_admin`: the bot's standing is known and is not administrator. Episode and qualifying
# moment `bot_status_at`, written with every standing change; `unknown` (never reported) never
# alerts.
BOT_NOT_ADMIN = """
SELECT f.rule_id, f.chat_pk, 'chat'::text AS subject_type, c.id AS subject_id,
       c.bot_status_at AS episode_at,
       c.bot_status_at AS qualified_at
FROM rule_in_force f
JOIN telegram_chats c ON c.id = f.chat_pk
WHERE c.bot_status NOT IN ('administrator', 'unknown')
  AND c.bot_status_at IS NOT NULL
"""

register_statement(Trigger.GROUP_SILENT, GROUP_SILENT)
register_statement(Trigger.BOT_NOT_ADMIN, BOT_NOT_ADMIN)


def _candidates_sql(statement: str) -> sa.TextClause:
    return sa.text(
        "WITH "
        + RULE_IN_FORCE
        + ", candidates AS ("
        + statement
        + """)
SELECT q.rule_id, q.chat_pk, q.subject_type, q.subject_id, q.episode_at, q.qualified_at,
       r.telegram_chat_id AS rule_chat_id, r.threshold_s, r.min_severity, r.categories,
       r.openers, r.repeat_every_s, r.max_repeats, r.quiet_hours, r.enabled_at,
       h.first_fired_at, h.max_index, now() AS now
FROM candidates q
JOIN alert_rules r ON r.id = q.rule_id
LEFT JOIN LATERAL (
    SELECT min(a.fired_at) FILTER (WHERE a.repeat_index = 0) AS first_fired_at,
           max(a.repeat_index)                               AS max_index
    FROM alerts a
    WHERE a.alert_rule_id = q.rule_id
      AND a.subject_type  = q.subject_type
      AND a.subject_id    = q.subject_id
      AND a.episode_at IS NOT DISTINCT FROM q.episode_at
) h ON true
WHERE q.qualified_at >= r.enabled_at
ORDER BY q.qualified_at, q.subject_id
"""
    )


# F2/F3: the insert carries its own "no index >= k yet" guard, so two evaluators that both
# computed a repeat cannot add one below an index the other already recorded; `uq_alerts_dedupe`
# settles an exact tie.
_INSERT = sa.text(
    """
INSERT INTO alerts (alert_rule_id, trigger, telegram_chat_id, subject_type, subject_id,
                    episode_at, repeat_index, dedupe_key, rule_values, qualified_at,
                    delivery_status)
SELECT :rule_id, :trigger, :chat_pk, :subject_type, :subject_id, :episode_at, :repeat_index,
       :dedupe_key, :rule_values, :qualified_at, :delivery_status
WHERE NOT EXISTS (
    SELECT 1 FROM alerts a
    WHERE a.alert_rule_id = :rule_id
      AND a.subject_type  = :subject_type
      AND a.subject_id    = :subject_id
      AND a.episode_at IS NOT DISTINCT FROM :episode_at
      AND a.repeat_index >= :repeat_index
)
ON CONFLICT (dedupe_key) DO NOTHING
RETURNING id
"""
).bindparams(
    # Typed, so a parameter used twice is never deduced as two types.
    sa.bindparam("rule_id", type_=sa.BigInteger()),
    sa.bindparam("trigger", type_=sa.String()),
    sa.bindparam("chat_pk", type_=sa.BigInteger()),
    sa.bindparam("subject_type", type_=sa.String()),
    sa.bindparam("subject_id", type_=sa.BigInteger()),
    sa.bindparam("episode_at", type_=sa.DateTime(timezone=True)),
    sa.bindparam("repeat_index", type_=sa.SmallInteger()),
    sa.bindparam("dedupe_key", type_=sa.String()),
    sa.bindparam("rule_values", type_=JSONB()),
    sa.bindparam("qualified_at", type_=sa.DateTime(timezone=True)),
    sa.bindparam("delivery_status", type_=sa.String()),
)


def rule_values(row: Any) -> dict[str, Any]:
    """F4: the rule's values in force at firing, kept on the alert."""
    return {
        "rule_chat_id": row["rule_chat_id"],
        "threshold_s": row["threshold_s"],
        "min_severity": row["min_severity"],
        "categories": row["categories"],
        "openers": row["openers"],
        "repeat_every_s": row["repeat_every_s"],
        "max_repeats": row["max_repeats"],
        "quiet_hours": row["quiet_hours"],
        "enabled_at": row["enabled_at"].isoformat() if row["enabled_at"] else None,
    }


@dataclass
class Evaluation:
    """One evaluation's result: the ids to deliver (non-suppressed inserts), how many were
    suppressed, and how many quiet-hours windows were skipped as malformed."""

    to_deliver: list[int] = field(default_factory=list)
    suppressed: list[int] = field(default_factory=list)
    skipped_windows: int = 0


async def evaluate_once(session: AsyncSession) -> Evaluation:
    """F1-F8 in one transaction, so every insert shares the statement's `now()` as `fired_at`.
    Commits. Writes only `alerts` (F7)."""
    result = Evaluation()
    inserted_subjects: set[tuple[str, int]] = set()  # F6
    for trigger in Trigger:
        statement = STATEMENTS.get(trigger)
        if statement is None:
            continue
        rows = (
            (await session.execute(_candidates_sql(statement), {"trigger": trigger.value}))
            .mappings()
            .all()
        )
        for row in rows:
            subject_type = SubjectType(row["subject_type"])
            if subject_type is not SUBJECT_OF[trigger]:
                raise ValueError(f"{trigger.value}'s statement returned a {subject_type.value}")
            subject = (subject_type.value, int(row["subject_id"]))
            if subject in inserted_subjects:
                continue
            now: datetime = row["now"]
            if row["max_index"] is None:
                index = 0
            else:
                index = due_repeat_index(
                    row["first_fired_at"] or now,
                    now,
                    row["repeat_every_s"],
                    row["max_repeats"],
                )
                if index < 1 or index <= row["max_index"]:
                    continue
            windows, skipped = parse_quiet_hours(row["quiet_hours"])
            result.skipped_windows += skipped
            status = "suppressed" if in_quiet_hours(windows, now) else "pending"
            alert_id = (
                await session.execute(
                    _INSERT,
                    {
                        "rule_id": row["rule_id"],
                        "trigger": trigger.value,
                        "chat_pk": row["chat_pk"],
                        "subject_type": subject_type.value,
                        "subject_id": row["subject_id"],
                        "episode_at": row["episode_at"],
                        "repeat_index": index,
                        "dedupe_key": dedupe_key(
                            row["rule_id"],
                            subject_type,
                            row["subject_id"],
                            row["episode_at"],
                            index,
                        ),
                        "rule_values": rule_values(row),
                        "qualified_at": row["qualified_at"],
                        "delivery_status": status,
                    },
                )
            ).scalar_one_or_none()
            if alert_id is None:
                continue
            inserted_subjects.add(subject)
            (result.suppressed if status == "suppressed" else result.to_deliver).append(
                int(alert_id)
            )
    await session.commit()
    return result


# --- the refresh scan (§6) ---


async def changed_alerts(
    session_factory: async_sessionmaker[AsyncSession], settings: RenderSettings
) -> list[int]:
    """Every `sent` alert still followed — `final_at IS NULL` (its subject may end) or
    `excerpt_shown` (its words may age out) — with fewer than `MAX_EDIT_ATTEMPTS` consecutive
    failed edits, whose computed render state differs from the stored one or whose subject has
    ended without `final_at` yet."""
    changed: list[int] = []
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    sa.select(alerts)
                    .where(
                        alerts.c.delivery_status == "sent",
                        sa.or_(alerts.c.final_at.is_(None), alerts.c.excerpt_shown.is_(True)),
                        alerts.c.edit_attempts < MAX_EDIT_ATTEMPTS,
                    )
                    .order_by(alerts.c.id)
                )
            )
            .mappings()
            .all()
        )
        now = await _now(session)
        for row in rows:
            alert = AlertRef.from_row(row)
            try:
                data = await build_render_input(session, alert, settings, now=now)
            except NoResultFound:
                # The subject row is gone (never in production: nothing deletes one). One alert
                # must not stop the scan for every other.
                logger.warning("alert subject not found; skipped", extra={"alert_id": alert.id})
                continue
            live = await subject_live(session, alert)
            if render_state(data) != alert.rendered_state or (
                not live and alert.final_at is None
            ):
                changed.append(alert.id)
    return changed
