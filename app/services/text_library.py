from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import BotText
from app.repositories.text_library import TextLibraryRepository
from app.texts.library import DEFAULT_TEXTS, TEXT_GROUP_LABELS


class TextLibraryService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = TextLibraryRepository(session)

    async def ensure_defaults(self) -> None:
        await self.repository.seed_defaults(DEFAULT_TEXTS)

    async def get(self, text_key: str) -> str:
        item = await self.repository.get_random_active(text_key)
        if item is not None:
            return item.content
        fallback = DEFAULT_TEXTS.get(text_key)
        if fallback:
            return fallback[0]
        return ""

    async def groups(self) -> list[tuple[str, str, int, int]]:
        counts = await self.repository.group_counts()
        return [
            (
                key,
                label,
                counts.get(key, (0, 0))[0],
                counts.get(key, (0, 0))[1],
            )
            for key, label in TEXT_GROUP_LABELS.items()
        ]

    async def list_items(self, text_key: str) -> list[BotText]:
        return await self.repository.list_by_key(text_key)
