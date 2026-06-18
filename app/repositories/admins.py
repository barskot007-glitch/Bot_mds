from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import Admin, AdminAction
from app.models.enums import AdminRole


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None:
        result: Admin | None = await self.session.scalar(
            select(Admin).where(
                Admin.telegram_id == telegram_id,
                Admin.is_active.is_(True),
                Admin.deleted_at.is_(None),
            )
        )
        return result

    async def get(self, admin_id: str) -> Admin | None:
        return await self.session.get(Admin, admin_id)

    async def list_all(self) -> list[Admin]:
        return list(
            await self.session.scalars(
                select(Admin).where(Admin.deleted_at.is_(None)).order_by(Admin.created_at.asc())
            )
        )

    async def upsert(
        self,
        *,
        telegram_id: int,
        role: AdminRole,
        added_by_admin_id: str | None,
    ) -> Admin:
        admin = await self.session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
        if admin is None:
            admin = Admin(
                telegram_id=telegram_id,
                role=role,
                is_active=True,
                added_by_admin_id=added_by_admin_id,
            )
            self.session.add(admin)
        else:
            admin.role = role
            admin.is_active = True
            admin.deleted_at = None
        await self.session.flush()
        return admin

    async def deactivate(self, admin: Admin, now: datetime) -> None:
        admin.is_active = False
        admin.deleted_at = now

    async def log_action(
        self,
        *,
        admin_id: str,
        action: str,
        now: datetime,
        entity_type: str | None = None,
        entity_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AdminAction(
                admin_id=admin_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_json=metadata or {},
                created_at=now,
            )
        )
