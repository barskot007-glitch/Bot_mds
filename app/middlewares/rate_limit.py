from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or self.min_interval <= 0:
            return await handler(event, data)
        now = time.monotonic()
        previous = self._last_seen.get(user.id, 0.0)
        if now - previous < self.min_interval:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком частые действия", show_alert=False)
            elif isinstance(event, Message):
                await event.answer("Подождите немного и повторите действие.")
            return None
        self._last_seen[user.id] = now
        if len(self._last_seen) > 100_000:
            cutoff = now - 3600
            self._last_seen = {
                key: value for key, value in self._last_seen.items() if value >= cutoff
            }
        return await handler(event, data)
