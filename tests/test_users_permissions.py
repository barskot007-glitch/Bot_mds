from __future__ import annotations

from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.content_audit import Admin
from app.models.enums import AdminRole
from app.services.permissions import PermissionService
from app.services.support import SupportService
from app.services.users import UserService, determine_age_group
from app.utils.time import utcnow
from tests.conftest import make_user


def test_age_group_detection(settings: Settings) -> None:
    assert determine_age_group(17, settings.age_groups) == "до 18"
    assert determine_age_group(24, settings.age_groups) == "18–24"
    assert determine_age_group(55, settings.age_groups) == "55+"


async def test_user_registration(session: AsyncSession, settings: Settings) -> None:
    telegram_user = TelegramUser(
        id=5001,
        is_bot=False,
        first_name="Иван",
        last_name="Иванов",
        username="ivan",
        language_code="ru",
    )
    service = UserService(session, settings)
    user = await service.ensure_user(telegram_user, now=utcnow(), source="campaign-a")
    await service.complete_registration(
        user,
        country="Армения",
        age=31,
        notifications_consent=True,
        data_processing_consent=True,
        first_name="Давид",
        last_name="Иванов",
        participation_history="Впервые",
    )
    assert user.registration_completed is True
    assert user.country == "Армения"
    assert user.first_name == "Давид"
    assert user.last_name == "Иванов"
    assert user.participation_history == "Впервые"
    assert user.age_group == "25–34"
    assert user.source == "campaign-a"


async def test_admin_permissions(session: AsyncSession, settings: Settings) -> None:
    admin = Admin(telegram_id=7001, role=AdminRole.MODERATOR, is_active=True)
    session.add(admin)
    await session.flush()
    service = PermissionService(session, settings)
    resolved = await service.get_admin(7001)
    assert resolved is not None
    assert service.has_permission(resolved, "events") is True
    assert service.has_permission(resolved, "broadcasts") is False


async def test_support_ticket_numbers_are_sequential(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, telegram_id=8001)
    service = SupportService(session, settings)
    first = await service.create_ticket(
        user=user, subject="Первое обращение", text="Описание", now=utcnow()
    )
    second = await service.create_ticket(
        user=user, subject="Второе обращение", text="Описание", now=utcnow()
    )
    assert first.number == 1
    assert second.number == 2


def test_railway_database_url_is_normalized() -> None:
    settings = Settings(
        BOT_TOKEN="123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        DATABASE_URL="postgresql://user:p%40ss@db.internal:5432/app",
        APP_ENV="production",
    )
    assert settings.database_url == "postgresql+asyncpg://user:p%40ss@db.internal:5432/app"
