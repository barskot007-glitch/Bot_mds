from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.services.users import UserService
from app.utils.time import utcnow


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = getattr(event, "from_user", None)
        session = data.get("session")
        if telegram_user is not None and isinstance(session, AsyncSession):
            user = await UserService(session, self.settings).ensure_user(
                telegram_user, now=utcnow()
            )
            data["user_model"] = user
        return await handler(event, data)
