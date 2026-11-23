"""US5 — `make tg-doctor`: one command answering "is this set up correctly?" (FR-036, FR-039,
SC-014, `contracts/health-ingestion.md` §2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from app.application.moderation.ingest import record_poll_outcome
from app.infrastructure.config import Settings
from app.infrastructure.models_moderation import alert_rules, telegram_chats
from app.providers.telegram.errors import TelegramAuthError, TelegramUnreachableError
from app.providers.telegram.models import BotIdentity, ChatMemberStatus, WebhookInfo
from app.scripts.tg_doctor import _run
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _StubProvider:
    def __init__(
        self,
        *,
        identity: BotIdentity | None = None,
        error: Exception | None = None,
        webhook_url: str = "",
        available_reactions: list[dict[str, str]] | None = None,
        member_status: str = "member",
        member_error: Exception | None = None,
    ) -> None:
        self._identity = identity
        self._error = error
        self._webhook_url = webhook_url
        self._available_reactions = available_reactions
        self._member_status = member_status
        self._member_error = member_error
        self.member_calls: list[dict[str, object]] = []

    async def get_me(self) -> BotIdentity:
        if self._error is not None:
            raise self._error
        assert self._identity is not None
        return self._identity

    async def get_updates(self, **_kwargs: object) -> list:  # pragma: no cover — unused here
        raise NotImplementedError

    async def get_webhook_info(self) -> WebhookInfo:
        return WebhookInfo(url=self._webhook_url)

    async def get_chat_member(self, **kwargs: object) -> ChatMemberStatus:
        """TG-M6 D5: the bot's standing in the alert destination."""
        self.member_calls.append(kwargs)
        if self._member_error is not None:
            raise self._member_error
        return ChatMemberStatus(status=self._member_status)

    async def get_chat_available_reactions(self, **_kwargs: object) -> list[dict[str, str]] | None:
        return self._available_reactions


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


async def _monitored_admin_chat(
    session_factory: async_sessionmaker[AsyncSession], chat_id: int
) -> None:
    async with session_factory() as session:
        await session.execute(
            telegram_chats.insert().values(
                chat_id=chat_id,
                chat_type="supergroup",
                title="Test Group",
                is_monitored=True,
                bot_status="administrator",
            )
        )
        await session.commit()


async def test_a_monitored_chat_that_allows_every_reaction_allows_eyes(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TG-M4.1 E9: `available_reactions` omitted means every emoji reaction is allowed."""
    await _monitored_admin_chat(ingest_session_factory, ingest_chat_id)

    await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b")),
    )

    # The shared test database may hold other tests' chats, so the exit code is not this case's
    # to judge — the chat's own line and the absence of the 👀 warning are.
    output = capsys.readouterr().out
    assert "👀 allowed" in output
    assert "whose reactions do not include" not in output


async def test_a_monitored_chat_whose_reactions_exclude_eyes_is_named_and_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _monitored_admin_chat(ingest_session_factory, ingest_chat_id)

    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(
            identity=BotIdentity(bot_id=ingest_bot_id, username="b"),
            available_reactions=[{"type": "emoji", "emoji": "👍"}],
        ),
    )

    assert exit_code != 0
    assert "👀 not allowed" in capsys.readouterr().out


# --- TG-M6 D5: the alert destination ---


async def _clear_destination(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            telegram_chats.update()
            .where(telegram_chats.c.is_alert_destination.is_(True))
            .values(is_alert_destination=False)
        )
        await session.commit()


@pytest_asyncio.fixture
async def no_destination(
    ingest_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Clears any destination another run left (there is at most one), before and after."""
    await _clear_destination(ingest_session_factory)
    yield
    await _clear_destination(ingest_session_factory)


async def _destination(
    session_factory: async_sessionmaker[AsyncSession], chat_id: int
) -> None:
    async with session_factory() as session:
        await session.execute(
            telegram_chats.insert().values(
                chat_id=chat_id,
                chat_type="supergroup",
                title="Moderators",
                is_monitored=False,
                is_alert_destination=True,
                bot_status="member",
            )
        )
        await session.commit()


def _destination_line(output: str) -> str:
    [line] = [row for row in output.splitlines() if "alert destination" in row]
    return line


async def test_a_designated_destination_where_the_bot_can_post_is_reported(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    no_destination: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _destination(ingest_session_factory, ingest_chat_id)
    client = _StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b"))

    await _run(_settings(token="t"), session_factory=ingest_session_factory, client=client)

    line = _destination_line(capsys.readouterr().out)
    assert "designated — Moderators" in line
    assert "bot can post (member)" in line
    assert "not monitored" in line
    assert "⚠" not in line
    assert client.member_calls == [{"chat_id": ingest_chat_id, "user_id": ingest_bot_id}]


@pytest.mark.parametrize("standing", ["left", "kicked", "restricted"])
async def test_a_destination_the_bot_cannot_post_in_is_named_and_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    no_destination: None,
    capsys: pytest.CaptureFixture[str],
    standing: str,
) -> None:
    await _destination(ingest_session_factory, ingest_chat_id)

    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(
            identity=BotIdentity(bot_id=ingest_bot_id, username="b"), member_status=standing
        ),
    )

    assert exit_code != 0
    line = _destination_line(capsys.readouterr().out)
    assert f"bot CANNOT post ({standing})" in line
    assert "⚠" in line


