"""Shared fixtures for `tests/moderation/attention_judgement/` (TG-M5.3, `tasks.md` T014).

The attention judgement reads the same chats, messages, predictions and items the classification
does, so the classification package's builders are **re-exported by explicit import** rather than
rebuilt: a second copy of each builder would be a second definition free to drift. Every fixture a
re-exported one depends on is imported with it, since pytest resolves a fixture only from this
directory's own `conftest.py` and its parents, never a sibling's.

Added here:
- `insert_attention_judgement(...)` writes one `message_attention_judgements` row directly. Its
  `needs_response` is derived by calling `needs_response_for(intent)`, never a literal: the
  derivation has exactly one definition (`contracts/attention-judgement.md` S2, N2).
- `insert_attention_attempt(...)` writes one `message_attention_attempts` row, an exclusion or a
  failure.
- `seeded_attention_profile(active=...)` creates one fake `role='attention'` profile per call,
  mirroring `classification_seeded_profile`. An active one first deactivates any other active
  attention profile (`uq_model_profiles_one_active_per_role`). Every profile it created is removed
  on teardown, best effort: a profile a judgement still references stays (`ON DELETE RESTRICT`).

The schema guard is the classification package's own `_ensure_schema_at_head`, reached through
`classification_session_factory`. It checks for `message_attention_judgements`, so a test database
left at `0007` is brought to head before any of these builders writes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

import pytest_asyncio
from app.domain.moderation.attention_judgement import needs_response_for
from app.infrastructure.models import model_profiles
from app.infrastructure.models_moderation import (
    message_attention_attempts,
    message_attention_judgements,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.moderation.classification import conftest as classification_conftest

# Re-exported, by name, from the classification package (T014): pytest finds a fixture by the
# attribute name in this module.
classification_bot_id = classification_conftest.classification_bot_id
classification_chat_id = classification_conftest.classification_chat_id
classification_redis =classification_conftest.classification_redis
classification_redis_namespace = classification_conftest.classification_redis_namespace
classification_seeded_profile = classification_conftest.classification_seeded_profile
classification_session_factory = classification_conftest.classification_session_factory
classification_settings = classification_conftest.classification_settings
classification_test_database_url = classification_conftest.classification_test_database_url
fetch_attention_item = classification_conftest.fetch_attention_item
insert_assignment = classification_conftest.insert_assignment
insert_attention_item = classification_conftest.insert_attention_item
insert_chat = classification_conftest.insert_chat
insert_message = classification_conftest.insert_message
insert_moderator = classification_conftest.insert_moderator
insert_prediction = classification_conftest.insert_prediction
insert_user = classification_conftest.insert_user
scripted_gateway = classification_conftest.scripted_gateway

_TEST_ATTENTION_PROMPT_VERSION = "attention_test"


@pytest_asyncio.fixture
async def seeded_attention_profile(
    classification_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[..., Awaitable[int]]]:
    """Returns a builder, `await seeded_attention_profile(active=True) -> profile id`."""
    created: list[int] = []

    async def _seed(*, active: bool = True) -> int:
        async with classification_session_factory() as session:
            if active:
                await session.execute(
                    text(
                        "UPDATE model_profiles SET is_active = false "
                        "WHERE role = 'attention' AND is_active = true"
                    )
                )
            profile_id = (
                await session.execute(
                    model_profiles.insert()
                    .values(
                        name=f"att-test-{uuid.uuid4().hex[:12]}",
                        provider="fake",
                        model="fake-attention",
                        role="attention",
                        params={"reasoning_effort": "none"},
                        is_active=active,
                    )
                    .returning(model_profiles.c.id)
                )
            ).scalar_one()
            await session.commit()
        created.append(profile_id)
        return profile_id

    try:
        yield _seed
    finally:
        for profile_id in created:
            try:
                async with classification_session_factory() as session:
                    await session.execute(
                        model_profiles.delete().where(model_profiles.c.id == profile_id)
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001 — best-effort teardown, mirrors the classification one
                pass


@pytest_asyncio.fixture
def insert_attention_judgement(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded_attention_profile: Callable[..., Awaitable[int]],
) -> Callable[..., Awaitable[int]]:
    """Inserts one `message_attention_judgements` row and returns its id. Without a
    `model_profile_id`, the row cites an inactive attention profile created once per test."""
    default_profile: list[int] = []

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        intent: str,
        path: str = "live",
        created_at: datetime | None = None,
        model_profile_id: int | None = None,
        prompt_version: str = _TEST_ATTENTION_PROMPT_VERSION,
        model_run_id: int | None = None,
        is_current: bool = True,
    ) -> int:
        if model_profile_id is None:
            if not default_profile:
                default_profile.append(await seeded_attention_profile(active=False))
            model_profile_id = default_profile[0]
        values: dict[str, Any] = {
            "telegram_chat_id": telegram_chat_id,
            "telegram_message_id": telegram_message_id,
            "model_profile_id": model_profile_id,
            "model_run_id": model_run_id,
            "prompt_version": prompt_version,
            "intent": intent,
            "needs_response": needs_response_for(intent),
            "path": path,
            "is_current": is_current,
        }
        if created_at is not None:
            values["created_at"] = created_at
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    message_attention_judgements.insert()
                    .values(**values)
                    .returning(message_attention_judgements.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert


@pytest_asyncio.fixture
def insert_attention_attempt(
    classification_session_factory: async_sessionmaker[AsyncSession],
    seeded_attention_profile: Callable[..., Awaitable[int]],
) -> Callable[..., Awaitable[int]]:
    """Inserts one `message_attention_attempts` row and returns its id. A failure without a
    `model_profile_id` cites an inactive attention profile created once per test, since
    `ck_attention_attempt_profile` requires one; an exclusion never cites one."""
    default_profile: list[int] = []

    async def _insert(
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        outcome: str,
        reason: str,
        path: str = "live",
        model_profile_id: int | None = None,
        created_at: datetime | None = None,
    ) -> int:
        if outcome == "failed" and model_profile_id is None:
            if not default_profile:
                default_profile.append(await seeded_attention_profile(active=False))
            model_profile_id = default_profile[0]
        values: dict[str, Any] = {
            "telegram_chat_id": telegram_chat_id,
            "telegram_message_id": telegram_message_id,
            "path": path,
            "outcome": outcome,
            "reason": reason,
            "model_profile_id": model_profile_id,
        }
        if created_at is not None:
            values["created_at"] = created_at
        async with classification_session_factory() as session:
            row_id = (
                await session.execute(
                    message_attention_attempts.insert()
                    .values(**values)
                    .returning(message_attention_attempts.c.id)
                )
            ).scalar_one()
            await session.commit()
            return row_id

    return _insert
