from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.broadcast_support import SupportMessage, SupportTicket
from app.models.content_audit import SequenceCounter
from app.models.enums import MessageAuthorType, TicketStatus


class SupportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_number(self) -> int:
        """Получить следующий номер обращения атомарно в SQLite и PostgreSQL."""
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            await self.session.execute(
                pg_insert(SequenceCounter)
                .values(name="support_ticket", value=0)
                .on_conflict_do_nothing(index_elements=[SequenceCounter.name])
            )
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            await self.session.execute(
                sqlite_insert(SequenceCounter)
                .values(name="support_ticket", value=0)
                .on_conflict_do_nothing(index_elements=[SequenceCounter.name])
            )
        else:
            existing = await self.session.get(SequenceCounter, "support_ticket")
            if existing is None:
                self.session.add(SequenceCounter(name="support_ticket", value=0))
                await self.session.flush()

        number = await self.session.scalar(
            update(SequenceCounter)
            .where(SequenceCounter.name == "support_ticket")
            .values(value=SequenceCounter.value + 1)
            .returning(SequenceCounter.value)
        )
        if number is None:
            raise RuntimeError("Не удалось сформировать номер обращения")
        return int(number)

    async def create_ticket(
        self, *, user_id: str, subject: str, text: str, now: datetime
    ) -> SupportTicket:
        ticket = SupportTicket(
            number=await self.next_number(),
            user_id=user_id,
            subject=subject,
            status=TicketStatus.NEW,
            last_reply_at=now,
        )
        self.session.add(ticket)
        await self.session.flush()
        self.session.add(
            SupportMessage(
                ticket_id=ticket.id,
                author_type=MessageAuthorType.USER,
                user_id=user_id,
                text=text,
            )
        )
        await self.session.flush()
        return ticket

    async def get(self, ticket_id: str) -> SupportTicket | None:
        result: SupportTicket | None = await self.session.scalar(
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id)
            .options(
                selectinload(SupportTicket.messages).selectinload(SupportMessage.attachments),
                selectinload(SupportTicket.user),
            )
        )
        return result

    async def get_by_number(self, number: int) -> SupportTicket | None:
        result: SupportTicket | None = await self.session.scalar(
            select(SupportTicket)
            .where(SupportTicket.number == number)
            .options(
                selectinload(SupportTicket.messages).selectinload(SupportMessage.attachments),
                selectinload(SupportTicket.user),
            )
        )
        return result

    async def list_for_user(self, user_id: str, limit: int = 20) -> list[SupportTicket]:
        return list(
            await self.session.scalars(
                select(SupportTicket)
                .where(SupportTicket.user_id == user_id)
                .order_by(SupportTicket.updated_at.desc())
                .limit(limit)
            )
        )

    async def list_open(self, offset: int, limit: int) -> list[SupportTicket]:
        return list(
            await self.session.scalars(
                select(SupportTicket)
                .where(SupportTicket.status != TicketStatus.CLOSED)
                .options(selectinload(SupportTicket.user))
                .order_by(SupportTicket.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    async def add_message(
        self,
        *,
        ticket: SupportTicket,
        text: str,
        now: datetime,
        author_type: MessageAuthorType,
        user_id: str | None = None,
        admin_id: str | None = None,
    ) -> SupportMessage:
        message = SupportMessage(
            ticket_id=ticket.id,
            author_type=author_type,
            user_id=user_id,
            admin_id=admin_id,
            text=text,
        )
        self.session.add(message)
        ticket.last_reply_at = now
        ticket.status = (
            TicketStatus.WAITING_USER
            if author_type == MessageAuthorType.ADMIN
            else TicketStatus.IN_PROGRESS
        )
        await self.session.flush()
        return message
