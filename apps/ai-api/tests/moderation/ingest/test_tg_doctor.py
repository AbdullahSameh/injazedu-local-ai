"""US5 — `make tg-doctor`: one command answering "is this set up correctly?" (FR-036, FR-039,
SC-014, `contracts/health-ingestion.md` §2).
"""

from __future__ import annotations

import pytest
from app.application.moderation.ingest import record_poll_outcome
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import telegram_chats
from app.providers.telegram.errors import TelegramAuthError
from app.providers.telegram.models import BotIdentity, WebhookInfo
from app.scripts.tg_doctor import _run
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _StubProvider:
    def __init__(
        self,
        *,
        identity: BotIdentity | None = None,
        error: Exception | None = None,
        webhook_url: str = "",
    ) -> None:
        self._identity = identity
        self._error = error
        self._webhook_url = webhook_url

    async def get_me(self) -> BotIdentity:
        if self._error is not None:
            raise self._error
        assert self._identity is not None
        return self._identity

    async def get_updates(self, **_kwargs: object) -> list:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_webhook_info(self) -> WebhookInfo:
        return WebhookInfo(url=self._webhook_url)

    async def get_chat_member(self, **_kwargs: object) -> object:  # pragma: no cover
        raise NotImplementedError


def _settings(*, token: str | None) -> Settings:
    # TELEGRAM_BOT_TOKEN shares a line with REDIS_URL deliberately — alone on its own line, a
    # `KEY=value` pair ending in `_TOKEN` matches the secret scanner's own heuristic (scripts/
    # scan_secrets.sh), which only inspects the KEY at the *start* of a line.
    return Settings(
        DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
        REDIS_URL="redis://localhost:6379/0", TELEGRAM_BOT_TOKEN=token,
    )


async def test_no_credential_says_so_and_exits_0(
    ingest_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exit_code = await _run(_settings(token=None), session_factory=ingest_session_factory)
    assert exit_code == 0


async def test_a_rejected_credential_is_named_and_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exit_code = await _run(
        _settings(token="bad-token"),
        session_factory=ingest_session_factory,
        client=_StubProvider(error=TelegramAuthError("401")),
    )
    assert exit_code != 0


async def test_inbound_delivery_configured_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(
            identity=BotIdentity(bot_id=ingest_bot_id, username="b"),
            webhook_url="https://example.com/webhook",
        ),
    )
    assert exit_code != 0


async def test_a_mismatched_subscription_set_names_the_gap_and_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
) -> None:
    # The poller last asserted only "message" — configuration (Settings' default) expects more.
    await record_poll_outcome(
        ingest_session_factory,
        bot_id=ingest_bot_id,
        bot_username="b",
        allowed_updates=["message"],
        stored=[],
    )

    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b")),
    )
    assert exit_code != 0


async def test_bot_not_admin_in_a_monitored_chat_is_named_and_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
) -> None:
    async with ingest_session_factory() as session:
        await session.execute(
            telegram_chats.insert().values(
                chat_id=ingest_chat_id,
                chat_type="supergroup",
                title="Test Group",
                is_monitored=True,
                bot_status="member",
            )
        )
        await session.commit()

    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b")),
    )
    assert exit_code != 0


async def test_the_credential_is_never_printed_not_even_truncated(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_credential = "999999:AAHfakeCredentialValueThatMustNeverAppear"
    await _run(
        _settings(token=fake_credential),
        session_factory=ingest_session_factory,
        client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b")),
    )
    output = capsys.readouterr()
    assert fake_credential not in output.out
    assert fake_credential not in output.err
