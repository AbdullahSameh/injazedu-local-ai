"""Quiet hours (R7, F5, FR-543, D-TG-223): `[from, to)` windows in `Asia/Riyadh`, crossing midnight
when `to < from`, and a parser that skips anything malformed.

The pure cases are T510's. The integration cases (T523, US1) drive the evaluator and delivery: a
firing inside a window is `suppressed`, never claimed and never sent; it keeps its index, so a
repeat due after the window is sent; and no item changes. A test cannot move the clock, so
"after the window" is the same window shape placed so that the current instant falls outside it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.moderation.alert_delivery import DeliveryOutcome, deliver
from app.application.moderation.alerting import RenderSettings
from app.domain.moderation.alerting import QuietWindow, in_quiet_hours, parse_quiet_hours

from tests.moderation.alerts.conftest import Chat, ScriptedTelegram

RIYADH = timezone(timedelta(hours=3))


def _riyadh(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 12, hour, minute, tzinfo=RIYADH)


NIGHT = (QuietWindow(start=time(22, 0), end=time(7, 0)),)
LUNCH = (QuietWindow(start=time(12, 0), end=time(13, 30)),)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (21, 59, False),
        (22, 0, True),  # `from` is inside
        (23, 59, True),
        (0, 0, True),  # across midnight
        (6, 59, True),
        (7, 0, False),  # `to` is outside
        (12, 0, False),
    ],
)
def test_a_window_crossing_midnight(hour: int, minute: int, expected: bool) -> None:
    assert in_quiet_hours(NIGHT, _riyadh(hour, minute)) is expected


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(11, 59, False), (12, 0, True), (13, 29, True), (13, 30, False)],
)
def test_a_window_within_one_day(hour: int, minute: int, expected: bool) -> None:
    assert in_quiet_hours(LUNCH, _riyadh(hour, minute)) is expected


def test_the_instant_is_judged_in_riyadh_whatever_its_offset() -> None:
    # 19:30 UTC is 22:30 in Riyadh: inside the night window.
    assert in_quiet_hours(NIGHT, datetime(2026, 11, 12, 19, 30, tzinfo=UTC)) is True
    # 03:30 UTC is 06:30 in Riyadh: still inside.
    assert in_quiet_hours(NIGHT, datetime(2026, 11, 12, 3, 30, tzinfo=UTC)) is True
    # 04:00 UTC is 07:00 in Riyadh: outside.
    assert in_quiet_hours(NIGHT, datetime(2026, 11, 12, 4, 0, tzinfo=UTC)) is False


def test_any_of_several_windows_counts() -> None:
    both = NIGHT + LUNCH
    assert in_quiet_hours(both, _riyadh(12, 15)) is True
    assert in_quiet_hours(both, _riyadh(23, 0)) is True
    assert in_quiet_hours(both, _riyadh(15, 0)) is False


def test_no_windows_is_never_quiet() -> None:
    assert in_quiet_hours((), _riyadh(3, 0)) is False


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError):
        in_quiet_hours(NIGHT, datetime(2026, 11, 12, 23, 0))


def test_the_parser_reads_well_formed_windows() -> None:
    windows, skipped = parse_quiet_hours(
        [{"from": "22:00", "to": "07:00"}, {"from": "12:00", "to": "13:30"}]
    )
    assert windows == NIGHT + LUNCH
    assert skipped == 0


def test_the_parser_skips_each_malformed_window() -> None:
    windows, skipped = parse_quiet_hours(
        [
            {"from": "22:00", "to": "22:00"},  # from == to
            {"from": "24:00", "to": "07:00"},
            {"from": "7:00", "to": "08:00"},
            {"from": "22:00"},
            {"to": "07:00"},
            "22:00-07:00",
            {"from": 22, "to": 7},
            {"from": "12:00", "to": "13:30"},
        ]
    )
    assert windows == LUNCH
    assert skipped == 7


@pytest.mark.parametrize(("raw", "skipped"), [(None, 0), ([], 0), ({"from": "22:00"}, 1)])
def test_the_parser_on_a_non_list(raw: object, skipped: int) -> None:
    assert parse_quiet_hours(raw) == ((), skipped)


# --- integration (T523) ---

SETTINGS = RenderSettings(panel_base_url=None, retention_days=90)


def _hhmm(instant: datetime) -> str:
    return instant.astimezone(RIYADH).strftime("%H:%M")


def _window_around(now: datetime) -> list[dict[str, str]]:
    """A window that contains `now` and crosses midnight, whatever the hour: in the afternoon
    and evening it starts an hour before `now` and ends at 06:00; in the morning it starts at
    18:00 and ends an hour after `now`."""
    local = now.astimezone(RIYADH)
    if local.hour >= 12:
        return [{"from": _hhmm(now - timedelta(hours=1)), "to": "06:00"}]
    return [{"from": "18:00", "to": _hhmm(now + timedelta(hours=1))}]


def _window_excluding(now: datetime) -> list[dict[str, str]]:
    """The same shape, placed so that `now` falls in its one open hour."""
    return [{"from": _hhmm(now + timedelta(minutes=30)), "to": _hhmm(now - timedelta(minutes=30))}]


async def _item_row(session_factory: Any, item_id: int) -> tuple[Any, ...]:
    async with session_factory() as session:
        return tuple(
            (
                await session.execute(
                    sa.text("SELECT * FROM attention_items WHERE id = :id"), {"id": item_id}
                )
            ).one()
        )


async def test_a_firing_inside_a_window_across_midnight_is_suppressed_and_never_sent(
    alert_session_factory, make_rule, insert_item, evaluate, fetch_alerts,
    scripted_telegram: ScriptedTelegram, destination_chat: Chat, source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    window = _window_around(now)
    assert window[0]["to"] < window[0]["from"]  # it crosses midnight
    await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        quiet_hours=window,
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(minutes=30))
    before = await _item_row(alert_session_factory, item_id)

    result = await evaluate()
    [alert] = await fetch_alerts("attention_item", item_id)
    outcome = await deliver(alert_session_factory, scripted_telegram.client, alert["id"], SETTINGS)

    assert alert["delivery_status"] == "suppressed"
    assert alert["id"] in result.suppressed
    assert alert["id"] not in result.to_deliver
    assert outcome is DeliveryOutcome.NOT_CLAIMED
    assert scripted_telegram.calls == []
    assert (await fetch_alerts("attention_item", item_id))[0]["attempts"] == 0
    assert await _item_row(alert_session_factory, item_id) == before


async def test_a_repeat_due_after_the_window_is_sent(
    alert_session_factory, make_rule, insert_item, evaluate, fetch_alerts,
    scripted_telegram: ScriptedTelegram, destination_chat: Chat, source_chat: Chat, db_now,
) -> None:
    now: datetime = await db_now()
    rule_id = await make_rule(
        trigger="question_waiting",
        telegram_chat_id=source_chat.id,
        threshold_s=600,
        repeat_every_s=600,
        max_repeats=3,
        quiet_hours=_window_around(now),
    )
    item_id = await insert_item(source_chat, opened_at=now - timedelta(hours=1))
    before = await _item_row(alert_session_factory, item_id)
    await evaluate()  # index 0, suppressed

    # Time passes: one interval since the first firing, and the instant now outside the window.
    async with alert_session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE alerts SET fired_at = fired_at - interval '600 seconds' "
                "WHERE subject_type = 'attention_item' AND subject_id = :id"
            ),
            {"id": item_id},
        )
        await session.execute(
            sa.text("UPDATE alert_rules SET quiet_hours = CAST(:w AS jsonb) WHERE id = :id"),
            {"w": json.dumps(_window_excluding(now)), "id": rule_id},
        )
        await session.commit()
    result = await evaluate()

    first, repeat = await fetch_alerts("attention_item", item_id)
    assert (first["repeat_index"], first["delivery_status"]) == (0, "suppressed")
    assert (repeat["repeat_index"], repeat["delivery_status"]) == (1, "pending")
    assert result.to_deliver.count(repeat["id"]) == 1

    outcome = await deliver(
        alert_session_factory, scripted_telegram.client, repeat["id"], SETTINGS
    )
    assert outcome is DeliveryOutcome.SENT
    [sent] = scripted_telegram.calls_to("sendMessage")
    assert sent["chat_id"] == destination_chat.chat_id
    assert "تذكير 1 من 3" in sent["text"]
    assert await _item_row(alert_session_factory, item_id) == before
