from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from app.config.settings import Settings


class SecretMaskingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "***")
        record.msg = message
        record.args = ()
        return True


def setup_logging(settings: Settings) -> None:
    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }
    }
    root_handlers = ["console"]
    if settings.log_to_file and settings.app_env != "production":
        Path("logs").mkdir(exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": "logs/bot.log",
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
        }
        root_handlers.append("file")

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {"format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"}
            },
            "handlers": handlers,
            "root": {"level": settings.log_level.upper(), "handlers": root_handlers},
            "loggers": {
                "aiogram.event": {"level": "WARNING"},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
    masking_filter = SecretMaskingFilter([settings.bot_token, settings.webhook_secret])
    for handler in logging.getLogger().handlers:
        handler.addFilter(masking_filter)
