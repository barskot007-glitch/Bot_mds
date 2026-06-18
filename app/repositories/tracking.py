from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import LinkClick, TrackingLink


class TrackingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        target_url: str,
        user_id: str | None,
        broadcast_id: str | None = None,
        event_id: str | None = None,
        button_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> TrackingLink:
        token = secrets.token_urlsafe(24)
        link = TrackingLink(
            token=token,
            target_url=target_url,
            user_id=user_id,
            broadcast_id=broadcast_id,
            event_id=event_id,
            button_id=button_id,
            expires_at=expires_at,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def get_active(self, token: str, now: datetime) -> TrackingLink | None:
        link = await self.session.scalar(
            select(TrackingLink).where(
                TrackingLink.token == token, TrackingLink.is_active.is_(True)
            )
        )
        if link is None:
            return None
        if link.expires_at is not None and link.expires_at < now:
            return None
        return link

    async def record_click(
        self,
        *,
        link: TrackingLink,
        now: datetime,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> LinkClick:
        click = LinkClick(
            tracking_link_id=link.id,
            user_id=link.user_id,
            broadcast_id=link.broadcast_id,
            event_id=link.event_id,
            button_id=link.button_id,
            clicked_at=now,
            ip_hash=ip_hash,
            user_agent=user_agent,
        )
        self.session.add(click)
        await self.session.flush()
        return click

    async def clicks_for_broadcast(self, broadcast_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count(LinkClick.id)).where(LinkClick.broadcast_id == broadcast_id)
            )
            or 0
        )
