from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.broadcast_support import SupportMessage, SupportTicket
from app.models.content_audit import Admin
from app.models.enums import MessageAuthorType, TicketStatus
from app.models.users_events import User
from app.repositories.admins import AdminRepository
from app.repositories.support import SupportRepository


class SupportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = SupportRepository(session)

    async def create_ticket(
        self, *, user: User, subject: str, text: str, now: datetime
    ) -> SupportTicket:
        if not subject.strip() or not text.strip():
            raise ValueError("Тема и текст обращения обязательны")
        return await self.repository.create_ticket(
            user_id=user.id,
            subject=subject.strip()[:255],
            text=text.strip()[:4096],
            now=now,
        )

    async def reply_as_user(
        self, *, ticket: SupportTicket, user: User, text: str, now: datetime
    ) -> SupportMessage:
        if ticket.user_id != user.id:
            raise PermissionError("Это обращение принадлежит другому пользователю")
        if ticket.status == TicketStatus.CLOSED:
            raise ValueError("Обращение закрыто. Сначала откройте его повторно")
        return await self.repository.add_message(
            ticket=ticket,
            text=text.strip()[:4096],
            now=now,
            author_type=MessageAuthorType.USER,
            user_id=user.id,
        )

    async def reply_as_admin(
        self, *, ticket: SupportTicket, admin: Admin, text: str, now: datetime
    ) -> SupportMessage:
        if ticket.status == TicketStatus.CLOSED:
            raise ValueError("Закрытое обращение нужно сначала открыть повторно")
        message = await self.repository.add_message(
            ticket=ticket,
            text=text.strip()[:4096],
            now=now,
            author_type=MessageAuthorType.ADMIN,
            admin_id=admin.id,
        )
        ticket.status = TicketStatus.CLOSED
        ticket.closed_at = now
        return message

    async def notify_admins(
        self,
        bot: Bot,
        ticket: SupportTicket,
        user: User,
        source_message: Message | None = None,
    ) -> None:
        username = f"@{user.username}" if user.username else "не указан"
        name = " ".join(part for part in [user.first_name, user.last_name] if part) or "не указано"
        text = (
            "Новое сообщение в поддержку\n\n"
            f"Обращение №{ticket.number}\n"
            f"Пользователь: {name}\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Username: {username}\n"
            f"Телефон: {user.phone or 'не указан'}\n"
            f"Email: {user.email or 'не указан'}\n\n"
            "Ответить можно через /admin → Обращения."
        )
        recipients: set[int] = set(self.settings.superadmin_ids)
        if self.settings.admin_chat_id:
            recipients.add(self.settings.admin_chat_id)
        for admin in await AdminRepository(self.session).list_all():
            if admin.is_active:
                recipients.add(admin.telegram_id)
        for telegram_id in recipients:
            try:
                await bot.send_message(telegram_id, text)
                if source_message is not None:
                    await source_message.copy_to(telegram_id)
            except Exception:
                continue
