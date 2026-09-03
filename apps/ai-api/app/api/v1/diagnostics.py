"""POST /v1/diagnostics/ping and GET /v1/diagnostics/ping/{nonce} (research D-10).

Enqueueing runs in this process; execution happens in the worker (FR-016). A broker that is
unreachable fails the POST visibly with 503 rather than silently dropping the task.
"""

from __future__ import annotations

import json
import uuid

import redis.exceptions
from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app.workers.tasks.diagnostics import RESULT_KEY_PREFIX, ping

router = APIRouter()


class PingRequest(BaseModel):
    should_fail: bool = False


@router.post("/v1/diagnostics/ping", status_code=202)
async def enqueue_ping(body: PingRequest | None = None) -> JSONResponse:
    should_fail = body.should_fail if body is not None else False
    nonce = str(uuid.uuid4())
    try:
        ping.send(nonce, should_fail)
    except redis.exceptions.RedisError as exc:
        return JSONResponse(status_code=503, content={"detail": f"broker unreachable: {exc}"})
    return JSONResponse(status_code=202, content={"nonce": nonce, "status": "pending"})


@router.get("/v1/diagnostics/ping/{nonce}")
async def get_ping_result(nonce: str, request: Request) -> JSONResponse:
    redis_client = request.app.state.redis
    raw = await redis_client.get(f"{RESULT_KEY_PREFIX}:{nonce}")
    if raw is None:
        return JSONResponse(content={"nonce": nonce, "status": "pending"})
    return JSONResponse(content={"nonce": nonce, **json.loads(raw)})