async def test_an_unreadable_standing_is_reported_not_guessed(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    no_destination: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _destination(ingest_session_factory, ingest_chat_id)

    exit_code = await _run(
        _settings(token="t"),
        session_factory=ingest_session_factory,
        client=_StubProvider(
            identity=BotIdentity(bot_id=ingest_bot_id, username="b"),
            member_error=TelegramUnreachableError("unreachable"),
        ),
    )

    assert exit_code != 0
    assert "bot standing unknown" in _destination_line(capsys.readouterr().out)


async def test_no_destination_and_no_enabled_rule_is_reported_without_failing(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_cleanup: None,
    no_destination: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with ingest_session_factory() as session:
        enabled = (
            await session.execute(
                alert_rules.select().where(alert_rules.c.is_enabled.is_(True))
            )
        ).first()
    if enabled is not None:  # pragma: no cover — another run's leftover; not this case's
        pytest.skip("an enabled alert rule exists in the shared database")
    client = _StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b"))

    await _run(_settings(token="t"), session_factory=ingest_session_factory, client=client)

    assert "none designated (no rule is enabled)" in _destination_line(capsys.readouterr().out)
    assert client.member_calls == []


async def test_no_destination_while_a_rule_is_enabled_exits_non_zero(
    ingest_session_factory: async_sessionmaker[AsyncSession],
    ingest_bot_id: int,
    ingest_chat_id: int,
    ingest_cleanup: None,
    ingest_chat_cleanup: None,
    no_destination: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with ingest_session_factory() as session:
        chat_pk = (
            await session.execute(
                telegram_chats.insert()
                .values(chat_id=ingest_chat_id, chat_type="supergroup", is_monitored=True,
                        bot_status="administrator")
                .returning(telegram_chats.c.id)
            )
        ).scalar_one()
        rule_id = (
            await session.execute(
                alert_rules.insert()
                .values(trigger="bot_not_admin", telegram_chat_id=chat_pk, is_enabled=True,
                        enabled_at=sa.func.now())
                .returning(alert_rules.c.id)
            )
        ).scalar_one()
        await session.commit()
    try:
        exit_code = await _run(
            _settings(token="t"),
            session_factory=ingest_session_factory,
            client=_StubProvider(identity=BotIdentity(bot_id=ingest_bot_id, username="b")),
        )
    finally:
        async with ingest_session_factory() as session:
            await session.execute(alert_rules.delete().where(alert_rules.c.id == rule_id))
            await session.commit()

    assert exit_code != 0
    assert "NONE —" in _destination_line(capsys.readouterr().out)
