from __future__ import annotations

from datetime import datetime

from aiogram import Bot
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
        ticket.assigned_admin_id = ticket.assigned_admin_id or admin.id
        return await self.repository.add_message(
            ticket=ticket,
            text=text.strip()[:4096],
            now=now,
            author_type=MessageAuthorType.ADMIN,
            admin_id=admin.id,
        )

    async def notify_admins(self, bot: Bot, ticket: SupportTicket) -> None:
        text = f"Новое обращение №{ticket.number}\nТема: {ticket.subject}"
        sent: set[int] = set()
        if self.settings.admin_chat_id:
            await bot.send_message(self.settings.admin_chat_id, text)
            sent.add(self.settings.admin_chat_id)
        for admin in await AdminRepository(self.session).list_all():
            if admin.telegram_id not in sent and admin.is_active:
                try:
                    await bot.send_message(admin.telegram_id, text)
                except Exception:
                    continue
