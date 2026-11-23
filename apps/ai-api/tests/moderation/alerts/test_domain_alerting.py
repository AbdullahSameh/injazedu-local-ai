"""`app/domain/moderation/alerting.py` (T510): the repeat index, the dedupe key, callback data, the
severity order and the enums. Pure: no database, no clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.domain.moderation.alerting import (
    ACT_KIND,
    ACTIONS_FOR,
    DEDUPE_KEY_MAX,
    SUBJECT_OF,
    PressAction,
    PressOutcome,
    SubjectType,
    Trigger,
    decode_callback,
    dedupe_key,
    due_repeat_index,
    encode_callback,
    episode_token,
    severity_at_least,
)

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


# --- enums ---


def test_the_five_triggers_and_their_subjects() -> None:
    assert {t.value for t in Trigger} == {
        "question_waiting",
        "incident_flagged",
        "incident_unhandled",
        "group_silent",
        "bot_not_admin",
    }
    assert SUBJECT_OF[Trigger.QUESTION_WAITING] is SubjectType.ATTENTION_ITEM
    assert SUBJECT_OF[Trigger.INCIDENT_FLAGGED] is SubjectType.INCIDENT
    assert SUBJECT_OF[Trigger.INCIDENT_UNHANDLED] is SubjectType.INCIDENT
    assert SUBJECT_OF[Trigger.GROUP_SILENT] is SubjectType.CHAT
    assert SUBJECT_OF[Trigger.BOT_NOT_ADMIN] is SubjectType.CHAT


def test_the_six_press_outcomes() -> None:
    assert {o.value for o in PressOutcome} == {
        "recorded",
        "recorded_not_team",
        "already_taken",
        "already_ended",
        "not_a_moderator",
        "invalid",
    }


def test_which_actions_fit_which_subject() -> None:
    assert ACTIONS_FOR[SubjectType.INCIDENT] == {PressAction.HANDLED, PressAction.FALSE_POSITIVE}
    assert ACTIONS_FOR[SubjectType.ATTENTION_ITEM] == {PressAction.TAKE}
    assert ACTIONS_FOR[SubjectType.CHAT] == frozenset()
    assert ACT_KIND == {
        PressAction.HANDLED: "alert_handled",
        PressAction.FALSE_POSITIVE: "alert_false_positive",
        PressAction.TAKE: "alert_take",
    }


# --- repeats (F3) ---


@pytest.mark.parametrize(
    ("elapsed_s", "expected"),
    [
        (-5, 0),
        (0, 0),
        (599, 0),
        (600, 1),
        (1199, 1),
        (1200, 2),
        (1800, 3),
        (6000, 3),  # capped at max
    ],
)
def test_the_due_repeat_index(elapsed_s: int, expected: int) -> None:
    now = T0 + timedelta(seconds=elapsed_s)
    assert due_repeat_index(T0, now, 600, 3) == expected


def test_after_an_outage_the_due_index_jumps_and_is_never_back_filled() -> None:
    # Three intervals missed: the index due now is 3, not 1, 2, 3 in turn.
    assert due_repeat_index(T0, T0 + timedelta(seconds=3 * 600 + 5), 600, 5) == 3


@pytest.mark.parametrize(("every_s", "max_repeats"), [(None, None), (600, None), (None, 3)])
def test_a_rule_without_repeats_is_always_index_0(
    every_s: int | None, max_repeats: int | None
) -> None:
    assert due_repeat_index(T0, T0 + timedelta(days=3), every_s, max_repeats) == 0


# --- dedupe key ---


def test_the_dedupe_key_shape() -> None:
    assert dedupe_key(7, SubjectType.ATTENTION_ITEM, 42, None, 0) == "7:attention_item:42:0"
    assert dedupe_key(7, "incident", 9, None, 2) == "7:incident:9:2"


def test_a_health_key_carries_its_episode_exactly() -> None:
    episode = datetime(2026, 11, 12, 9, 0, 0, 123456, tzinfo=UTC)
    key = dedupe_key(3, SubjectType.CHAT, 5, episode, 0)
    assert key == f"3:chat:5@{episode_token(episode)}:0"
    assert episode_token(episode) == 1_794_474_000_123_456
    # A later episode, even a microsecond later, is a different key.
    assert dedupe_key(3, SubjectType.CHAT, 5, episode + timedelta(microseconds=1), 0) != key


def test_the_largest_key_fits_the_column() -> None:
    key = dedupe_key(
        9_223_372_036_854_775_807,
        SubjectType.ATTENTION_ITEM,
        9_223_372_036_854_775_807,
        datetime(9999, 12, 31, tzinfo=UTC),
        32_767,
    )
    assert len(key) <= DEDUPE_KEY_MAX


def test_an_unknown_subject_type_is_refused() -> None:
    with pytest.raises(ValueError):
        dedupe_key(1, "user", 1, None, 0)


# --- callback data (B1, T2) ---


@pytest.mark.parametrize("action", list(PressAction))
def test_callback_data_round_trips(action: PressAction) -> None:
    data = encode_callback(1234, action)
    assert data == f"a:1234:{action.value}"
    assert decode_callback(data) == (1234, action)
    assert len(data.encode()) <= 64


@pytest.mark.parametrize(
    "data",
    [
        None,
        "",
        "a:1234",
        "a:1234:x",
        "a:0:h",
        "a:-1:h",
        "a:01:h",
        "b:1234:h",
        "a:1234:h ",
        " a:1234:h",
        "a:1234:hh",
        "a:1234:h:extra",
        "a:١٢٣:h",
        "a:" + "9" * 19 + ":h",
        123,
    ],
)
def test_anything_else_is_rejected(data: object) -> None:
    assert decode_callback(data) is None


def test_encode_refuses_a_non_positive_id() -> None:
    with pytest.raises(ValueError):
        encode_callback(0, PressAction.TAKE)


# --- severity (R4) ---


@pytest.mark.parametrize(
    ("severity", "minimum", "expected"),
    [
        ("low", None, True),
        ("low", "low", True),
        ("low", "medium", False),
        ("medium", "medium", True),
        ("high", "medium", True),
        ("medium", "high", False),
        ("high", "high", True),
        ("urgent", "low", False),
        ("low", "urgent", False),
    ],
)
def test_severity_at_least(severity: str, minimum: str | None, expected: bool) -> None:
    assert severity_at_least(severity, minimum) is expected
