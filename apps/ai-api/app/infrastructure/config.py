"""Startup configuration for the API and worker entrypoints.

Fails fast: a missing or invalid required variable exits the process with a message
naming the variable, never a stack trace (FR-005).
"""

from __future__ import annotations

import sys

from pydantic import Field, ValidationError, field_validator, model_validator
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

    # --- Moderation Intelligence (TG-M0, all optional, all defaulted) ---
    # `str | None`, not `str = ""`: "not configured" and "configured empty" are the same state
    # (D-TG-26). Never validated here — carried, unread until TG-M1 (D-TG-27).
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_updates: str = Field(
        default="message,edited_message,my_chat_member,chat_member,message_reaction,"
        "callback_query",
        alias="TELEGRAM_ALLOWED_UPDATES",
    )
    moderation_burst_gap_s: int = Field(default=90, alias="MODERATION_BURST_GAP_S")
    moderation_item_max_age_s: int = Field(default=86400, alias="MODERATION_ITEM_MAX_AGE_S")
    moderation_text_retention_days: int = Field(default=90, alias="MODERATION_TEXT_RETENTION_DAYS")

    # --- Telegram Event Ingestion (TG-M1, all optional, all defaulted) ---
    telegram_api_base_url: str = Field(
        default="https://api.telegram.org", alias="TELEGRAM_API_BASE_URL"
    )
    telegram_poll_timeout_s: int = Field(default=30, alias="TELEGRAM_POLL_TIMEOUT_S")
    # The Bot API's own ceiling on getUpdates' limit parameter (D-TG-40).
    telegram_poll_limit: int = Field(default=100, alias="TELEGRAM_POLL_LIMIT")
    telegram_conflict_standdown_count: int = Field(
        default=5, alias="TELEGRAM_CONFLICT_STANDDOWN_COUNT"
    )
    moderation_gap_min_silence_s: int = Field(default=300, alias="MODERATION_GAP_MIN_SILENCE_S")
    # 691200s = 8 days: past Telegram's one-week retention, where a re-sync must omit `offset`
    # rather than continue polling forward forever (D-TG-33, D-TG-39).
    moderation_stall_resync_s: int = Field(default=691200, alias="MODERATION_STALL_RESYNC_S")

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _empty_telegram_bot_token_is_absent(cls, value: object) -> object:
        # "" and unset are one state (D-TG-26) — pydantic does not coerce this on its own.
        if value == "":
            return None
        return value

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

    @model_validator(mode="after")
    def _telegram_allowed_updates_is_non_empty(self) -> Settings:
        if not self.telegram_allowed_updates.strip():
            raise ValueError("TELEGRAM_ALLOWED_UPDATES must not be empty")
        return self

    @model_validator(mode="after")
    def _moderation_burst_gap_is_positive(self) -> Settings:
        # A data-safety check, not config hygiene: MODERATION_BURST_GAP_S=0 would make every
        # message its own burst, silently inflating the attention-item count TG-M3 measures.
        if self.moderation_burst_gap_s <= 0:
            raise ValueError(
                f"MODERATION_BURST_GAP_S must be positive (got {self.moderation_burst_gap_s})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_item_max_age_is_positive(self) -> Settings:
        if self.moderation_item_max_age_s <= 0:
            raise ValueError(
                "MODERATION_ITEM_MAX_AGE_S must be positive "
                f"(got {self.moderation_item_max_age_s})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_text_retention_is_positive(self) -> Settings:
        # A data-safety check, not config hygiene: MODERATION_TEXT_RETENTION_DAYS=0 reaching
        # TG-M10's purge_expired_text actor would null every message text on its first run.
        if self.moderation_text_retention_days <= 0:
            raise ValueError(
                "MODERATION_TEXT_RETENTION_DAYS must be positive "
                f"(got {self.moderation_text_retention_days})"
            )
        return self


    @model_validator(mode="after")
    def _telegram_poll_timeout_is_positive(self) -> Settings:
        if self.telegram_poll_timeout_s <= 0:
            raise ValueError(
                f"TELEGRAM_POLL_TIMEOUT_S must be positive (got {self.telegram_poll_timeout_s})"
            )
        return self

    @model_validator(mode="after")
    def _telegram_poll_limit_is_in_bot_api_range(self) -> Settings:
        # The Bot API rejects getUpdates(limit=...) outside 1-100 (D-TG-40).
        if not 1 <= self.telegram_poll_limit <= 100:
            raise ValueError(
                f"TELEGRAM_POLL_LIMIT must be between 1 and 100 (got {self.telegram_poll_limit})"
            )
        return self

    @model_validator(mode="after")
    def _telegram_conflict_standdown_count_is_positive(self) -> Settings:
        if self.telegram_conflict_standdown_count <= 0:
            raise ValueError(
                "TELEGRAM_CONFLICT_STANDDOWN_COUNT must be positive "
                f"(got {self.telegram_conflict_standdown_count})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_gap_min_silence_is_positive(self) -> Settings:
        if self.moderation_gap_min_silence_s <= 0:
            raise ValueError(
                "MODERATION_GAP_MIN_SILENCE_S must be positive "
                f"(got {self.moderation_gap_min_silence_s})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_stall_resync_is_positive(self) -> Settings:
        if self.moderation_stall_resync_s <= 0:
            raise ValueError(
                "MODERATION_STALL_RESYNC_S must be positive "
                f"(got {self.moderation_stall_resync_s})"
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
