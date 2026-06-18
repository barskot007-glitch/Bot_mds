from __future__ import annotations

from typing import Any

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.services.permissions import PermissionService


class AdminFilter(Filter):
    def __init__(self, permission: str | None = None) -> None:
        self.permission = permission

    async def __call__(
        self,
        event: Message | CallbackQuery,
        session: AsyncSession,
        settings: Settings,
    ) -> bool | dict[str, Any]:
        if event.from_user is None:
            return False
        service = PermissionService(session, settings)
        admin = await service.get_admin(event.from_user.id)
        if admin is None:
            return False
        if self.permission and not service.has_permission(admin, self.permission):
            return False
        return {"admin_model": admin}
