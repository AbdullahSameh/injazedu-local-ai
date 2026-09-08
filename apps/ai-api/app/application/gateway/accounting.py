"""Writes one `model_runs` row per gateway call, after the caller's result is determined
(data-model.md §2, contracts/gateway-interface.md §6). A recording failure is logged and
swallowed — it must never fail a model call that already succeeded (FR-040).

`Gateway`'s default, when no `AccountingWriter` is wired in, is `NullAccountingWriter`: a bare
`Gateway(registry)` (every earlier story's tests, `smoke_llm.py`) must never write to whatever
`DATABASE_URL` happens to resolve to — that is a decision only explicit wiring should make, unlike
the lane/breaker's Redis defaults, because the constitution ties database identity, not Redis
identity, to the `_test` naming rule.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.model_profile import ModelProfile
from app.infrastructure.models import model_runs

logger = logging.getLogger(__name__)


def compute_request_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 over a canonical (sorted-key, no-whitespace) JSON serialisation (FR-038, SC-012).

    Identical requests produce identical digests. The digest answers "did we make this exact call
    before" without holding the request's text — which may be copyrighted book content — in the
    clear in a second place (data-model.md §2).
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AccountingLike(Protocol):
    async def record(
        self,
        *,
        profile: ModelProfile,
        operation: str,
        request_payload: Mapping[str, Any],
        latency_ms: int,
        attempts: int,
        ok: bool,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error_type: str | None = None,
        error_detail: str | None = None,
        response_payload: Mapping[str, Any] | None = None,
    ) -> None: ...


class NullAccountingWriter:
    """Satisfies `AccountingLike` by recording nothing — `Gateway`'s default."""

    async def record(self, **_kwargs: Any) -> None:
        return None


class AccountingWriter:
    """Writes on its own session (data-model.md §2's "Write path"), redacting request/response
    text unless `capture_payloads` is set (FR-039)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        capture_payloads: bool,
    ) -> None:
        self._session_factory = session_factory
        self._capture_payloads = capture_payloads

    async def record(
        self,
        *,
        profile: ModelProfile,
        operation: str,
        request_payload: Mapping[str, Any],
        latency_ms: int,
        attempts: int,
        ok: bool,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error_type: str | None = None,
        error_detail: str | None = None,
        response_payload: Mapping[str, Any] | None = None,
    ) -> None:
        digest = compute_request_digest(request_payload)
        try:
            async with self._session_factory() as session:
                await session.execute(
                    model_runs.insert().values(
                        model_profile_id=profile.id,
                        operation=operation,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                        attempts=attempts,
                        ok=ok,
                        error_type=error_type,
                        error_detail=error_detail,
                        request_digest=digest,
                        request_payload=dict(request_payload) if self._capture_payloads else None,
                        response_payload=(
                            dict(response_payload)
                            if self._capture_payloads and response_payload is not None
                            else None
                        ),
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 — a recording failure must never fail the model call (FR-040)
            logger.exception(
                "failed to record model_runs row (profile=%s, operation=%s)",
                profile.name,
                operation,
            )
