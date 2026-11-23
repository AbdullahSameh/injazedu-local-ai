"""Everything the bot says in the alert group (TG-M6, `contracts/alert-messages.md` §1-§7).

Pure: a function of a frozen `RenderInput` — the alert row, the subject's derived state, the names
and the held text — with no session and no clock. The times shown come from the rows, and an age is
frozen at firing, so a waiting alert renders the same text on every tick.

- `render_alert(input)` → `(html, reply_markup)`;
- `render_state(input)` → the JSON-able inputs that change the text (U1, D-TG-216), never the text;
- `answer_text(outcome, …)` → the answer to a press (§5);
- `excerpt(text, removed, aged_out)` → the redacted, cut excerpt (§2, D-TG-221).

**Arabic only** (FR-533). Category, severity, opener, status, actor and "via" words are the
panel's own Arabic, keyed here by the panel's English string; `test_alert_glossary.py` asserts each
equals `apps/ai-control/lang/ar.json` (D-TG-222), so an alert and the panel cannot drift.

**Never** (§7): no deletion or removal word (W1), no confidence, percentage or probability (W2),
never "confirmed" (W3), and no student name, username or Telegram id — only moderators are
mentioned (W4). Nothing here logs.

The panel paths below were read from `php artisan route:list` (2026-11-14). The queue page has no
URL filter, so a question's panel link opens the queue itself.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application.moderation.text import normalize, redact
from app.domain.moderation.alerting import (
    ALERT_TIMEZONE,
    PressAction,
    PressOutcome,
    SubjectType,
    Trigger,
    encode_callback,
)

PANEL_INCIDENT_PATH = "/admin/incidents/{id}"
PANEL_QUEUE_PATH = "/admin/live-attention-queue"
PANEL_GROUP_PATH = "/admin/telegram-chats/{id}/edit"

# D-TG-224 / probe P2: the panel link is a URL button. If Telegram refuses the URL, flip this and
# the link moves into the text (`alert-messages.md` §5 allows both).
PANEL_LINK_AS_BUTTON = True

MAX_RENDERED_CHARS = 1000
EXCERPT_MAX_CHARS = 100
TITLE_MAX_CHARS = 80
NAME_MAX_CHARS = 60
TEAM_MAX_MENTIONS = 6

# The panel's English string → its Arabic (`apps/ai-control/lang/ar.json`). Only these words are
# shared with the panel; every other string below is the alert group's own.
GLOSSARY: dict[str, str] = {
    # categories (the codes are the panel's keys)
    "SPAM_OR_AD": "رسائل مزعجة أو إعلان",
    "ABUSE": "إساءة",
    "OTHER": "أخرى",
    # severities
    "low": "منخفضة",
    "medium": "متوسطة",
    "high": "عالية",
    # openers (IncidentDisplay::openerLabel)
    "Link rule": "قاعدة الروابط",
    "Model": "النموذج",
    "Operator": "مشغّل اللوحة",
    # the bot's standing in a group
    "member": "عضو",
    "left": "غادر",
    "kicked": "طُرد",
    "restricted": "مقيّد",
    "administrator": "مسؤول",
    # responsibility (TeamAssignment::label / viaLabel)
    "Team: :names": "الفريق: :names",
    "No team": "بلا فريق",
    "Not taken by the team": "لم يتولّه أحد من الفريق",
    "via reply": "بالرد",
    "via dismissal": "بالاستبعاد",
    "via reaction": "بالتفاعل",
    "via alert": "من التنبيه",
    "via a ban or restriction": "بالحظر أو التقييد",
    "via panel acknowledge": "بالاستلام من اللوحة",
    "via panel resolve": "بالحل من اللوحة",
    "via Not a violation": "بـ«ليست مخالفة»",
    # actors
    "anonymous administrator": "مسؤول مجهول الهوية",
}

_OPENER_KEY = {"rule": "Link rule", "ai": "Model", "operator": "Operator"}

_VIA_KEY = {
    "reply": "via reply",
    "dismissal": "via dismissal",
    "reaction": "via reaction",
    "alert": "via alert",
    "alert_handled": "via alert",
    "alert_false_positive": "via alert",
    "ban": "via a ban or restriction",
    "expulsion": "via a ban or restriction",
    "restriction": "via a ban or restriction",
    "panel_acknowledge": "via panel acknowledge",
    "panel_resolve": "via panel resolve",
    "panel_false_positive": "via Not a violation",
}

# §6 `{how}`: how an incident was resolved, by the resolving evidence's kind.
_HOW = {
    "ban": "بحظر العضو",
    "expulsion": "بطرده",
    "restriction": "بتقييده",
    "reaction": "بتفاعل 👀",
    "panel_resolve": "من اللوحة",
    "alert_handled": "من التنبيه",
}

HEADERS: dict[Trigger, str] = {
    Trigger.QUESTION_WAITING: "⏳ سؤال ينتظر الرد",
    Trigger.INCIDENT_FLAGGED: "🚨 رُصدت مخالفة",
    Trigger.INCIDENT_UNHANDLED: "⚠️ مخالفة لم تُعالَج بعد",
    Trigger.GROUP_SILENT: "🔇 لا نشاط مسجَّل في مجموعة",
    Trigger.BOT_NOT_ADMIN: "🛑 البوت لم يعد مشرفاً في مجموعة",
}

BUTTON_HANDLED = "✅ تمت المعالجة"
BUTTON_FALSE_POSITIVE = "🚫 ليست مخالفة"
BUTTON_TAKE = "🙋 أتولّاه"
BUTTON_PANEL = "فتح في اللوحة"

TEXT_NOT_HELD = "النص لم يعد محفوظاً"
NO_MESSAGE_LINK = "(لا يمكن الربط برسالة في مجموعة عادية)"


# --- inputs ---


@dataclass(frozen=True)
class Person:
    """A moderator named in an alert. Only moderators are ever named (W4)."""

    moderator_id: int
    name: str
    tg_user_id: int | None


@dataclass(frozen=True)
class SubjectEnd:
    """How the subject ended, from the derived state (U1).

    `kind` is one of: `answered_moderator`, `answered_member`, `dismissed`, `expired` (items);
    `resolved`, `false_positive` (incidents); `resumed`, `standing_changed` (groups).
    `actor_kind` is `moderator`, `panel_user` (unlinked), `anonymous` or `administrator` (a group
    administrator who is not a declared moderator, never named). `how` is the resolving
    evidence's kind. `new_status` is the bot's standing after a change.
    """

    kind: str
    at: datetime
    actor: Person | None = None
    actor_kind: str | None = None
    how: str | None = None
    new_status: str | None = None


@dataclass(frozen=True)
class RenderInput:
    alert_id: int
    trigger: Trigger
    subject_id: int
    chat_pk: int
    repeat_index: int
    max_repeats: int | None
    fired_at: datetime
    group_title: str | None
    chat_type: str
    chat_platform_id: int
    chat_username: str | None
    status: str
    end: SubjectEnd | None = None
    # the anchor message (items and incidents)
    anchor_message_id: int | None = None
    anchor_text: str | None = None
    text_removed: bool = False
    text_aged_out: bool = False
    # items and incidents
    opened_at: datetime | None = None
    posted_at: datetime | None = None
    detected_at: datetime | None = None
    category: str | None = None
    severity: str | None = None
    opener: str | None = None
    # groups: the episode that opened the alert, and the standing at firing
    episode_at: datetime | None = None
    bot_status: str | None = None
    # responsibility
    assignee: Person | None = None
    assigned_via: str | None = None
    team: tuple[Person, ...] = field(default_factory=tuple)
    panel_base_url: str | None = None

    @property
    def subject_type(self) -> SubjectType:
        if self.trigger is Trigger.QUESTION_WAITING:
            return SubjectType.ATTENTION_ITEM
        if self.trigger in (Trigger.INCIDENT_FLAGGED, Trigger.INCIDENT_UNHANDLED):
            return SubjectType.INCIDENT
        return SubjectType.CHAT

    @property
    def ended(self) -> bool:
        return self.end is not None


# --- small pieces ---


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _cut(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _local(instant: datetime) -> datetime:
    return instant.astimezone(ALERT_TIMEZONE)


def format_time(instant: datetime, reference: datetime) -> str:
    """`HH:MM` in Riyadh, or `YYYY-MM-DD HH:MM` on a different Riyadh day from `reference`."""
    local = _local(instant)
    if local.date() != _local(reference).date():
        return local.strftime("%Y-%m-%d %H:%M")
    return local.strftime("%H:%M")


def _count(n: int, one: str, two: str, few: str, many: str) -> str:
    """Arabic number agreement (§3): 1, 2, 3-10, 11+."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def _minutes(n: int) -> str:
    return _count(n, "دقيقة", "دقيقتين", "دقائق", "دقيقة")


