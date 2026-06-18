from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.broadcast_support import Broadcast, BroadcastRecipient
from app.models.enums import BroadcastStatus, RecipientStatus


class BroadcastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        title: str,
        text: str,
        audience_filter: dict[str, Any],
        author_admin_id: str,
        timezone: str,
    ) -> Broadcast:
        broadcast = Broadcast(
            title=title,
            text=text,
            audience_filter=audience_filter,
            author_admin_id=author_admin_id,
            timezone=timezone,
            status=BroadcastStatus.DRAFT,
        )
        self.session.add(broadcast)
        await self.session.flush()
        return broadcast

    async def get(self, broadcast_id: str, *, with_relations: bool = False) -> Broadcast | None:
        query = select(Broadcast).where(
            Broadcast.id == broadcast_id, Broadcast.deleted_at.is_(None)
        )
        if with_relations:
            query = query.options(
                selectinload(Broadcast.files),
                selectinload(Broadcast.buttons),
            )
        result: Broadcast | None = await self.session.scalar(query)
        return result

    async def list_admin(self, offset: int, limit: int) -> list[Broadcast]:
        return list(
            await self.session.scalars(
                select(Broadcast)
                .where(Broadcast.deleted_at.is_(None))
                .order_by(Broadcast.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    async def schedule(self, broadcast: Broadcast, when: datetime) -> None:
        broadcast.scheduled_at = when
        broadcast.status = BroadcastStatus.SCHEDULED

    async def cancel(self, broadcast: Broadcast) -> None:
        broadcast.status = BroadcastStatus.CANCELLED

    async def due(self, now: datetime) -> list[Broadcast]:
        return list(
            await self.session.scalars(
                select(Broadcast).where(
                    Broadcast.status == BroadcastStatus.SCHEDULED,
                    Broadcast.scheduled_at.is_not(None),
                    Broadcast.scheduled_at <= now,
                    Broadcast.deleted_at.is_(None),
                )
            )
        )

    async def resumable(self) -> list[Broadcast]:
        return list(
            await self.session.scalars(
                select(Broadcast).where(
                    Broadcast.status == BroadcastStatus.SENDING,
                    Broadcast.deleted_at.is_(None),
                )
            )
        )

    async def recipient_exists(self, broadcast_id: str, user_id: str) -> bool:
        return (
            await self.session.scalar(
                select(BroadcastRecipient.id).where(
                    BroadcastRecipient.broadcast_id == broadcast_id,
                    BroadcastRecipient.user_id == user_id,
                )
            )
            is not None
        )

    async def add_recipient(self, broadcast_id: str, user_id: str) -> BroadcastRecipient:
        recipient = BroadcastRecipient(broadcast_id=broadcast_id, user_id=user_id)
        self.session.add(recipient)
        await self.session.flush()
        return recipient

    async def pending_recipients(self, broadcast_id: str, limit: int) -> list[BroadcastRecipient]:
        return list(
            await self.session.scalars(
                select(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == broadcast_id,
                    BroadcastRecipient.status.in_(
                        [RecipientStatus.PENDING, RecipientStatus.PROCESSING]
                    ),
                )
                .options(selectinload(BroadcastRecipient.user))
                .order_by(BroadcastRecipient.created_at.asc())
                .limit(limit)
            )
        )

    async def count_pending(self, broadcast_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count(BroadcastRecipient.id)).where(
                    BroadcastRecipient.broadcast_id == broadcast_id,
                    BroadcastRecipient.status.in_(
                        [RecipientStatus.PENDING, RecipientStatus.PROCESSING]
                    ),
                )
            )
            or 0
        )

    async def statistics(self, broadcast_id: str) -> dict[str, int | float | str]:
        rows = await self.session.execute(
            select(BroadcastRecipient.status, func.count(BroadcastRecipient.id))
            .where(BroadcastRecipient.broadcast_id == broadcast_id)
            .group_by(BroadcastRecipient.status)
        )
        counts = {status.value: int(count) for status, count in rows.all()}
        sent = counts.get(RecipientStatus.SENT.value, 0)
        failed = counts.get(RecipientStatus.FAILED.value, 0)
        blocked = counts.get(RecipientStatus.BLOCKED.value, 0)
        total = sum(counts.values())
        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "blocked": blocked,
            "pending": counts.get(RecipientStatus.PENDING.value, 0),
            "accepted_rate": round(sent / total * 100, 2) if total else 0.0,
            "opens": "Недоступны в Telegram Bot API",
        }
