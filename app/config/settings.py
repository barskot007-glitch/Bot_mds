from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    bot_mode: Literal["polling", "webhook"] = Field(default="polling", alias="BOT_MODE")
    database_url: str = Field(default="sqlite+aiosqlite:///./bot.db", alias="DATABASE_URL")
    superadmin_ids: tuple[int, ...] = Field(default=(), alias="SUPERADMIN_IDS")
    admin_chat_id: int | None = Field(default=None, alias="ADMIN_CHAT_ID")

    webhook_base_url: str = Field(default="", alias="WEBHOOK_BASE_URL")
    webhook_path: str = Field(default="/webhook", alias="WEBHOOK_PATH")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    port: int = Field(default=8080, alias="PORT")
    host: str = Field(default="0.0.0.0", alias="HOST")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_to_file: bool = Field(default=False, alias="LOG_TO_FILE")
    default_timezone: str = Field(default="Asia/Yerevan", alias="DEFAULT_TIMEZONE")

    active_user_days: int = Field(default=30, alias="ACTIVE_USER_DAYS", ge=1)
    new_user_days: int = Field(default=7, alias="NEW_USER_DAYS", ge=1)

    broadcast_batch_size: int = Field(default=25, alias="BROADCAST_BATCH_SIZE", ge=1, le=1000)
    broadcast_concurrency: int = Field(default=5, alias="BROADCAST_CONCURRENCY", ge=1, le=20)
    broadcast_delay_seconds: float = Field(
        default=1.0, alias="BROADCAST_DELAY_SECONDS", ge=0.0, le=60.0
    )
    broadcast_max_attempts: int = Field(default=4, alias="BROADCAST_MAX_ATTEMPTS", ge=1, le=10)

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    tracking_base_url: str = Field(default="", alias="TRACKING_BASE_URL")
    age_groups: str = Field(
        default="0-17:до 18,18-24:18–24,25-34:25–34,35-44:35–44,45-54:45–54,55-200:55+",
        alias="AGE_GROUPS",
    )
    rate_limit_seconds: float = Field(default=0.6, alias="RATE_LIMIT_SECONDS", ge=0.0)
    max_message_length: int = Field(default=4096, alias="MAX_MESSAGE_LENGTH", ge=100, le=4096)
    max_upload_bytes: int = Field(default=20_000_000, alias="MAX_UPLOAD_BYTES", ge=1)

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> str:
        url = str(value or "").strip()
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @field_validator("superadmin_ids", mode="before")
    @classmethod
    def parse_ids(cls, value: object) -> tuple[int, ...]:
        if value in (None, "", ()):
            return ()
        if isinstance(value, (tuple, list, set)):
            return tuple(int(item) for item in value)
        return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())

    @field_validator("webhook_path")
    @classmethod
    def normalize_webhook_path(cls, value: str) -> str:
        value = value.strip() or "/webhook"
        return value if value.startswith("/") else f"/{value}"

    @field_validator("default_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def validate_production(self) -> Settings:
        if self.app_env == "production" and self.database_url.startswith("sqlite"):
            raise ValueError("SQLite запрещён в production без явного изменения APP_ENV")
        if self.bot_mode == "webhook":
            if not self.webhook_base_url:
                raise ValueError("WEBHOOK_BASE_URL обязателен в webhook-режиме")
            if not self.webhook_secret:
                raise ValueError("WEBHOOK_SECRET обязателен в webhook-режиме")
        return self

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url.rstrip('/')}{self.webhook_path}"

    @property
    def public_base_url(self) -> str:
        return (self.tracking_base_url or self.webhook_base_url).rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
