from __future__ import annotations

from aiogram.types import User as TelegramUser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.broadcast_support import SupportAttachment, SupportMessage, SupportTicket
from app.models.content_audit import Admin
from app.models.enums import AdminRole, FileType
from app.repositories.support import SupportRepository
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
        phone="+374 99 123 456",
        email="david@example.com",
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
    assert user.phone == "+374 99 123 456"
    assert user.email == "david@example.com"
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


async def test_crm_age_and_country_filters(session: AsyncSession, settings: Settings) -> None:
    from app.repositories.users import UserRepository

    minor = await make_user(session, telegram_id=8101, country="Армения")
    minor.age = 17
    minor.age_group = "до 18"
    adult_armenia = await make_user(session, telegram_id=8102, country="Армения")
    adult_armenia.age = 24
    adult_armenia.age_group = "18–24"
    adult_russia = await make_user(session, telegram_id=8103, country="Россия")
    adult_russia.age = 31
    adult_russia.age_group = "25–34"
    await session.flush()

    repository = UserRepository(session)
    minors_count = await repository.count_audience(
        {"subscribed_only": False, "age_max": 17},
        now=utcnow(),
        active_days=settings.active_user_days,
        new_days=settings.new_user_days,
    )
    selected_countries_count = await repository.count_audience(
        {
            "subscribed_only": False,
            "age_min": 18,
            "countries": ["Армения", "Россия"],
        },
        now=utcnow(),
        active_days=settings.active_user_days,
        new_days=settings.new_user_days,
    )

    assert minors_count == 1
    assert selected_countries_count == 2
    assert await repository.list_countries() == ["Армения", "Россия"]


async def test_admin_reply_waits_for_explicit_completion(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, telegram_id=8201)
    admin = Admin(telegram_id=8202, role=AdminRole.SUPPORT, is_active=True)
    session.add(admin)
    await session.flush()

    service = SupportService(session, settings)
    ticket = await service.create_ticket(
        user=user, subject="Обращение", text="Вопрос", now=utcnow()
    )
    await service.reply_as_admin(ticket=ticket, admin=admin, text="Ответ", now=utcnow())

    assert ticket.status.value == "waiting_user"
    assert ticket.closed_at is None


async def test_answered_ticket_is_deleted_with_messages_and_attachments(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, telegram_id=8301)
    admin = Admin(telegram_id=8302, role=AdminRole.SUPPORT, is_active=True)
    session.add(admin)
    await session.flush()

    service = SupportService(session, settings)
    ticket = await service.create_ticket(
        user=user, subject="Обращение", text="Вопрос", now=utcnow()
    )
    first_message = await session.scalar(
        select(SupportMessage).where(SupportMessage.ticket_id == ticket.id)
    )
    assert first_message is not None
    session.add(
        SupportAttachment(
            message_id=first_message.id,
            file_id="photo-file-id",
            file_unique_id="photo-unique-id",
            file_type=FileType.PHOTO,
            position=0,
        )
    )
    await service.reply_as_admin(ticket=ticket, admin=admin, text="Ответ", now=utcnow())
    await session.flush()

    await SupportRepository(session).delete_ticket(ticket.id)

    ticket_count = await session.scalar(select(func.count()).select_from(SupportTicket))
    message_count = await session.scalar(select(func.count()).select_from(SupportMessage))
    attachment_count = await session.scalar(select(func.count()).select_from(SupportAttachment))
    assert ticket_count == 0
    assert message_count == 0
    assert attachment_count == 0


async def test_cleanup_removes_previously_closed_tickets(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, telegram_id=8401)
    admin = Admin(telegram_id=8402, role=AdminRole.SUPPORT, is_active=True)
    session.add(admin)
    await session.flush()

    service = SupportService(session, settings)
    ticket = await service.create_ticket(
        user=user, subject="Старое обращение", text="Вопрос", now=utcnow()
    )
    await service.reply_as_admin(ticket=ticket, admin=admin, text="Ответ", now=utcnow())
    from app.models.enums import TicketStatus

    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = utcnow()
    await session.flush()

    deleted = await SupportRepository(session).delete_answered_tickets()

    assert deleted == 1
    remaining = await session.scalar(select(func.count()).select_from(SupportTicket))
    assert remaining == 0
