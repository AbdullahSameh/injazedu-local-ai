"""The model profile domain object (data-model.md §1).

A frozen dataclass, not an ORM row — `domain/` carries no ORM import and stays mypy `strict`.
`app/infrastructure/models.py` owns the table; `app/application/gateway/registry.py` builds one
of these from a row it reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Provider = Literal["ollama", "vllm", "fake"]
Role = Literal["llm", "embedding", "moderation", "attention"]
# The generation subset of `Role` — every role a `Gateway.generate_text`/`generate_structured`
# call may resolve, excluding `embedding` (D-TG-131). `attention` (TG-M5.3, D-TG-190) is the
# attention judgement's own role: its own active profile, independent of `moderation`'s.
GenerationRole = Literal["llm", "moderation", "attention"]


@dataclass(frozen=True, slots=True)
class ModelProfile:
    id: int
    name: str
    provider: Provider
    model: str
    role: Role
    params: Mapping[str, Any]
    is_active: bool
    base_url: str | None = None
    dim: int | None = None
    api_key_env: str | None = None
