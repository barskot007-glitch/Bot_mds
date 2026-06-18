from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import BotText
from app.utils.time import utcnow


class TextLibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def seed_defaults(self, defaults: Mapping[str, Sequence[str]]) -> None:
        existing_count = int(
            await self.session.scalar(
                select(func.count(BotText.id)).where(BotText.deleted_at.is_(None))
            )
            or 0
        )
        if existing_count > 0:
            return
        for text_key, items in defaults.items():
            for position, content in enumerate(items):
                self.session.add(
                    BotText(
                        text_key=text_key,
                        content=content,
                        position=position,
                        is_active=True,
                    )
                )
        await self.session.flush()

    async def get_random_active(self, text_key: str) -> BotText | None:
        item: BotText | None = await self.session.scalar(
            select(BotText)
            .where(
                BotText.text_key == text_key,
                BotText.is_active.is_(True),
                BotText.deleted_at.is_(None),
            )
            .order_by(func.random())
            .limit(1)
        )
        return item

    async def list_by_key(self, text_key: str) -> list[BotText]:
        result = await self.session.scalars(
            select(BotText)
            .where(BotText.text_key == text_key, BotText.deleted_at.is_(None))
            .order_by(BotText.position.asc(), BotText.created_at.asc())
        )
        return list(result)

    async def group_counts(self) -> dict[str, tuple[int, int]]:
        rows = (
            await self.session.execute(
                select(
                    BotText.text_key,
                    func.count(BotText.id),
                    func.count(BotText.id).filter(BotText.is_active.is_(True)),
                )
                .where(BotText.deleted_at.is_(None))
                .group_by(BotText.text_key)
            )
        ).all()
        return {str(key): (int(total), int(active)) for key, total, active in rows}

    async def get(self, text_id: str) -> BotText | None:
        item = await self.session.get(BotText, text_id)
        if item is None or item.deleted_at is not None:
            return None
        return item

    async def create(
        self,
        *,
        text_key: str,
        content: str,
        created_by_admin_id: str | None,
    ) -> BotText:
        max_position = await self.session.scalar(
            select(func.max(BotText.position)).where(
                BotText.text_key == text_key,
                BotText.deleted_at.is_(None),
            )
        )
        item = BotText(
            text_key=text_key,
            content=content,
            position=int(max_position or -1) + 1,
            is_active=True,
            created_by_admin_id=created_by_admin_id,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_content(self, item: BotText, content: str) -> BotText:
        item.content = content
        await self.session.flush()
        return item

    async def toggle(self, item: BotText) -> BotText:
        item.is_active = not item.is_active
        await self.session.flush()
        return item

    async def soft_delete(self, item: BotText) -> None:
        item.deleted_at = utcnow()
        item.is_active = False
        await self.session.flush()
