"""`alert_render` (T511, T512) against `contracts/alert-messages.md` §1-§7. Pure: no database.

Escaping, every duration bucket, the excerpt (cut, redaction, not held, media), the three link
forms, the panel link, the 1,000-character bound, the keyboard, render state, the answers, and the
three "never" rules over every template and outcome: W1 (no deletion word), W2 (no confidence,
percentage or probability), W4 (only moderators are named).
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from app.application.moderation.alert_render import (
    NO_MESSAGE_LINK,
    TEXT_NOT_HELD,
    Person,
    RenderInput,
    SubjectEnd,
    answer_text,
    excerpt,
    format_duration,
    format_time,
    render_alert,
    render_state,
    visible_length,
)
from app.domain.moderation.alerting import PressAction, PressOutcome, Trigger

FIRED = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)  # 12:30 in Riyadh
SARA = Person(moderator_id=1, name="Sara", tg_user_id=111)
OMAR = Person(moderator_id=2, name="Omar", tg_user_id=222)
STUDENT_NAME = "Khalid Student"
STUDENT_USERNAME = "khalid_student99"
STUDENT_TG_ID = 987654321


def _question(**overrides: object) -> RenderInput:
    base = RenderInput(
        alert_id=41,
        trigger=Trigger.QUESTION_WAITING,
        subject_id=7,
        chat_pk=3,
        repeat_index=0,
        max_repeats=None,
        fired_at=FIRED,
        group_title="Math 101",
        chat_type="supergroup",
        chat_platform_id=-1001234567890,
        chat_username=None,
        status="open",
        anchor_message_id=555,
        anchor_text="When is the exam?",
        opened_at=FIRED - timedelta(minutes=12),
        team=(SARA, OMAR),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _incident(**overrides: object) -> RenderInput:
    base = RenderInput(
        alert_id=42,
        trigger=Trigger.INCIDENT_FLAGGED,
        subject_id=9,
        chat_pk=3,
        repeat_index=0,
        max_repeats=None,
        fired_at=FIRED,
        group_title="Math 101",
        chat_type="supergroup",
        chat_platform_id=-1001234567890,
        chat_username=None,
        status="open",
        anchor_message_id=556,
        anchor_text="Buy followers now",
        opened_at=FIRED - timedelta(minutes=3),
        posted_at=FIRED - timedelta(minutes=4),
        detected_at=FIRED - timedelta(minutes=3),
        category="SPAM_OR_AD",
        severity="high",
        opener="rule",
        team=(SARA,),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _silent(**overrides: object) -> RenderInput:
    base = RenderInput(
        alert_id=43,
        trigger=Trigger.GROUP_SILENT,
        subject_id=3,
        chat_pk=3,
        repeat_index=0,
        max_repeats=None,
        fired_at=FIRED,
        group_title="Math 101",
        chat_type="supergroup",
        chat_platform_id=-1001234567890,
        chat_username=None,
        status="active",
        episode_at=FIRED - timedelta(days=2, hours=3),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _bot(**overrides: object) -> RenderInput:
    base = RenderInput(
        alert_id=44,
        trigger=Trigger.BOT_NOT_ADMIN,
        subject_id=3,
        chat_pk=3,
        repeat_index=0,
        max_repeats=None,
        fired_at=FIRED,
        group_title="Math 101",
        chat_type="supergroup",
        chat_platform_id=-1001234567890,
        chat_username=None,
        status="active",
        episode_at=FIRED - timedelta(minutes=20),
        bot_status="member",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


# --- headers and bodies ---


def test_a_question_alert() -> None:
    text, markup = render_alert(_question())

    assert text.splitlines() == [
        "⏳ سؤال ينتظر الرد",
        "المجموعة: Math 101",
        "«When is the exam?»",
        "سُئل الساعة 12:18 · انتظر 12 دقيقة عند التنبيه",
        'الفريق: <a href="tg://user?id=111">Sara</a>، <a href="tg://user?id=222">Omar</a>',
        '🔗 <a href="https://t.me/c/1234567890/555">الرسالة</a>',
    ]
    assert markup == {"inline_keyboard": [[{"text": "🙋 أتولّاه", "callback_data": "a:41:t"}]]}


def test_an_incident_alert() -> None:
    text, markup = render_alert(_incident())

    assert text.splitlines() == [
        "🚨 رُصدت مخالفة",
        "المجموعة: Math 101",
        "الفئة: رسائل مزعجة أو إعلان · الخطورة: عالية",
        "«Buy followers now»",
        "فُتحت بواسطة: قاعدة الروابط · نُشرت 12:26 · رُصدت 12:27",
        'الفريق: <a href="tg://user?id=111">Sara</a>',
        '🔗 <a href="https://t.me/c/1234567890/556">الرسالة</a>',
    ]
    assert markup == {
        "inline_keyboard": [
            [
                {"text": "✅ تمت المعالجة", "callback_data": "a:42:h"},
                {"text": "🚫 ليست مخالفة", "callback_data": "a:42:f"},
            ]
        ]
    }


def test_an_unhandled_incident_states_its_age_from_detection() -> None:
    text, _ = render_alert(
        _incident(trigger=Trigger.INCIDENT_UNHANDLED, detected_at=FIRED - timedelta(minutes=45))
    )
    assert text.splitlines()[0] == "⚠️ مخالفة لم تُعالَج بعد"
    assert "مضى على رصدها 45 دقيقة عند التنبيه" in text


def test_a_silent_group_alert() -> None:
    text, markup = render_alert(_silent())
    assert text.splitlines() == [
        "🔇 لا نشاط مسجَّل في مجموعة",
        "المجموعة: Math 101",
        "آخر نشاط مسجَّل: 2026-11-10 09:30 · منذ يومين و3 ساعات عند التنبيه",
    ]
    assert markup is None


def test_a_bot_standing_alert() -> None:
    text, markup = render_alert(_bot())
    assert text.splitlines() == [
        "🛑 البوت لم يعد مشرفاً في مجموعة",
        "المجموعة: Math 101",
        "حالة البوت: عضو منذ 12:10",
    ]
    assert markup is None


def test_a_repeat_names_its_index() -> None:
    text, _ = render_alert(_question(repeat_index=2, max_repeats=3))
    assert text.splitlines()[0] == "⏳ سؤال ينتظر الرد · تذكير 2 من 3"


@pytest.mark.parametrize(
    ("opener", "word"),
    [("rule", "قاعدة الروابط"), ("ai", "النموذج"), ("operator", "مشغّل اللوحة")],
)
def test_the_opener_words(opener: str, word: str) -> None:
    assert f"فُتحت بواسطة: {word}" in render_alert(_incident(opener=opener))[0]


# --- escaping (§1) ---


def test_titles_names_and_the_excerpt_are_escaped() -> None:
    text, _ = render_alert(
        _question(
            group_title="<b>Math</b> & co",
            anchor_text="is 2 < 3 & <i>true</i>?",
            team=(Person(moderator_id=5, name='Ali <script>"x"', tg_user_id=5),),
        )
    )
    assert "المجموعة: &lt;b&gt;Math&lt;/b&gt; &amp; co" in text
    assert "«is 2 &lt; 3 &amp; &lt;i&gt;true&lt;/i&gt;?»" in text
    assert '<a href="tg://user?id=5">Ali &lt;script&gt;"x"</a>' in text
    assert "<script>" not in text and "<b>" not in text and "<i>" not in text


def test_the_group_title_is_cut_at_80() -> None:
    text, _ = render_alert(_question(group_title="T" * 120))
    title_line = text.splitlines()[1]
    assert title_line == "المجموعة: " + "T" * 79 + "…"


# --- durations (§3) ---


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (30, "أقل من دقيقة"),
        (60, "دقيقة"),
        (120, "دقيقتين"),
        (180, "3 دقائق"),
        (600, "10 دقائق"),
        (660, "11 دقيقة"),
        (59 * 60, "59 دقيقة"),
        (3600, "ساعة"),
        (2 * 3600 + 5 * 60, "ساعتين و5 دقائق"),
        (3600 + 60, "ساعة ودقيقة"),
        (5 * 3600 + 120, "5 ساعات ودقيقتين"),
        (23 * 3600, "23 ساعة"),
        (86400, "يوم"),
        (2 * 86400 + 3 * 3600, "يومين و3 ساعات"),
        (3 * 86400 + 3600, "3 أيام وساعة"),
        (11 * 86400, "11 يوماً"),
    ],
)
def test_every_duration_bucket(seconds: int, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_times_are_riyadh_and_carry_the_date_on_another_day() -> None:
    assert format_time(datetime(2026, 11, 12, 6, 5, tzinfo=UTC), FIRED) == "09:05"
    assert format_time(datetime(2026, 11, 11, 23, 0, tzinfo=UTC), FIRED) == "02:00"
    assert format_time(datetime(2026, 11, 11, 20, 0, tzinfo=UTC), FIRED) == "2026-11-11 23:00"


# --- the excerpt (§2) ---


def test_the_excerpt_is_cut_at_a_word_boundary_with_an_ellipsis() -> None:
    words = " ".join(["word"] * 40)  # 199 characters
    cut = excerpt(words, removed=False, aged_out=False)
    assert cut is not None
    assert cut.endswith("…")
    assert len(cut) <= 101
    assert cut[:-1] == " ".join(["word"] * 20)


def test_an_excerpt_with_no_space_in_range_is_cut_at_100() -> None:
    cut = excerpt("x" * 150, removed=False, aged_out=False)
    assert cut == "x" * 100 + "…"


def test_a_short_text_is_kept_whole() -> None:
    assert excerpt("  When   is the\n exam?  ", removed=False, aged_out=False) == (
        "When is the exam?"
    )


def test_links_emails_handles_and_numbers_are_replaced() -> None:
    cut = excerpt(
        "call 0555123456 or mail me@example.com, see https://x.example/a and @someone",
        removed=False,
        aged_out=False,
    )
    assert cut == "call «رقم» or mail «بريد», see «رابط» and «مستخدم»"


@pytest.mark.parametrize(("removed", "aged_out"), [(True, False), (False, True), (True, True)])
def test_text_not_held(removed: bool, aged_out: bool) -> None:
    assert excerpt("anything", removed=removed, aged_out=aged_out) == TEXT_NOT_HELD
    text, _ = render_alert(_question(text_removed=removed, text_aged_out=aged_out))
    assert TEXT_NOT_HELD in text.splitlines()
    assert "«" + TEXT_NOT_HELD not in text


def test_media_without_text_has_no_excerpt_line() -> None:
    text, _ = render_alert(_question(anchor_text=None))
    assert excerpt(None, removed=False, aged_out=False) is None
    assert text.splitlines()[2].startswith("سُئل الساعة")


# --- links (T7) ---


def test_a_public_group_links_by_username() -> None:
    text, _ = render_alert(_question(chat_username="math101_group"))
    assert '🔗 <a href="https://t.me/math101_group/555">الرسالة</a>' in text


def test_a_supergroup_links_by_its_internal_id() -> None:
    assert "https://t.me/c/1234567890/555" in render_alert(_question())[0]


def test_a_basic_group_has_no_link() -> None:
    text, _ = render_alert(_question(chat_type="group", chat_platform_id=-4567890))
    assert NO_MESSAGE_LINK in text
    assert "t.me" not in text


def test_the_panel_link_is_a_button_when_configured() -> None:
    _, markup = render_alert(_incident(panel_base_url="https://panel.example.org"))
    assert markup is not None
    assert markup["inline_keyboard"][-1] == [
        {"text": "فتح في اللوحة", "url": "https://panel.example.org/admin/incidents/9"}
    ]
    _, markup = render_alert(_question(panel_base_url="https://panel.example.org"))
    assert markup is not None
    assert markup["inline_keyboard"][-1][0]["url"] == (
        "https://panel.example.org/admin/live-attention-queue"
    )
    _, markup = render_alert(_silent(panel_base_url="https://panel.example.org"))
    assert markup == {
        "inline_keyboard": [
            [{"text": "فتح في اللوحة", "url": "https://panel.example.org/admin/telegram-chats/3/edit"}]
        ]
    }


def test_no_panel_link_without_a_base_url() -> None:
    _, markup = render_alert(_incident())
    assert markup is not None
    assert all("url" not in button for row in markup["inline_keyboard"] for button in row)


# --- responsibility ---


def test_the_assignee_and_how_they_took_it() -> None:
    text, _ = render_alert(_question(assignee=SARA, assigned_via="alert"))
    assert 'المسؤول: <a href="tg://user?id=111">Sara</a> · من التنبيه' in text
    assert "🙋 يتولّاه Sara" in text  # a taken question stays open, with its keyboard
    assert render_alert(_question(assignee=SARA, assigned_via="alert"))[1] is not None


@pytest.mark.parametrize(
    ("via", "word"),
    [
        ("reply", "بالرد"),
        ("dismissal", "بالاستبعاد"),
        ("reaction", "بالتفاعل"),
        ("alert", "من التنبيه"),
    ],
)
def test_the_item_via_words(via: str, word: str) -> None:
    assert f"· {word}" in render_alert(_question(assignee=SARA, assigned_via=via))[0]


def test_no_team_and_not_taken() -> None:
    assert "بلا فريق" in render_alert(_question(team=()))[0]
    ended = _question(
        status="expired", end=SubjectEnd(kind="expired", at=FIRED + timedelta(hours=20))
    )
    assert "لم يتولّه أحد من الفريق" in render_alert(ended)[0]


def test_health_alerts_name_nobody() -> None:
    for data in (_silent(team=(SARA,)), _bot(team=(SARA,))):
        assert "tg://user" not in render_alert(data)[0]


# --- status lines (§6) ---

LATER = FIRED + timedelta(minutes=10)  # 12:40 in Riyadh


@pytest.mark.parametrize(
    ("data", "line"),
    [
        (
            _question(status="answered", end=SubjectEnd(kind="answered_moderator", at=LATER,
                                                         actor=OMAR)),
            "✅ أُجيب عنه — Omar الساعة 12:40",
        ),
        (
            _question(status="answered", end=SubjectEnd(kind="answered_member", at=LATER)),
            "✅ أجاب عنه عضو الساعة 12:40",
        ),
        (
            _question(status="dismissed", end=SubjectEnd(kind="dismissed", at=LATER, actor=OMAR,
                                                         actor_kind="moderator")),
            "استُبعد — Omar الساعة 12:40",
        ),
        (
            _question(status="dismissed", end=SubjectEnd(kind="dismissed", at=LATER,
                                                         actor_kind="panel_user")),
            "استُبعد — مشغّل اللوحة الساعة 12:40",
        ),
        (
            _question(status="expired", end=SubjectEnd(kind="expired", at=LATER)),
            "انتهت مهلته الساعة 12:40 دون رد",
        ),
        (
            _incident(status="resolved", end=SubjectEnd(kind="resolved", at=LATER, actor=SARA,
                                                        actor_kind="moderator", how="ban")),
            "✅ عولجت — Sara · بحظر العضو الساعة 12:40",
        ),
        (
            _incident(status="resolved", end=SubjectEnd(kind="resolved", at=LATER, actor=SARA,
                                                        actor_kind="moderator",
                                                        how="alert_handled")),
            "✅ عولجت — Sara · من التنبيه الساعة 12:40",
        ),
        (
            _incident(status="resolved", end=SubjectEnd(kind="resolved", at=LATER,
                                                        actor_kind="anonymous", how="restriction")),
            "✅ عولجت — مسؤول مجهول الهوية · بتقييده الساعة 12:40",
        ),
        (
            # A group administrator who is not a declared moderator is never named (W4).
            _incident(status="resolved", end=SubjectEnd(kind="resolved", at=LATER,
                                                        actor_kind="administrator", how="ban")),
            "✅ عولجت — مسؤول · بحظر العضو الساعة 12:40",
        ),
        (
            _incident(status="closed_false_positive",
                      end=SubjectEnd(kind="false_positive", at=LATER, actor_kind="panel_user")),
            "🚫 ليست مخالفة — مشغّل اللوحة الساعة 12:40",
        ),
        (
            _silent(status="ended", end=SubjectEnd(kind="resumed", at=LATER)),
            "عاد النشاط الساعة 12:40",
        ),
        (
            _bot(status="ended", end=SubjectEnd(kind="standing_changed", at=LATER,
                                                new_status="administrator")),
            "تغيّرت حالة البوت الساعة 12:40: مسؤول",
        ),
    ],
)
def test_each_status_line_and_no_keyboard_once_ended(data: RenderInput, line: str) -> None:
    text, markup = render_alert(replace(data, panel_base_url="https://panel.example.org"))
    assert text.splitlines()[-1] == line
    assert markup is None


@pytest.mark.parametrize(
    ("how", "word"),
    [
        ("ban", "بحظر العضو"),
        ("expulsion", "بطرده"),
        ("restriction", "بتقييده"),
        ("reaction", "بتفاعل 👀"),
        ("panel_resolve", "من اللوحة"),
        ("alert_handled", "من التنبيه"),
    ],
)
def test_every_how(how: str, word: str) -> None:
    data = _incident(
        status="resolved",
        end=SubjectEnd(kind="resolved", at=LATER, actor=SARA, actor_kind="moderator", how=how),
    )
    assert f"· {word} الساعة" in render_alert(data)[0]


# --- the bound (§1) ---


def test_the_longest_alert_stays_within_1000_characters() -> None:
    crowd = tuple(Person(moderator_id=i, name="N" * 200, tg_user_id=i) for i in range(30))
    data = _incident(
        trigger=Trigger.INCIDENT_UNHANDLED,
        group_title="G" * 300,
        anchor_text="word " * 400,
        team=crowd,
        repeat_index=9,
        max_repeats=10,
        panel_base_url="https://panel.example.org",
    )
    text, _ = render_alert(data)
    assert visible_length(text) <= 1000


# --- render state (U1) ---


def test_render_state_holds_no_text() -> None:
    state = render_state(_question())
    flat = repr(state)
    assert "When is the exam" not in flat
    assert state["excerpt"] is True
    assert render_state(_question(text_aged_out=True))["excerpt"] is False
    assert render_state(_question(anchor_text=None))["excerpt"] is False


def test_render_state_changes_only_with_its_inputs() -> None:
    base = render_state(_question())
    # An unchanged subject renders the same state, whatever the fired-at ages say.
    assert render_state(_question(team=(SARA,))) == base
    assert render_state(_question(assignee=SARA, assigned_via="alert")) != base
    assert render_state(
        _question(status="expired", end=SubjectEnd(kind="expired", at=LATER))
    ) != base
    assert render_state(_question(text_aged_out=True)) != base


# --- answers (§5) ---


@pytest.mark.parametrize(
    ("outcome", "kwargs", "expected"),
    [
        (PressOutcome.RECORDED, {"action": PressAction.HANDLED}, "تم: عولجت المخالفة"),
        (PressOutcome.RECORDED, {"action": PressAction.FALSE_POSITIVE}, "تم: أُغلقت كرصد خاطئ"),
        (PressOutcome.RECORDED, {"action": PressAction.TAKE}, "تم: السؤال لك"),
        (PressOutcome.RECORDED_NOT_TEAM, {}, "سُجّل. لست في فريق هذه المجموعة، فلا يُسند إليك"),
        (PressOutcome.ALREADY_TAKEN, {"assignee_name": "Sara"}, "سُجّل. يتولّاه Sara"),
        (PressOutcome.ALREADY_ENDED, {"ended_status": "resolved"}, "انتهى هذا البند: عولجت"),
        (PressOutcome.ALREADY_ENDED, {"ended_status": "answered"}, "انتهى هذا البند: أُجيب عنه"),
        (PressOutcome.NOT_A_MODERATOR, {}, "هذه الأزرار للمشرفين المعتمدين فقط"),
        (PressOutcome.INVALID, {}, "هذا الزر لم يعد صالحاً"),
    ],
)
def test_every_answer(outcome: PressOutcome, kwargs: dict[str, object], expected: str) -> None:
    text = answer_text(outcome, **kwargs)  # type: ignore[arg-type]
    assert text == expected
    assert len(text) <= 200


# --- never (§7) ---

_DELETION_WORDS = ("حذف", "حُذف", "حذفت", "حُذفت", "أزال", "أُزيل", "إزالة", "مسح", "مُسح")
_CONFIDENCE_WORDS = ("ثقة", "%", "٪", "احتمال", "نسبة", "مؤكد", "تأكد", "ثبت")


def _every_rendering() -> list[str]:
    ends = [
        None,
        SubjectEnd(kind="answered_moderator", at=LATER, actor=OMAR),
        SubjectEnd(kind="answered_member", at=LATER),
        SubjectEnd(kind="dismissed", at=LATER, actor_kind="panel_user"),
        SubjectEnd(kind="expired", at=LATER),
        SubjectEnd(kind="resolved", at=LATER, actor=SARA, actor_kind="moderator", how="ban"),
        SubjectEnd(kind="resolved", at=LATER, actor_kind="anonymous", how="expulsion"),
        SubjectEnd(kind="false_positive", at=LATER, actor=SARA, actor_kind="moderator"),
        SubjectEnd(kind="resumed", at=LATER),
        SubjectEnd(kind="standing_changed", at=LATER, new_status="kicked"),
    ]
    builders = [
        _question,
        _incident,
        lambda **kw: _incident(trigger=Trigger.INCIDENT_UNHANDLED, **kw),
        _silent,
        _bot,
    ]
    texts: list[str] = []
    for build, end, held in product(builders, ends, (True, False)):
        data = build(end=end, text_aged_out=not held, panel_base_url="https://p.example.org")
        text, markup = render_alert(data)
        texts.append(text)
        texts.extend(
            button["text"] for row in (markup or {}).get("inline_keyboard", []) for button in row
        )
    texts.extend(
        answer_text(outcome, action=action, assignee_name="Sara", ended_status=status)
        for outcome, action, status in product(
            PressOutcome, PressAction, ("answered", "dismissed", "expired", "resolved",
                                        "closed_false_positive")
        )
    )
    return texts


def test_w1_no_deletion_or_removal_word_anywhere() -> None:
    for text in _every_rendering():
        for word in _DELETION_WORDS:
            assert word not in text, f"{word!r} in {text!r}"


def test_w2_w3_no_confidence_percentage_probability_or_proof_word() -> None:
    for text in _every_rendering():
        for word in _CONFIDENCE_WORDS:
            assert word not in text, f"{word!r} in {text!r}"


def test_w4_only_moderators_are_mentioned() -> None:
    mentioned_ids = set()
    for text in _every_rendering():
        mentioned_ids |= {int(i) for i in re.findall(r"tg://user\?id=(\d+)", text)}
        assert STUDENT_NAME not in text
        assert STUDENT_USERNAME not in text
        assert str(STUDENT_TG_ID) not in text
    assert mentioned_ids <= {SARA.tg_user_id, OMAR.tg_user_id}
