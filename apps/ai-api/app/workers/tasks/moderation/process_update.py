"""`process_update` — dispatches interpretation by kind (FR-011, FR-012, D-TG-61,
`contracts/message-derivation.md` §1, `contracts/incident-lifecycle.md` §2, D-TG-112).

`message` → `messages.derive_message`; `edited_message` → `messages.apply_edit`;
`message_reaction` → `evidence.derive_reaction_evidence` (TG-M4, US2); `chat_member` →
`evidence.derive_membership_evidence` (TG-M4, US3). `callback_query` → TG-M6's
`alert_press.derive_alert_press` (`contracts/alerting.md` §5, amending `message-derivation.md`
§1): a press in the alert group records at most one act, then `answer_alert_press` is enqueued
with the outcome, to answer the press and refresh its alert (B7). The derivation itself sends
nothing (B8). `my_chat_member` → nothing here — its standing update already happened at capture
time, in TG-M1's `upsert_chats_from_batch` (`data-model.md` §1). A moderator's direct reply needs
no dispatch of its own: the evidence view reads it from `telegram_messages` in place (V11).
`unknown` is left exactly as TG-M1 left it: stored, about to be marked handled, deriving nothing.
Declining to interpret is not a failure.

`processed_at` is set unconditionally at the end, regardless of kind — the same "setting it
twice is the same result" contract TG-M1 established, now with real work happening first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import dramatiq
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.moderation.alert_press import derive_alert_press
from app.application.moderation.evidence import (
    derive_membership_evidence,
    derive_reaction_evidence,
)
from app.application.moderation.messages import apply_edit, derive_message
from app.infrastructure.db import run_with_worker_session
from app.infrastructure.models_moderation import telegram_updates
from app.workers.tasks.moderation.answer_alert_press import answer_alert_press

logger = logging.getLogger(__name__)


def _send_answer(update_row_id: int, outcome: str) -> None:
    answer_alert_press.send(update_row_id, outcome)


async def process_update_row(
    session_factory: async_sessionmaker[AsyncSession],
    update_row_id: int,
    *,
    send_answer: Callable[[int, str], object] = _send_answer,
) -> None:
    async with session_factory() as session:
        kind = (
            await session.execute(
                sa.select(telegram_updates.c.update_type).where(
                    telegram_updates.c.id == update_row_id
                )
            )
        ).scalar_one_or_none()

    if kind == "message":
        await derive_message(session_factory, update_row_id=update_row_id)
    elif kind == "edited_message":
        await apply_edit(session_factory, update_row_id=update_row_id)
    elif kind == "message_reaction":
        await derive_reaction_evidence(session_factory, update_row_id=update_row_id)
    elif kind == "chat_member":
        await derive_membership_evidence(session_factory, update_row_id=update_row_id)
    elif kind == "callback_query":
        outcome = await derive_alert_press(session_factory, update_row_id)
        # Enqueued before the row is marked processed: a crash re-runs the derivation, which is
        # idempotent (B6), and at worst answers twice; Telegram refuses the second answer.
        send_answer(update_row_id, outcome.value)

    async with session_factory() as session:
        await session.execute(
            telegram_updates.update()
            .where(telegram_updates.c.id == update_row_id)
            .values(processed_at=sa.func.now(), process_error=None)
        )
        await session.commit()


@dramatiq.actor(max_retries=3)
def process_update(update_row_id: int, update_id: int) -> None:
    logger.info("update processed", extra={"update_id": update_id})
    run_with_worker_session(
        lambda session_factory: process_update_row(session_factory, update_row_id)
    )
