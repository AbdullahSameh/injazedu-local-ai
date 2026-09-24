"""Burst assembly, item opening, and response matching — the one matcher, two entry points
(`contracts/attention-rules.md` §1, §2, §4, §4.1, tasks T026-T027, T042-T047).

`assemble_burst` reads `telegram_messages` and reconstructs the cluster of one sender's messages
in one thread that settles around a given instant (D-TG-79). `open_item` evaluates that burst
through `app.domain.moderation.attention.evaluate` — the same predicate for the fast, delayed
path (`app/workers/tasks/moderation/evaluate_attention.py`) and for the sweep — and performs the
one insert-only write (D-TG-72, D-TG-80).

`match_response` (the live path, no delay) and `match_existing_responses` (the open-time
lookback, C10) both close items through the same three functions — `_response_predicate`,
`_oldest_open_item_before` and `close_item` — so what closes an item is decided in exactly one
place regardless of which direction found the message (D-TG-82).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.moderation.assignments import responsible_at
from app.application.moderation.locks import chat_lock
from app.domain.moderation.attention import RULE_VERSION, evaluate
from app.infrastructure.models_moderation import (
    attention_items,
    moderators,
    telegram_chats,
    telegram_messages,
    telegram_users,
)

# A moderator mention is resolved against a stored `@handle`, never against the boolean
# `entity_flags.has_mention` alone — that flag only says *something* was mentioned, not whom
# (D-TG-77). Mirrors `app.application.moderation.text`'s private `_HANDLE_RE` shape.
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{3,})")


async def assemble_burst(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    message_thread_id: int | None,
    around: datetime,
    gap_s: int,
) -> list[sa.RowMapping]:
    """Reconstructs the burst (contract §1) sharing `(telegram_chat_id, telegram_user_id,
    message_thread_id)` that the instant `around` falls inside — every stored message for that
    key, partitioned wherever two consecutive members (by `sent_at`) are more than `gap_s` apart,
    keeping only the partition containing `around`.

    `message_thread_id` is compared `IS NOT DISTINCT FROM`, never `=` (FR-002): no thread is
    itself a distinct thread value that matches only other messages with no thread. Recomputed
    from the database on every call — never cached — which is what makes repeated judgement
    converge on the same anchor (B1, B2, D-TG-79, D-TG-80).

    Returns the burst ordered by `(sent_at, message_id)` ascending — its first element is the
    anchor (FR-005) — or `[]` when nothing is stored for that key.
    """
    rows = (
        (
            await session.execute(
                sa.select(telegram_messages)
                .where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.telegram_user_id == telegram_user_id,
                    sa.not_(
                        telegram_messages.c.message_thread_id.is_distinct_from(message_thread_id)
                    ),
                )
                .order_by(telegram_messages.c.sent_at, telegram_messages.c.message_id)
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return []

    cluster: list[sa.RowMapping] = [rows[0]]
    for previous, row in zip(rows, rows[1:], strict=False):
        gap = (row["sent_at"] - previous["sent_at"]).total_seconds()
        if gap <= gap_s:
            cluster.append(row)
            continue
        if cluster[0]["sent_at"] <= around <= cluster[-1]["sent_at"]:
            return cluster
        cluster = [row]

    if cluster[0]["sent_at"] <= around <= cluster[-1]["sent_at"]:
        return cluster
    return []


async def _sender_is_moderator_or_bot(
    session: AsyncSession, *, telegram_user_id: int, is_from_moderator: bool
) -> bool:
    """Condition 1 (contract §2.2): a moderator at send time, or a bot. `is_from_moderator` is
    TG-M2's write-once flag, resolved once at insert; `is_bot` is looked up from `telegram_users`
    since it is not denormalised onto the message row."""
    if is_from_moderator:
        return True
    result = await session.execute(
        sa.select(telegram_users.c.is_bot).where(telegram_users.c.id == telegram_user_id)
    )
    return bool(result.scalar_one_or_none())


async def _replies_to_moderator(
    session: AsyncSession, *, telegram_chat_id: int, burst: Sequence[sa.RowMapping]
) -> bool:
    """Condition 6, first half: whether any burst member directly replies to a message whose
    `is_from_moderator` is true — resolvable from TG-M2's stored facts alone (D-TG-77)."""
    reply_ids = {
        row["reply_to_message_id"] for row in burst if row["reply_to_message_id"] is not None
    }
    if not reply_ids:
        return False
    result = await session.execute(
        sa.select(sa.literal(True))
        .select_from(telegram_messages)
        .where(
            telegram_messages.c.telegram_chat_id == telegram_chat_id,
            telegram_messages.c.message_id.in_(reply_ids),
            telegram_messages.c.is_from_moderator.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _mentions_moderator(
    session: AsyncSession, *, burst: Sequence[sa.RowMapping]
) -> bool:
    """Condition 6, second half: whether any burst member's text `@`-mentions a mapped
    moderator's username (D-TG-77)."""
    handles: set[str] = set()
    for row in burst:
        original_text = row.get("original_text")
        if original_text:
            handles.update(match.lower() for match in _MENTION_RE.findall(original_text))
    if not handles:
        return False
    moderator_identities = moderators.join(
        telegram_users, moderators.c.telegram_user_id == telegram_users.c.id
    )
    result = await session.execute(
        sa.select(sa.literal(True))
        .select_from(moderator_identities)
        .where(sa.func.lower(telegram_users.c.username).in_(handles))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def open_item(session: AsyncSession, burst: Sequence[sa.RowMapping]) -> int | None:
    """Judges `burst` and opens an item when the rules say so — the fast path
    (`evaluate_attention`), the sweep (`sweep_unjudged_bursts`) and the open-time lookback all
    call this over whatever burst `assemble_burst` hands back, so there is exactly one place this
    decision is made (contract §4.1, D-TG-82).

    Holds `chat_lock` for the duration (C11, D-TG-81). Every burst member gets
    `attention_evaluated_at` set, whether or not an item resulted, and `attention_item_id` set
    only when one did (B3, D-TG-72).

    **E2/E4**: if any burst member already carries an `attention_item_id`, an item already covers
    this burst — waiting, answered, dismissed or expired — so no rule is evaluated and no insert
    is attempted; this run converges on that item. This is what makes an edit's re-judgement (E5
    clears `attention_evaluated_at` on the edited message alone, leaving the rest of the burst's
    `attention_item_id` untouched) safe to run through this same function: it can never reopen,
    retract or re-date an item that already exists.

    **E3**: when no item exists yet and the rules now say to open one, the item anchors on the
    burst's earliest member (`sent_at`) as usual — *unless* some member has been edited
    (`edited_at IS NOT NULL`), in which case it anchors on the most recently edited member with
    `opened_at` taken from that edit's own timestamp, never from `sent_at` (contract §3, D-TG-88).
    The pre-edit text is never consulted for this decision (E1) — the signal is only ever
    "has this message ever been edited", which is available without it.

    Inserts with `ON CONFLICT (telegram_chat_id, telegram_message_id) DO NOTHING RETURNING id` —
    never `DO UPDATE` — so a concurrent or repeated judgement converges on one row (B1, D-TG-80).

    Returns the item's id, or `None` when the burst is empty, the chat is not (or is no longer)
    `is_monitored`, or the rules decline. An unmeasured chat still gets `attention_evaluated_at`
    stamped on every burst member, so the sweep does not revisit it forever (T023, D-TG-72).
    """
    if not burst:
        return None

    earliest = burst[0]
    telegram_chat_id = earliest["telegram_chat_id"]
    member_ids = [row["id"] for row in burst]

    async with chat_lock(session, telegram_chat_id):
        item_id: int | None = next(
            (row["attention_item_id"] for row in burst if row["attention_item_id"] is not None),
            None,
        )

        if item_id is None:
            is_monitored = (
                await session.execute(
                    sa.select(telegram_chats.c.is_monitored).where(
                        telegram_chats.c.id == telegram_chat_id
                    )
                )
            ).scalar_one()
            sender_excluded = await _sender_is_moderator_or_bot(
                session,
                telegram_user_id=earliest["telegram_user_id"],
                is_from_moderator=earliest["is_from_moderator"],
            )
            has_service_message = any(row["is_service"] for row in burst)

            opens = False
            if is_monitored and not sender_excluded and not has_service_message:
                replies_to_moderator = await _replies_to_moderator(
                    session, telegram_chat_id=telegram_chat_id, burst=burst
                )
                mentions_moderator = await _mentions_moderator(session, burst=burst)
                texts = [row["normalized_text"] for row in burst]
                opens = evaluate(
                    texts,
                    mentions_moderator=mentions_moderator,
                    replies_to_moderator=replies_to_moderator,
                )

            if opens:
                edited_members = [row for row in burst if row["edited_at"] is not None]
                if edited_members:
                    anchor = max(
                        edited_members, key=lambda row: (row["edited_at"], row["message_id"])
                    )
                    opened_at = anchor["edited_at"]
                else:
                    anchor = earliest
                    opened_at = anchor["sent_at"]

                responsible_moderator_id = await responsible_at(
                    session, telegram_chat_id=telegram_chat_id, t=opened_at
                )
                insert_stmt = (
                    pg_insert(attention_items)
                    .values(
                        telegram_chat_id=telegram_chat_id,
                        telegram_message_id=anchor["message_id"],
                        message_thread_id=anchor["message_thread_id"],
                        opened_at=opened_at,
                        source="rule",
                        rule_version=RULE_VERSION,
                        responsible_moderator_id=responsible_moderator_id,
                    )
                    .on_conflict_do_nothing(constraint="uq_attention_anchor")
                    .returning(attention_items.c.id)
                )
                item_id = (await session.execute(insert_stmt)).scalar_one_or_none()
                if item_id is None:
                    # A concurrent or repeated run already opened this anchor (B1) — the burst's
                    # members still need stamping below, against the row that already exists.
                    item_id = (
                        await session.execute(
                            sa.select(attention_items.c.id).where(
                                attention_items.c.telegram_chat_id == telegram_chat_id,
                                attention_items.c.telegram_message_id == anchor["message_id"],
                            )
                        )
                    ).scalar_one()

        # Two statements, not one conditional value: `attention_item_id` is only ever set, never
        # cleared, by this function — a burst that has already opened an item must never have
        # that link severed by a later, otherwise-declining re-run over the same anchor.
        values: dict[str, Any] = {"attention_evaluated_at": sa.func.now()}
        if item_id is not None:
            values["attention_item_id"] = item_id
        await session.execute(
            telegram_messages.update().where(telegram_messages.c.id.in_(member_ids)).values(**values)
        )

        if item_id is not None:
            # Contract §4.1 C10: a moderator can answer inside the settle window, before this
            # item existed. Opening it immediately evaluates whatever qualifying messages are
            # already stored after `opened_at`, through the same matcher live traffic uses
            # (D-TG-82) — still inside `chat_lock`, sharing C11's transaction scope. Runs after
            # `attention_item_id` is stamped above, since rule (a) here resolves against this
            # item's own burst members. Re-run harmlessly whenever this burst already has an item
            # (E4) — `close_item`'s guard makes it a no-op once the item is no longer open.
            # `opened_at` is read back from the item itself rather than assumed from the burst,
            # since an edit-anchored item's `opened_at` is not any burst member's `sent_at`.
            item_opened_at = (
                await session.execute(
                    sa.select(attention_items.c.opened_at).where(attention_items.c.id == item_id)
                )
            ).scalar_one()
            await match_existing_responses(
                session,
                {
                    "id": item_id,
                    "telegram_chat_id": telegram_chat_id,
                    "opened_at": item_opened_at,
                    "message_thread_id": earliest["message_thread_id"],
                },
            )

    return item_id


def _response_predicate(item: Mapping[str, Any], message: Mapping[str, Any]) -> bool:
    """The single expression of `contracts/attention-rules.md` §4 (T042): whether `message` may
    close `item` at all, evaluated before either resolution rule is trusted. `is_from_moderator`
    is read exactly as stored at insert (TG-M2's write-once rule) — which already means the
    sender was not a bot, since `derive_message` never sets it `True` for one — so no separate
    bot check is needed here (C6). Everything else in this module delegates to this function
    rather than re-expressing any part of it.
    """
    return (
        message["telegram_chat_id"] == item["telegram_chat_id"]
        and bool(message["is_from_moderator"])
        and message["sent_at"] > item["opened_at"]
    )


async def _oldest_open_item_before(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    message_thread_id: int | None,
    sent_at: datetime,
) -> sa.RowMapping | None:
    """Rule (b)'s candidate (contract §4, C3): the oldest open item in this chat and thread whose
    `opened_at` the given instant strictly follows, tie-broken by the anchor's own
    `telegram_message_id` — both properties of the item itself, from Telegram, so a
    re-derivation reaches the same answer as live traffic (C9, T047). Shared by
    `match_response`'s live resolution and `match_existing_responses`' lookback, so "the oldest"
    means the same thing in both directions — the mechanism that keeps C3 true across both entry
    points.
    """
    return (
        (
            await session.execute(
                sa.select(attention_items)
                .where(
                    attention_items.c.telegram_chat_id == telegram_chat_id,
                    sa.not_(
                        attention_items.c.message_thread_id.is_distinct_from(message_thread_id)
                    ),
                    attention_items.c.status == "open",
                    attention_items.c.opened_at < sent_at,
                )
                .order_by(
                    attention_items.c.opened_at.asc(),
                    attention_items.c.telegram_message_id.asc(),
                )
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )


async def close_item(
    session: AsyncSession, item_id: int, message: Mapping[str, Any], kind: str
) -> bool:
    """The guarded close (contract §4 C8, D-TG-85): `UPDATE … WHERE id = :id AND status = 'open'`.
    Zero rows updated is a normal outcome, not an error — a second closer, a dismissed or expired
    item, and a re-run over the same message all no-op here rather than raising (C8, FR-033,
    FR-035).

    `first_response_moderator_id` is resolved from `message`'s sender — separate from
    `responsible_moderator_id`, so a colleague covering shows as help, never as a transfer of
    credit (C7).

    Returns whether this call is the one that closed the item.
    """
    responding_moderator_id = (
        await session.execute(
            sa.select(moderators.c.id).where(
                moderators.c.telegram_user_id == message["telegram_user_id"]
            )
        )
    ).scalar_one_or_none()
    result = await session.execute(
        attention_items.update()
        .where(attention_items.c.id == item_id, attention_items.c.status == "open")
        .values(
            status="answered",
            first_response_message_id=message["message_id"],
            first_response_at=message["sent_at"],
            first_response_moderator_id=responding_moderator_id,
            first_response_kind=kind,
        )
    )
    rowcount: int = result.rowcount  # type: ignore[attr-defined]
    return rowcount == 1


async def match_existing_responses(session: AsyncSession, item: Mapping[str, Any]) -> None:
    """Contract §4.1 C10, T045: called from `open_item` at the moment an item opens, scanning
    messages already stored after `item["opened_at"]` and delegating to the **same** predicate
    `match_response` uses on live traffic (D-TG-82) — one matcher, two entry points. Writes no
    second predicate.

    Rule (a) is resolved first, against this item's own burst members (`attention_item_id` is
    already set on them by the caller before this runs). Rule (b) is resolved only when no direct
    reply qualifies, and only when `item` is itself the oldest open item the candidate message
    would close (C3) — otherwise an older still-open item in the same chat and thread is the one
    that message belongs to, and this item is left for its own later match.
    """
    telegram_chat_id = item["telegram_chat_id"]
    opened_at = item["opened_at"]

    direct = (
        (
            await session.execute(
                sa.select(telegram_messages)
                .where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.is_from_moderator.is_(True),
                    telegram_messages.c.sent_at > opened_at,
                    telegram_messages.c.reply_to_message_id.in_(
                        sa.select(telegram_messages.c.message_id).where(
                            telegram_messages.c.telegram_chat_id == telegram_chat_id,
                            telegram_messages.c.attention_item_id == item["id"],
                        )
                    ),
                )
                .order_by(telegram_messages.c.sent_at.asc(), telegram_messages.c.message_id.asc())
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    if direct is not None and _response_predicate(item, dict(direct)):
        await close_item(session, item["id"], dict(direct), "direct_reply")
        return

    candidate = (
        (
            await session.execute(
                sa.select(telegram_messages)
                .where(
                    telegram_messages.c.telegram_chat_id == telegram_chat_id,
                    telegram_messages.c.is_from_moderator.is_(True),
                    telegram_messages.c.sent_at > opened_at,
                    sa.not_(
                        telegram_messages.c.message_thread_id.is_distinct_from(
                            item["message_thread_id"]
                        )
                    ),
                )
                .order_by(telegram_messages.c.sent_at.asc(), telegram_messages.c.message_id.asc())
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    if candidate is None:
        return

    oldest = await _oldest_open_item_before(
        session,
        telegram_chat_id=telegram_chat_id,
        message_thread_id=item["message_thread_id"],
        sent_at=candidate["sent_at"],
    )
    if oldest is not None and oldest["id"] == item["id"]:
        await close_item(session, item["id"], dict(candidate), "group_message")


async def match_response(session: AsyncSession, message: Mapping[str, Any]) -> int | None:
    """Contract §4, T043: whether `message` — a moderator message already stored in
    `telegram_messages` — closes an open item, and which. Holds `chat_lock` for the duration
    (C11). Rule (a) is resolved first (C1): once a reply target's item is identified, that
    resolution is authoritative and rule (b) is never attempted for the same message, whatever
    its outcome.

    Returns the closed item's id, or `None` when nothing closed — no reply target, no qualifying
    open item, or a guarded close that updated zero rows (a race already resolved by someone
    else, or a target that was not open).
    """
    telegram_chat_id = message["telegram_chat_id"]
    async with chat_lock(session, telegram_chat_id):
        reply_to_message_id = message["reply_to_message_id"]
        if reply_to_message_id is not None:
            target_item_id = (
                await session.execute(
                    sa.select(telegram_messages.c.attention_item_id).where(
                        telegram_messages.c.telegram_chat_id == telegram_chat_id,
                        telegram_messages.c.message_id == reply_to_message_id,
                    )
                )
            ).scalar_one_or_none()
            if target_item_id is not None:
                item = (
                    (
                        await session.execute(
                            sa.select(attention_items).where(
                                attention_items.c.id == target_item_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                if _response_predicate(dict(item), message) and await close_item(
                    session, item["id"], message, "direct_reply"
                ):
                    return int(item["id"])
                return None

        candidate_item = await _oldest_open_item_before(
            session,
            telegram_chat_id=telegram_chat_id,
            message_thread_id=message["message_thread_id"],
            sent_at=message["sent_at"],
        )
        if candidate_item is None:
            return None
        if await close_item(session, candidate_item["id"], message, "group_message"):
            return int(candidate_item["id"])
        return None
