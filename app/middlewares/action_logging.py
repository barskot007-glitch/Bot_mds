from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class ActionLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        action = "unknown"
        if isinstance(event, Message):
            action = f"message:{(event.text or event.content_type)[:80]}"
        elif isinstance(event, CallbackQuery):
            action = f"callback:{event.data or ''}"
        if user is not None:
            logger.info("Telegram action user=%s action=%s", user.id, action)
        return await handler(event, data)
