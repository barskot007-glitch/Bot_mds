from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import EventStatus, RegistrationStatus
from app.models.users_events import Event, EventView, Registration


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: str, *, with_relations: bool = False) -> Event | None:
        query = select(Event).where(Event.id == event_id, Event.deleted_at.is_(None))
        if with_relations:
            query = query.options(selectinload(Event.files), selectinload(Event.links))
        result: Event | None = await self.session.scalar(query)
        return result

    async def get_for_update(self, event_id: str) -> Event | None:
        """Заблокировать строку события на время проверки лимита участников."""
        result: Event | None = await self.session.scalar(
            select(Event).where(Event.id == event_id, Event.deleted_at.is_(None)).with_for_update()
        )
        return result

    async def create(self, **values: Any) -> Event:
        event = Event(**values)
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_published(
        self,
        *,
        now: datetime,
        offset: int,
        limit: int,
        upcoming_only: bool = True,
        registration_open_only: bool = False,
        date_to: datetime | None = None,
    ) -> list[Event]:
        query = (
            select(Event)
            .where(
                Event.deleted_at.is_(None),
                Event.status.in_([EventStatus.PUBLISHED, EventStatus.REGISTRATION_CLOSED]),
            )
            .options(selectinload(Event.files), selectinload(Event.links))
            .order_by(Event.start_at.asc())
        )
        if upcoming_only:
            query = query.where(Event.start_at >= now)
        if registration_open_only:
            query = query.where(
                Event.status == EventStatus.PUBLISHED,
                Event.registration_enabled.is_(True),
            )
        if date_to is not None:
            query = query.where(Event.start_at <= date_to)
        result = await self.session.scalars(query.offset(offset).limit(limit))
        return list(result)

    async def list_admin(
        self,
        offset: int,
        limit: int,
        status: EventStatus | None = None,
    ) -> list[Event]:
        query = select(Event).where(Event.deleted_at.is_(None))
        if status is not None:
            query = query.where(Event.status == status)
        result = await self.session.scalars(
            query.order_by(Event.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result)

    async def count_registered(self, event_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count(Registration.id)).where(
                    Registration.event_id == event_id,
                    Registration.status.in_(
                        [RegistrationStatus.REGISTERED, RegistrationStatus.ATTENDED]
                    ),
                )
            )
            or 0
        )

    async def get_registration(self, user_id: str, event_id: str) -> Registration | None:
        result: Registration | None = await self.session.scalar(
            select(Registration).where(
                Registration.user_id == user_id, Registration.event_id == event_id
            )
        )
        return result

    async def add_registration(
        self,
        *,
        user_id: str,
        event_id: str,
        status: RegistrationStatus,
        source: str | None,
        now: datetime,
    ) -> Registration:
        registration = Registration(
            user_id=user_id,
            event_id=event_id,
            status=status,
            source=source,
            registered_at=now,
        )
        self.session.add(registration)
        await self.session.flush()
        return registration

    async def next_waiting_registration(self, event_id: str) -> Registration | None:
        result: Registration | None = await self.session.scalar(
            select(Registration)
            .where(
                Registration.event_id == event_id,
                Registration.status == RegistrationStatus.WAITING_LIST,
            )
            .order_by(Registration.registered_at.asc())
            .with_for_update()
            .limit(1)
        )
        return result

    async def list_user_registrations(
        self, *, user_id: str, future: bool, now: datetime, offset: int, limit: int
    ) -> list[Registration]:
        query = (
            select(Registration)
            .join(Event)
            .where(
                Registration.user_id == user_id,
                Registration.status != RegistrationStatus.CANCELLED,
                Event.deleted_at.is_(None),
            )
            .options(selectinload(Registration.event))
            .order_by(Event.start_at.asc() if future else Event.start_at.desc())
        )
        query = query.where(Event.start_at >= now if future else Event.start_at < now)
        return list(await self.session.scalars(query.offset(offset).limit(limit)))

    async def list_participants(self, event_id: str, offset: int, limit: int) -> list[Registration]:
        result = await self.session.scalars(
            select(Registration)
            .where(Registration.event_id == event_id)
            .options(selectinload(Registration.user))
            .order_by(Registration.registered_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result)

    async def record_view(self, event_id: str, user_id: str, now: datetime) -> None:
        self.session.add(EventView(event_id=event_id, user_id=user_id, viewed_at=now))
        await self.session.flush()

    async def statistics(self, event_id: str) -> dict[str, float | int]:
        views = int(
            await self.session.scalar(
                select(func.count(EventView.id)).where(EventView.event_id == event_id)
            )
            or 0
        )
        unique_views = int(
            await self.session.scalar(
                select(func.count(func.distinct(EventView.user_id))).where(
                    EventView.event_id == event_id
                )
            )
            or 0
        )
        rows = await self.session.execute(
            select(Registration.status, func.count(Registration.id))
            .where(Registration.event_id == event_id)
            .group_by(Registration.status)
        )
        counts = {status.value: int(count) for status, count in rows.all()}
        registrations = counts.get(RegistrationStatus.REGISTERED.value, 0) + counts.get(
            RegistrationStatus.ATTENDED.value, 0
        )
        return {
            "views": views,
            "unique_views": unique_views,
            "registrations": registrations,
            "cancelled": counts.get(RegistrationStatus.CANCELLED.value, 0),
            "attended": counts.get(RegistrationStatus.ATTENDED.value, 0),
            "absent": counts.get(RegistrationStatus.ABSENT.value, 0),
            "waiting_list": counts.get(RegistrationStatus.WAITING_LIST.value, 0),
            "view_to_registration": round(registrations / unique_views * 100, 2)
            if unique_views
            else 0.0,
        }

    async def due_publications(self, now: datetime) -> list[Event]:
        return list(
            await self.session.scalars(
                select(Event).where(
                    Event.status == EventStatus.DRAFT,
                    Event.scheduled_publish_at.is_not(None),
                    Event.scheduled_publish_at <= now,
                    Event.deleted_at.is_(None),
                )
            )
        )

    async def due_registration_closures(self, now: datetime) -> list[Event]:
        return list(
            await self.session.scalars(
                select(Event).where(
                    Event.status == EventStatus.PUBLISHED,
                    Event.registration_deadline.is_not(None),
                    Event.registration_deadline <= now,
                    Event.deleted_at.is_(None),
                )
            )
        )
