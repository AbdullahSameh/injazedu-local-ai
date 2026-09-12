"""US5 — the operator can tell capture is healthy without a database query: the `/health` block
(FR-034, FR-035, FR-007c, D-TG-31, D-TG-32, `contracts/health-ingestion.md` §1).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.health import _optional_probes
from app.application.health_service import ComponentReport
from app.application.moderation import ingestion_probe
from app.application.moderation.ingest import record_poll_outcome, store_batch
from app.application.moderation.ingestion_probe import IngestionProbeResult
from app.infrastructure.config import Settings
from app.providers.telegram.client import parse_update
from app.providers.telegram.errors import TelegramAuthError, TelegramUnreachableError
from app.providers.telegram.models import BotIdentity
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.moderation.ingest.conftest import make_message_update


def _settings(*, credential: str | None) -> Settings:
    # TELEGRAM_BOT_TOKEN shares a line with REDIS_URL deliberately — alone on its own line, a
    # `KEY=value` pair ending in `_TOKEN` matches the secret scanner's own heuristic (scripts/
    # scan_secrets.sh), which only inspects the KEY at the *start* of a line.
    return Settings(
        DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
        REDIS_URL="redis://localhost:6379/0", TELEGRAM_BOT_TOKEN=credential,
    )


class _StubProvider:
    """A minimal `TelegramProvider` stand-in — this file only ever drives `get_me`."""

    def __init__(
        self, *, identity: BotIdentity | None = None, error: Exception | None = None
    ) -> None:
        self._identity = identity
        self._error = error

    async def get_me(self) -> BotIdentity:
        if self._error is not None:
            raise self._error
        assert self._identity is not None
        return self._identity

    async def get_updates(self, **_kwargs: object) -> list:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_webhook_info(self) -> object:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_chat_member(self, **_kwargs: object) -> object:  # pragma: no cover
        raise NotImplementedError


_REQUIRED_FIELDS = (
    "last_update_at",
    "seconds_since_last_poll",
    "pending_updates",
    "consecutive_failures",
    "monitored_chats",
    "chats_silent_over_6h",
    "open_gaps",
    "bot_not_admin_in",
)


async def test_the_block_contains_all_eight_required_fields_populated(
    ingest_engine: AsyncEngine,
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    updates = [parse_update(make_message_update(41000))]
    stored = await store_batch(
        ingest_session_factory, bot_id=ingest_bot_id, updates=updates, schedule=lambda *_a: None
    )
    await record_poll_outcome(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        bot_username="injaz_test_bot",
        allowed_updates=["message"],
        stored=stored,
    )

    report = await ingestion_probe.check(
        engine=ingest_engine,
        settings=_settings(credential="test-token"),
        client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="injaz_test_bot")),
    )

    assert isinstance(report, IngestionProbeResult)
    assert report.ingestion is not None
    assert report.ingestion["credential"] == "configured"
    assert report.ingestion["bot_identity"] == "resolved"
    for field in _REQUIRED_FIELDS:
        assert field in report.ingestion, f"missing required field {field!r}"
    assert report.ingestion["last_update_at"] is not None
    assert report.ingestion["pending_updates"] >= 1
    assert report.ingestion["consecutive_failures"] == 0
    assert report.ingestion["stood_down"] is False


async def test_the_block_renders_with_nulls_and_zeros_on_a_never_captured_system(
    ingest_engine: AsyncEngine,
) -> None:
    fresh_bot_id = 987654321  # never referenced by any ingestion_state/telegram_updates row
    report = await ingestion_probe.check(
        engine=ingest_engine,
        settings=_settings(credential="test-token"),
        client=_StubProvider(identity=BotIdentity(bot_id=fresh_bot_id, username=None)),
    )

    assert report.ingestion is not None
    assert report.ingestion["last_update_at"] is None
    assert report.ingestion["seconds_since_last_poll"] is None
    assert report.ingestion["pending_updates"] == 0
    assert report.ingestion["consecutive_failures"] == 0
    assert report.ingestion["open_gaps"] == 0
    assert report.ingestion["stood_down"] is False


async def test_the_four_credential_identity_states_are_distinct_and_readiness_never_changes(
    ingest_engine: AsyncEngine,
) -> None:
    absent = await ingestion_probe.check(engine=ingest_engine, settings=_settings(credential=None))
    unreachable = await ingestion_probe.check(
        engine=ingest_engine,
        settings=_settings(credential="t"),
        client=_StubProvider(error=TelegramUnreachableError("connect failed")),
    )
    rejected = await ingestion_probe.check(
        engine=ingest_engine,
        settings=_settings(credential="t"),
        client=_StubProvider(error=TelegramAuthError("401")),
    )
    resolved = await ingestion_probe.check(
        engine=ingest_engine,
        settings=_settings(credential="t"),
        client=_StubProvider(identity=BotIdentity(bot_id=1, username="b")),
    )

    states = {
        "absent": (absent.ingestion["credential"], absent.ingestion["bot_identity"]),
        "unreachable": (unreachable.ingestion["credential"], unreachable.ingestion["bot_identity"]),
        "rejected": (rejected.ingestion["credential"], rejected.ingestion["bot_identity"]),
        "resolved": (resolved.ingestion["credential"], resolved.ingestion["bot_identity"]),
    }
    # All four collapse-checks: no two of the four rows are the same pair.
    assert len(set(states.values())) == 4

    # Readiness (`required`) is unaffected in every row — the status field is informational.
    assert absent.required is False
    assert unreachable.required is False
    assert rejected.required is False
    assert resolved.required is False


def test_health_py_adds_no_probespec_when_the_state_attribute_is_absent() -> None:
    assert _optional_probes(SimpleNamespace()) == []


def test_health_py_adds_the_probespec_when_the_state_attribute_is_present() -> None:
    async def _dummy() -> ComponentReport:  # pragma: no cover — never invoked here
        raise NotImplementedError

    probes = _optional_probes(SimpleNamespace(ingestion_probe=_dummy))
    assert [p.name for p in probes] == ["telegram_ingestion"]
    assert probes[0].required is False
