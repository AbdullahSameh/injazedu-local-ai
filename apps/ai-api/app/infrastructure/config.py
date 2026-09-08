"""Startup configuration for the API and worker entrypoints.

Fails fast: a missing or invalid required variable exits the process with a message
naming the variable, never a stack trace (FR-005).
"""

from __future__ import annotations

import sys

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL"
    )
    api_port: int = Field(default=8000, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    worker_processes: int = Field(default=2, alias="WORKER_PROCESSES")
    worker_threads: int = Field(default=4, alias="WORKER_THREADS")
    worker_heartbeat_interval_s: int = Field(default=5, alias="WORKER_HEARTBEAT_INTERVAL_S")
    worker_heartbeat_ttl_s: int = Field(default=15, alias="WORKER_HEARTBEAT_TTL_S")

    gateway_call_timeout_s: int = Field(default=180, alias="GATEWAY_CALL_TIMEOUT_S")
    gateway_max_retries: int = Field(default=2, alias="GATEWAY_MAX_RETRIES")
    gateway_retry_base_s: float = Field(default=0.5, alias="GATEWAY_RETRY_BASE_S")
    gateway_breaker_threshold: int = Field(default=5, alias="GATEWAY_BREAKER_THRESHOLD")
    gateway_breaker_open_s: int = Field(default=30, alias="GATEWAY_BREAKER_OPEN_S")
    gateway_lane_lease_ttl_s: int = Field(default=30, alias="GATEWAY_LANE_LEASE_TTL_S")
    gateway_lane_renew_s: int = Field(default=10, alias="GATEWAY_LANE_RENEW_S")
    gateway_profile_cache_ttl_s: int = Field(default=30, alias="GATEWAY_PROFILE_CACHE_TTL_S")
    gateway_capture_payloads: bool = Field(default=False, alias="GATEWAY_CAPTURE_PAYLOADS")

    @model_validator(mode="after")
    def _heartbeat_ttl_exceeds_interval(self) -> Settings:
        if self.worker_heartbeat_ttl_s <= self.worker_heartbeat_interval_s:
            raise ValueError(
                "WORKER_HEARTBEAT_TTL_S must be greater than WORKER_HEARTBEAT_INTERVAL_S "
                f"(got TTL_S={self.worker_heartbeat_ttl_s}, "
                f"INTERVAL_S={self.worker_heartbeat_interval_s})"
            )
        return self

    @model_validator(mode="after")
    def _lane_renew_precedes_lease_ttl(self) -> Settings:
        if self.gateway_lane_renew_s >= self.gateway_lane_lease_ttl_s:
            raise ValueError(
                "GATEWAY_LANE_RENEW_S must be less than GATEWAY_LANE_LEASE_TTL_S "
                f"(got GATEWAY_LANE_RENEW_S={self.gateway_lane_renew_s}, "
                f"GATEWAY_LANE_LEASE_TTL_S={self.gateway_lane_lease_ttl_s})"
            )
        return self

    @model_validator(mode="after")
    def _gateway_call_timeout_is_positive(self) -> Settings:
        if self.gateway_call_timeout_s <= 0:
            raise ValueError(
                f"GATEWAY_CALL_TIMEOUT_S must be positive (got {self.gateway_call_timeout_s})"
            )
        return self

    @model_validator(mode="after")
    def _gateway_max_retries_is_non_negative(self) -> Settings:
        if self.gateway_max_retries < 0:
            raise ValueError(
                f"GATEWAY_MAX_RETRIES must be non-negative (got {self.gateway_max_retries})"
            )
        return self


def load_settings() -> Settings:
    """Instantiate Settings or exit naming the offending variable(s) — no stack trace."""
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "<config>"
            print(f"Configuration error: {field}: {error['msg']}", file=sys.stderr)
        sys.exit(1)
