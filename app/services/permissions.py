from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.content_audit import Admin
from app.models.enums import AdminRole
from app.repositories.admins import AdminRepository

PERMISSIONS: dict[AdminRole, frozenset[str]] = {
    AdminRole.SUPERADMIN: frozenset({"*"}),
    AdminRole.ADMIN: frozenset(
        {
            "events",
            "broadcasts",
            "users",
            "support",
            "faq",
            "statistics",
            "export",
            "logs",
        }
    ),
    AdminRole.MODERATOR: frozenset({"events", "faq", "statistics"}),
    AdminRole.SUPPORT: frozenset({"support"}),
}


class PermissionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.repository = AdminRepository(session)
        self.settings = settings

    async def get_admin(self, telegram_id: int) -> Admin | None:
        admin = await self.repository.get_by_telegram_id(telegram_id)
        if admin is not None:
            return admin
        if telegram_id in self.settings.superadmin_ids:
            return await self.repository.upsert(
                telegram_id=telegram_id,
                role=AdminRole.SUPERADMIN,
                added_by_admin_id=None,
            )
        return None

    async def require(self, telegram_id: int, permission: str) -> Admin:
        admin = await self.get_admin(telegram_id)
        if admin is None or not self.has_permission(admin, permission):
            raise PermissionError("Недостаточно прав")
        return admin

    @staticmethod
    def has_permission(admin: Admin, permission: str) -> bool:
        permissions = PERMISSIONS[admin.role]
        return "*" in permissions or permission in permissions

    @staticmethod
    def can_manage_role(actor: Admin, target_role: AdminRole) -> bool:
        return actor.role == AdminRole.SUPERADMIN and target_role in set(AdminRole)