def _hours(n: int) -> str:
    return _count(n, "ساعة", "ساعتين", "ساعات", "ساعة")


def _days(n: int) -> str:
    return _count(n, "يوم", "يومين", "أيام", "يوماً")


def format_duration(seconds: float) -> str:
    """An age with Arabic number agreement (§3). Under a minute is `أقل من دقيقة`."""
    total_minutes = int(seconds // 60)
    if total_minutes < 1:
        return "أقل من دقيقة"
    if total_minutes < 60:
        return _minutes(total_minutes)
    total_hours, minutes = divmod(total_minutes, 60)
    if total_hours < 24:
        return _hours(total_hours) + (f" و{_minutes(minutes)}" if minutes else "")
    days, hours = divmod(total_hours, 24)
    return _days(days) + (f" و{_hours(hours)}" if hours else "")


def excerpt(text: str | None, removed: bool, aged_out: bool) -> str | None:
    """§2: the first-posted words, normalised and redacted (links, emails, handles and long digit
    runs become placeholders), cut at a word boundary to 100 characters with `…`. `TEXT_NOT_HELD`
    once the text is purged or past the retention age; `None` for media with no text."""
    if removed or aged_out:
        return TEXT_NOT_HELD
    if text is None:
        return None
    cleaned = " ".join(redact(normalize(text)).split())
    if not cleaned:
        return None
    if len(cleaned) <= EXCERPT_MAX_CHARS:
        return cleaned
    cut = cleaned.rfind(" ", 0, EXCERPT_MAX_CHARS + 1)
    head = cleaned[:cut] if cut > 0 else cleaned[:EXCERPT_MAX_CHARS]
    return head.rstrip() + "…"


def excerpt_shown(data: RenderInput) -> bool:
    """Whether the rendered text carries actual words (the retention scan's flag)."""
    shown = excerpt(data.anchor_text, data.text_removed, data.text_aged_out)
    return shown is not None and shown != TEXT_NOT_HELD


def mention(person: Person) -> str:
    """D-TG-225: `tg://user` links notify the moderator; the name is escaped."""
    name = _esc(_cut(person.name, NAME_MAX_CHARS))
    if person.tg_user_id is None:
        return name
    return f'<a href="tg://user?id={int(person.tg_user_id)}">{name}</a>'


def _name(person: Person | None) -> str:
    return _esc(_cut(person.name, NAME_MAX_CHARS)) if person is not None else ""


def message_link(data: RenderInput) -> str | None:
    """T7: a public chat's `t.me/<username>/<id>`, a supergroup's `t.me/c/<id>/<id>`; a basic group
    has none."""
    if data.anchor_message_id is None:
        return None
    if data.chat_username and re.fullmatch(r"[A-Za-z0-9_]{4,64}", data.chat_username):
        return f"https://t.me/{data.chat_username}/{int(data.anchor_message_id)}"
    platform = str(data.chat_platform_id)
    if data.chat_type in ("supergroup", "channel") and platform.startswith("-100"):
        return f"https://t.me/c/{platform[4:]}/{int(data.anchor_message_id)}"
    return None


def panel_url(data: RenderInput) -> str | None:
    if not data.panel_base_url:
        return None
    if data.subject_type is SubjectType.INCIDENT:
        path = PANEL_INCIDENT_PATH.format(id=int(data.subject_id))
    elif data.subject_type is SubjectType.ATTENTION_ITEM:
        path = PANEL_QUEUE_PATH
    else:
        path = PANEL_GROUP_PATH.format(id=int(data.chat_pk))
    return data.panel_base_url.rstrip("/") + path


def _via(via: str | None) -> str:
    key = _VIA_KEY.get(via or "")
    return GLOSSARY[key] if key else ""


def _responsible(data: RenderInput) -> str | None:
    if data.subject_type is SubjectType.CHAT:
        return None
    if data.assignee is not None:
        via = _via(data.assigned_via)
        return f"المسؤول: {mention(data.assignee)}" + (f" · {via}" if via else "")
    if data.ended:
        return GLOSSARY["Not taken by the team"]
    if data.team:
        names = [mention(p) for p in data.team[:TEAM_MAX_MENTIONS]]
        if len(data.team) > TEAM_MAX_MENTIONS:
            names.append("…")
        return GLOSSARY["Team: :names"].replace(":names", "، ".join(names))
    return GLOSSARY["No team"]


def _actor(end: SubjectEnd) -> str:
    if end.actor_kind == "anonymous":
        return GLOSSARY["anonymous administrator"]
    if end.actor is not None:
        return _name(end.actor)
    if end.actor_kind == "administrator":
        # A Telegram administrator who is not a declared moderator: never named (W4).
        return GLOSSARY["administrator"]
    return GLOSSARY["Operator"]


def _standing(status: str | None) -> str:
    return GLOSSARY.get(status or "", _esc(status or "—"))


def status_line(data: RenderInput) -> str | None:
    """§6: the line an edit adds once the subject has ended, or an item has been taken."""
    end = data.end
    ref = data.fired_at
    if end is None:
        if data.subject_type is SubjectType.ATTENTION_ITEM and data.assignee is not None:
            return f"🙋 يتولّاه {_name(data.assignee)}"
        return None
    at = format_time(end.at, ref)
    if end.kind == "answered_moderator":
        return f"✅ أُجيب عنه — {_name(end.actor)} الساعة {at}"
    if end.kind == "answered_member":
        return f"✅ أجاب عنه عضو الساعة {at}"
    if end.kind == "dismissed":
        return f"استُبعد — {_actor(end)} الساعة {at}"
    if end.kind == "expired":
        return f"انتهت مهلته الساعة {at} دون رد"
    if end.kind == "resolved":
        how = _HOW.get(end.how or "")
        return f"✅ عولجت — {_actor(end)}" + (f" · {how}" if how else "") + f" الساعة {at}"
    if end.kind == "false_positive":
        return f"🚫 ليست مخالفة — {_actor(end)} الساعة {at}"
    if end.kind == "resumed":
        return f"عاد النشاط الساعة {at}"
    if end.kind == "standing_changed":
        return f"تغيّرت حالة البوت الساعة {at}: {_standing(end.new_status)}"
    return None


def _header(data: RenderInput) -> str:
    header = HEADERS[data.trigger]
    if data.repeat_index >= 1 and data.max_repeats:
        header += f" · تذكير {data.repeat_index} من {data.max_repeats}"
    return header


def _age(data: RenderInput, start: datetime | None) -> str | None:
    if start is None:
        return None
    return format_duration(max((data.fired_at - start).total_seconds(), 0.0))


def _body(data: RenderInput) -> list[str]:
    ref = data.fired_at
    title = _esc(_cut(data.group_title or "—", TITLE_MAX_CHARS))
    lines = [f"المجموعة: {title}"]
    words = excerpt(data.anchor_text, data.text_removed, data.text_aged_out)
    quoted = None
    if words is not None:
        quoted = words if words == TEXT_NOT_HELD else f"«{_esc(words)}»"

    if data.subject_type is SubjectType.ATTENTION_ITEM:
        if quoted:
            lines.append(quoted)
        if data.opened_at is not None:
            lines.append(
                f"سُئل الساعة {format_time(data.opened_at, ref)} · "
                f"انتظر {_age(data, data.opened_at)} عند التنبيه"
            )
    elif data.subject_type is SubjectType.INCIDENT:
        category = GLOSSARY.get(data.category or "", _esc(data.category or "—"))
        severity = GLOSSARY.get(data.severity or "", _esc(data.severity or "—"))
        lines.append(f"الفئة: {category} · الخطورة: {severity}")
        if quoted:
            lines.append(quoted)
        opener = GLOSSARY[_OPENER_KEY.get(data.opener or "", "Operator")]
        facts = [f"فُتحت بواسطة: {opener}"]
        if data.posted_at is not None:
            facts.append(f"نُشرت {format_time(data.posted_at, ref)}")
        if data.detected_at is not None:
            facts.append(f"رُصدت {format_time(data.detected_at, ref)}")
        lines.append(" · ".join(facts))
        if data.trigger is Trigger.INCIDENT_UNHANDLED:
            lines.append(f"مضى على رصدها {_age(data, data.detected_at)} عند التنبيه")
    elif data.trigger is Trigger.GROUP_SILENT:
        if data.episode_at is not None:
            lines.append(
                f"آخر نشاط مسجَّل: {format_time(data.episode_at, ref)} · "
                f"منذ {_age(data, data.episode_at)} عند التنبيه"
            )
    else:  # bot_not_admin
        since = f" منذ {format_time(data.episode_at, ref)}" if data.episode_at else ""
        lines.append(f"حالة البوت: {_standing(data.bot_status)}{since}")
    return lines


def _links(data: RenderInput) -> list[str]:
    lines: list[str] = []
    if data.subject_type is not SubjectType.CHAT:
        link = message_link(data)
        if link is not None:
            lines.append(f'🔗 <a href="{html.escape(link)}">الرسالة</a>')
        else:
            lines.append(NO_MESSAGE_LINK)
    url = panel_url(data)
    if url is not None and not PANEL_LINK_AS_BUTTON:
        lines.append(f'🖥 <a href="{html.escape(url)}">{BUTTON_PANEL}</a>')
    return lines


def reply_markup(data: RenderInput) -> dict[str, Any] | None:
    """§5: the action row while the subject is live, then the panel row. Nothing once it ended."""
    if data.ended:
        return None
    rows: list[list[dict[str, str]]] = []
    if data.subject_type is SubjectType.INCIDENT:
        rows.append(
            [
                {
                    "text": BUTTON_HANDLED,
                    "callback_data": encode_callback(data.alert_id, PressAction.HANDLED),
                },
                {
                    "text": BUTTON_FALSE_POSITIVE,
                    "callback_data": encode_callback(data.alert_id, PressAction.FALSE_POSITIVE),
                },
            ]
        )
    elif data.subject_type is SubjectType.ATTENTION_ITEM:
        take = encode_callback(data.alert_id, PressAction.TAKE)
        rows.append([{"text": BUTTON_TAKE, "callback_data": take}])
    url = panel_url(data)
    if url is not None and PANEL_LINK_AS_BUTTON:
        rows.append([{"text": BUTTON_PANEL, "url": url}])
    return {"inline_keyboard": rows} if rows else None


def render_alert(data: RenderInput) -> tuple[str, dict[str, Any] | None]:
    """The alert's HTML text and inline keyboard. Absent lines are omitted, never left blank."""
    lines = [_header(data), *_body(data)]
    responsible = _responsible(data)
    if responsible:
        lines.append(responsible)
    lines.extend(_links(data))
    status = status_line(data)
    if status:
        lines.append(status)
    return "\n".join(lines), reply_markup(data)


def visible_length(rendered_html: str) -> int:
    """What Telegram counts: the text after HTML entities are parsed."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", rendered_html)))


def render_state(data: RenderInput) -> dict[str, Any]:
    """U1: the inputs that change the text — the subject's status and end (who, how, when), the
    current assignee and how they took it, and whether the excerpt shows. Ages are frozen at firing
    and so are not here. Never any text (D-TG-216)."""
    end = data.end
    return {
        "v": 1,
        "status": data.status,
        "end": None
        if end is None
        else {
            "kind": end.kind,
            "at": end.at.isoformat(),
            "actor": end.actor.moderator_id if end.actor else None,
            "actor_kind": end.actor_kind,
            "how": end.how,
            "new_status": end.new_status,
        },
        "assignee": data.assignee.moderator_id if data.assignee else None,
        "via": data.assigned_via if data.assignee else None,
        "excerpt": excerpt_shown(data),
        "bot_status": data.bot_status if data.trigger is Trigger.BOT_NOT_ADMIN else None,
    }


# --- answers to presses (§5) ---

_ENDED_WORDS: dict[str, str] = {
    "answered": "أُجيب عنه",
    "dismissed": "استُبعد",
    "expired": "انتهت مهلته",
    "resolved": "عولجت",
    "closed_false_positive": "ليست مخالفة",
}


def ended_word(status: str) -> str:
    return _ENDED_WORDS.get(status, "")


def answer_text(
    outcome: PressOutcome,
    *,
    action: PressAction | None = None,
    assignee_name: str | None = None,
    ended_status: str | None = None,
) -> str:
    """The press's answer (at most 200 characters, no `show_alert`). Plain text: no HTML here."""
    if outcome is PressOutcome.RECORDED:
        if action is PressAction.HANDLED:
            return "تم: عولجت المخالفة"
        if action is PressAction.FALSE_POSITIVE:
            return "تم: أُغلقت كرصد خاطئ"
        return "تم: السؤال لك"
    if outcome is PressOutcome.RECORDED_NOT_TEAM:
        return "سُجّل. لست في فريق هذه المجموعة، فلا يُسند إليك"
    if outcome is PressOutcome.ALREADY_TAKEN:
        return f"سُجّل. يتولّاه {_cut(assignee_name or '', NAME_MAX_CHARS)}".strip()
    if outcome is PressOutcome.ALREADY_ENDED:
        word = ended_word(ended_status or "")
        return f"انتهى هذا البند: {word}" if word else "انتهى هذا البند"
    if outcome is PressOutcome.NOT_A_MODERATOR:
        return "هذه الأزرار للمشرفين المعتمدين فقط"
    return "هذا الزر لم يعد صالحاً"
