from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import FAQ


class FAQRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_published(self) -> list[FAQ]:
        return list(
            await self.session.scalars(
                select(FAQ)
                .where(FAQ.is_published.is_(True), FAQ.deleted_at.is_(None))
                .order_by(FAQ.position.asc(), FAQ.created_at.asc())
            )
        )

    async def list_all(self) -> list[FAQ]:
        return list(
            await self.session.scalars(
                select(FAQ).where(FAQ.deleted_at.is_(None)).order_by(FAQ.position.asc())
            )
        )

    async def get(self, faq_id: str) -> FAQ | None:
        result: FAQ | None = await self.session.scalar(
            select(FAQ).where(FAQ.id == faq_id, FAQ.deleted_at.is_(None))
        )
        return result

    async def create(self, question: str, answer: str) -> FAQ:
        max_position = int(await self.session.scalar(select(func.max(FAQ.position))) or 0)
        item = FAQ(question=question, answer=answer, position=max_position + 1, is_published=True)
        self.session.add(item)
        await self.session.flush()
        return item

    async def soft_delete(self, item: FAQ, now: datetime) -> None:
        item.deleted_at = now
        item.is_published = False
