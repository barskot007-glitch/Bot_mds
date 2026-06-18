from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import Admin
from app.models.enums import AdminRole
from app.repositories.text_library import TextLibraryRepository
from app.services.text_library import TextLibraryService
from app.texts.library import DEFAULT_TEXTS


async def test_text_library_seeds_and_returns_text(session: AsyncSession) -> None:
    service = TextLibraryService(session)
    await service.ensure_defaults()

    groups = await service.groups()
    welcome_group = next(group for group in groups if group[0] == "registration_welcome")
    assert welcome_group[2] == len(DEFAULT_TEXTS["registration_welcome"])
    assert welcome_group[3] == len(DEFAULT_TEXTS["registration_welcome"])
    assert await service.get("registration_name") in DEFAULT_TEXTS["registration_name"]


async def test_admin_can_add_edit_toggle_and_delete_text(session: AsyncSession) -> None:
    admin = Admin(telegram_id=9911, role=AdminRole.ADMIN, is_active=True)
    session.add(admin)
    await session.flush()

    repository = TextLibraryRepository(session)
    item = await repository.create(
        text_key="main_menu",
        content="Первый вариант",
        created_by_admin_id=admin.id,
    )
    assert item.is_active is True

    await repository.update_content(item, "Обновлённый вариант")
    assert item.content == "Обновлённый вариант"

    await repository.toggle(item)
    assert item.is_active is False

    await repository.soft_delete(item)
    assert await repository.get(item.id) is None
