"""Startup configuration for the API and worker entrypoints.

Fails fast: a missing or invalid required variable exits the process with a message
naming the variable, never a stack trace (FR-005).
"""

from __future__ import annotations

import sys
from typing import Literal

from pydantic import Field, ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The classification instructions a deployment may select (D-TG-163): each is a file under
# `app/prompts/moderation/` pinned by its SHA-256, and its name is the `prompt_version` stored on
# every prediction. The one definition — the classifier and the smoke test read their allowlist
# from here.
ModerationPromptVersion = Literal["classify_v1", "classify_v2"]


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

    # --- Groups, Users, Messages and Moderator Ownership (TG-M2, optional, defaulted) ---
    moderation_rederive_batch_size: int = Field(
        default=500, alias="MODERATION_REDERIVE_BATCH_SIZE"
    )

    # --- Deterministic Response Tracking (TG-M3, optional, defaulted) ---
    moderation_tick_interval_s: int = Field(default=30, alias="MODERATION_TICK_INTERVAL_S")
    moderation_percentile_min_samples: int = Field(
        default=10, alias="MODERATION_PERCENTILE_MIN_SAMPLES"
    )

    # --- Policy Incidents (TG-M4, optional, defaulted) ---
    moderation_incident_max_age_s: int = Field(
        default=86400, alias="MODERATION_INCIDENT_MAX_AGE_S"
    )

    # --- AI Classification (TG-M5, optional, defaulted) ---
    # Confidence is the model's self-report, never a safety signal (operator item 3): the floor
    # and threshold below only decide where a prediction is routed, not whether to trust it.
    moderation_confidence_floor: float = Field(default=0.60, alias="MODERATION_CONFIDENCE_FLOOR")
    moderation_incident_confidence: float = Field(
        default=0.85, alias="MODERATION_INCIDENT_CONFIDENCE"
    )
    moderation_classify_max_attempts: int = Field(
        default=5, alias="MODERATION_CLASSIFY_MAX_ATTEMPTS"
    )
    moderation_classify_retry_base_s: int = Field(
        default=30, alias="MODERATION_CLASSIFY_RETRY_BASE_S"
    )
    # Opt-in (D-TG-163): `classify_v1` until the operator smokes `classify_v2` and switches. A
    # switch revisits nothing — every past prediction keeps the version it was made with.
    moderation_prompt_version: ModerationPromptVersion = Field(
        default="classify_v1", alias="MODERATION_PROMPT_VERSION"
    )

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _empty_telegram_bot_token_is_absent(cls, value: object) -> object:
        # "" and unset are one state (D-TG-26) — pydantic does not coerce this on its own.
        if value == "":
            return None
        return value

    @field_validator(
        "moderation_confidence_floor",
        "moderation_incident_confidence",
        "moderation_classify_max_attempts",
        "moderation_classify_retry_base_s",
        "moderation_prompt_version",
        mode="before",
    )
    @classmethod
    def _empty_classification_setting_is_default(
        cls, value: object, info: ValidationInfo
    ) -> object:
        # "" and unset are one state, as `_empty_telegram_bot_token_is_absent` treats it — the
        # field's own default carries the value forward rather than each validator repeating it.
        if value == "":
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
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

    @model_validator(mode="after")
    def _moderation_rederive_batch_size_is_positive(self) -> Settings:
        if self.moderation_rederive_batch_size <= 0:
            raise ValueError(
                "MODERATION_REDERIVE_BATCH_SIZE must be positive "
                f"(got {self.moderation_rederive_batch_size})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_tick_interval_is_positive(self) -> Settings:
        if self.moderation_tick_interval_s <= 0:
            raise ValueError(
                "MODERATION_TICK_INTERVAL_S must be positive "
                f"(got {self.moderation_tick_interval_s})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_percentile_min_samples_is_positive(self) -> Settings:
        if self.moderation_percentile_min_samples <= 0:
            raise ValueError(
                "MODERATION_PERCENTILE_MIN_SAMPLES must be positive "
                f"(got {self.moderation_percentile_min_samples})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_incident_max_age_is_positive(self) -> Settings:
        if self.moderation_incident_max_age_s <= 0:
            raise ValueError(
                "MODERATION_INCIDENT_MAX_AGE_S must be positive "
                f"(got {self.moderation_incident_max_age_s})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_confidence_floor_is_in_range(self) -> Settings:
        if not 0 <= self.moderation_confidence_floor <= 1:
            raise ValueError(
                "MODERATION_CONFIDENCE_FLOOR must be between 0 and 1 "
                f"(got {self.moderation_confidence_floor})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_incident_confidence_is_in_range(self) -> Settings:
        if not 0 <= self.moderation_incident_confidence <= 1:
            raise ValueError(
                "MODERATION_INCIDENT_CONFIDENCE must be between 0 and 1 "
                f"(got {self.moderation_incident_confidence})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_confidence_floor_at_most_incident_confidence(self) -> Settings:
        if self.moderation_confidence_floor > self.moderation_incident_confidence:
            raise ValueError(
                "MODERATION_CONFIDENCE_FLOOR must be less than or equal to "
                "MODERATION_INCIDENT_CONFIDENCE (got MODERATION_CONFIDENCE_FLOOR="
                f"{self.moderation_confidence_floor}, MODERATION_INCIDENT_CONFIDENCE="
                f"{self.moderation_incident_confidence})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_classify_max_attempts_is_positive(self) -> Settings:
        if self.moderation_classify_max_attempts <= 0:
            raise ValueError(
                "MODERATION_CLASSIFY_MAX_ATTEMPTS must be positive "
                f"(got {self.moderation_classify_max_attempts})"
            )
        return self

    @model_validator(mode="after")
    def _moderation_classify_retry_base_is_positive(self) -> Settings:
        if self.moderation_classify_retry_base_s <= 0:
            raise ValueError(
                "MODERATION_CLASSIFY_RETRY_BASE_S must be positive "
                f"(got {self.moderation_classify_retry_base_s})"
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
