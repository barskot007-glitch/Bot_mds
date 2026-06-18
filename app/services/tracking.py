from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.tracking import TrackingRepository


class TrackingService:
    def __init__(self, session: AsyncSession, public_base_url: str) -> None:
        self.repository = TrackingRepository(session)
        self.public_base_url = public_base_url.rstrip("/")

    async def create_url(
        self,
        *,
        target_url: str,
        user_id: str | None,
        broadcast_id: str | None = None,
        event_id: str | None = None,
        button_id: str | None = None,
    ) -> str:
        if not self.public_base_url:
            return target_url
        link = await self.repository.create(
            target_url=target_url,
            user_id=user_id,
            broadcast_id=broadcast_id,
            event_id=event_id,
            button_id=button_id,
        )
        return f"{self.public_base_url}/t/{link.token}"

    async def resolve_and_record(
        self,
        *,
        token: str,
        now: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> str | None:
        link = await self.repository.get_active(token, now)
        if link is None:
            return None
        ip_hash = hashlib.sha256(ip.encode()).hexdigest() if ip else None
        await self.repository.record_click(
            link=link,
            now=now,
            ip_hash=ip_hash,
            user_agent=user_agent[:512] if user_agent else None,
        )
        return link.target_url
