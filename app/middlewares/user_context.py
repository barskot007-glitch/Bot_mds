from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.services.users import UserService
from app.utils.time import utcnow


def extract_telegram_user(event: TelegramObject) -> Any:
    direct_user = getattr(event, "from_user", None)
    if direct_user is not None:
        return direct_user

    for field_name in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "shipping_query",
        "pre_checkout_query",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
    ):
        nested_event = getattr(event, field_name, None)
        nested_user = getattr(nested_event, "from_user", None)
        if nested_user is not None:
            return nested_user
    return None


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = extract_telegram_user(event)
        session = data.get("session")
        if telegram_user is not None and isinstance(session, AsyncSession):
            user = await UserService(session, self.settings).ensure_user(
                telegram_user, now=utcnow()
            )
            data["user_model"] = user
        return await handler(event, data)
