"""The per-chat advisory lock (`contracts/attention-rules.md` §4.2 C11, D-TG-81, probe 8).

Judgement and matching hold `pg_advisory_xact_lock` on the chat for the duration of one
transaction. With eight concurrent consumers (`WORKER_PROCESSES × WORKER_THREADS`), rule (b)'s
"oldest open item in this chat and thread" is a read-then-write race: row locks alone stop two
closers writing the *same* row but not each selecting a *different* "oldest" — the failure that
silently credits one message with two items. The lock is per chat, so quiet groups pay nothing
and busy ones serialise only against themselves.

Transaction-scoped (`pg_advisory_xact_lock`, never `pg_advisory_lock`): it releases on commit
**and** on rollback with no cleanup path to get wrong, which is what lets a test that fails
mid-transaction not leak it into the next one (probe 8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# Namespaced so this lock's keyspace never collides with an advisory lock some other part of the
# stack might one day take on the same session's connection.
_LOCK_KEY_PREFIX = "attention:chat:"


@asynccontextmanager
async def chat_lock(session: AsyncSession, chat_id: int) -> AsyncIterator[None]:
    """Acquires the advisory lock for `chat_id` (the `telegram_chats` surrogate id) for the rest
    of `session`'s transaction. Blocks until acquired — a concurrent judgement or match on the
    same chat waits its turn rather than racing; a different chat never contends.

    `session` must be the session the caller goes on to commit or roll back: the lock is bound to
    *that* transaction, not to this context manager's own scope.
    """
    key = f"{_LOCK_KEY_PREFIX}{chat_id}"
    await session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(key))))
    yield
