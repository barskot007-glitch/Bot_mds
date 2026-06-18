from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.broadcast_support import Broadcast, BroadcastButton, BroadcastRecipient
from app.models.content_audit import LinkClick, TrackingLink
from app.models.enums import BroadcastStatus, RecipientStatus
from app.models.users_events import Event
from app.repositories.broadcasts import BroadcastRepository
from app.repositories.events import EventRepository
from app.repositories.users import UserRepository


class AnalyticsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def dashboard(self, now: datetime) -> dict[str, object]:
        user_repository = UserRepository(self.session)
        users = await user_repository.statistics(
            now=now,
            active_days=self.settings.active_user_days,
            new_days=self.settings.new_user_days,
        )
        event_count = int(
            await self.session.scalar(
                select(func.count(Event.id)).where(Event.deleted_at.is_(None))
            )
            or 0
        )
        broadcast_rows = await self.session.execute(
            select(Broadcast.status, func.count(Broadcast.id))
            .where(Broadcast.deleted_at.is_(None))
            .group_by(Broadcast.status)
        )
        broadcasts_by_status = {status.value: int(count) for status, count in broadcast_rows.all()}
        recipient_rows = await self.session.execute(
            select(BroadcastRecipient.status, func.count(BroadcastRecipient.id)).group_by(
                BroadcastRecipient.status
            )
        )
        deliveries = {status.value: int(count) for status, count in recipient_rows.all()}
        clicks = int(await self.session.scalar(select(func.count(LinkClick.id))) or 0)
        countries = await user_repository.distribution("country")
        age_groups = await user_repository.distribution("age_group")
        dynamics = await user_repository.registration_dynamics(since=now - timedelta(days=30))
        return {
            "users": users,
            "events": event_count,
            "broadcasts": sum(broadcasts_by_status.values()),
            "broadcasts_scheduled": broadcasts_by_status.get(BroadcastStatus.SCHEDULED.value, 0),
            "broadcasts_by_status": broadcasts_by_status,
            "sent_messages": deliveries.get(RecipientStatus.SENT.value, 0),
            "failed_messages": deliveries.get(RecipientStatus.FAILED.value, 0),
            "blocked_messages": deliveries.get(RecipientStatus.BLOCKED.value, 0),
            "clicks": clicks,
            "countries": countries,
            "age_groups": age_groups,
            "registration_dynamics": dynamics,
        }

    async def event_statistics(self, event_id: str) -> dict[str, float | int]:
        result = await EventRepository(self.session).statistics(event_id)
        event = await EventRepository(self.session).get(event_id)
        capacity = event.capacity if event else None
        registrations = int(result["registrations"])
        result["occupancy"] = (
            round(registrations / capacity * 100, 2) if capacity and capacity > 0 else 0.0
        )
        link_clicks = int(
            await self.session.scalar(
                select(func.count(LinkClick.id)).where(LinkClick.event_id == event_id)
            )
            or 0
        )
        result["link_clicks"] = link_clicks
        if event is not None and event.details_url:
            details_clicks = int(
                await self.session.scalar(
                    select(func.count(LinkClick.id))
                    .join(TrackingLink, TrackingLink.id == LinkClick.tracking_link_id)
                    .where(
                        LinkClick.event_id == event_id,
                        TrackingLink.target_url == event.details_url,
                    )
                )
                or 0
            )
        else:
            details_clicks = 0
        result["details_clicks"] = details_clicks
        return result

    async def broadcast_statistics(self, broadcast_id: str) -> dict[str, int | float | str]:
        result = await BroadcastRepository(self.session).statistics(broadcast_id)
        clicks = int(
            await self.session.scalar(
                select(func.count(LinkClick.id)).where(LinkClick.broadcast_id == broadcast_id)
            )
            or 0
        )
        unique_clicks = int(
            await self.session.scalar(
                select(func.count(func.distinct(LinkClick.user_id))).where(
                    LinkClick.broadcast_id == broadcast_id,
                    LinkClick.user_id.is_not(None),
                )
            )
            or 0
        )
        details_clicks = int(
            await self.session.scalar(
                select(func.count(LinkClick.id))
                .join(BroadcastButton, BroadcastButton.id == LinkClick.button_id)
                .where(
                    LinkClick.broadcast_id == broadcast_id,
                    BroadcastButton.is_details.is_(True),
                )
            )
            or 0
        )
        sent = int(result["sent"])
        result["clicks"] = clicks
        result["unique_clicks"] = unique_clicks
        result["details_clicks"] = details_clicks
        result["ctr"] = round(clicks / sent * 100, 2) if sent else 0.0
        result["unique_ctr"] = round(unique_clicks / sent * 100, 2) if sent else 0.0
        return result
