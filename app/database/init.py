from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import Admin
from app.models.enums import AdminRole
from app.repositories.text_library import TextLibraryRepository
from app.texts.library import DEFAULT_TEXTS


async def ensure_superadmins(session: AsyncSession, telegram_ids: tuple[int, ...]) -> None:
    for telegram_id in telegram_ids:
        existing = await session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
        if existing is None:
            session.add(Admin(telegram_id=telegram_id, role=AdminRole.SUPERADMIN, is_active=True))
        else:
            existing.role = AdminRole.SUPERADMIN
            existing.is_active = True
    await session.commit()


async def ensure_text_library(session: AsyncSession) -> None:
    await TextLibraryRepository(session).seed_defaults(DEFAULT_TEXTS)
    await session.commit()
