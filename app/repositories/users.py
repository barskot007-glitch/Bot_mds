from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RegistrationStatus
from app.models.users_events import Registration, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result: User | None = await self.session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result

    async def get(self, user_id: str) -> User | None:
        return await self.session.get(User, user_id)

    async def create_or_update_telegram_profile(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
        now: datetime,
        source: str | None = None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                registered_at=now,
                last_activity_at=now,
                source=source,
            )
            self.session.add(user)
            await self.session.flush()
            return user
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.language_code = language_code
        user.last_activity_at = now
        if source and not user.source:
            user.source = source
        return user

    async def complete_registration(
        self,
        user: User,
        *,
        country: str,
        age: int,
        age_group: str,
        notifications_consent: bool,
        data_processing_consent: bool,
    ) -> User:
        user.country = country
        user.age = age
        user.age_group = age_group
        user.notifications_consent = notifications_consent
        user.data_processing_consent = data_processing_consent
        user.is_subscribed = notifications_consent
        user.registration_completed = True
        await self.session.flush()
        return user

    async def set_subscription(self, user_id: str, subscribed: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(is_subscribed=subscribed)
        )

    async def set_blocked(self, user_id: str, blocked: bool = True) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(is_blocked=blocked)
        )

    async def list_paginated(self, offset: int, limit: int) -> list[User]:
        result = await self.session.scalars(
            select(User).order_by(User.registered_at.desc()).offset(offset).limit(limit)
        )
        return list(result)

    def audience_query(
        self,
        filters: dict[str, Any],
        *,
        now: datetime,
        active_days: int,
        new_days: int,
    ) -> Select[tuple[User]]:
        query = select(User).where(
            User.registration_completed.is_(True), User.is_blocked.is_(False)
        )
        if filters.get("subscribed_only", True):
            query = query.where(User.is_subscribed.is_(True))
        countries = filters.get("countries") or []
        if countries:
            query = query.where(User.country.in_(countries))
        age_groups = filters.get("age_groups") or []
        if age_groups:
            query = query.where(User.age_group.in_(age_groups))
        registered_from = filters.get("registered_from")
        registered_to = filters.get("registered_to")
        if registered_from:
            query = query.where(User.registered_at >= datetime.fromisoformat(registered_from))
        if registered_to:
            query = query.where(User.registered_at <= datetime.fromisoformat(registered_to))
        activity = filters.get("activity")
        if activity == "active":
            query = query.where(User.last_activity_at >= now - timedelta(days=active_days))
        elif activity == "inactive":
            query = query.where(User.last_activity_at < now - timedelta(days=active_days))
        elif activity == "new":
            days = int(filters.get("new_days", new_days))
            query = query.where(User.registered_at >= now - timedelta(days=days))
        event_id = filters.get("event_id")
        participation = filters.get("participation")
        if event_id or participation:
            reg_query = select(Registration.user_id)
            if event_id:
                reg_query = reg_query.where(Registration.event_id == event_id)
            if participation == "registered":
                reg_query = reg_query.where(
                    Registration.status.in_(
                        [RegistrationStatus.REGISTERED, RegistrationStatus.WAITING_LIST]
                    )
                )
            elif participation == "attended":
                reg_query = reg_query.where(Registration.status == RegistrationStatus.ATTENDED)
            elif participation == "any":
                reg_query = reg_query.where(Registration.status != RegistrationStatus.CANCELLED)
            query = query.where(User.id.in_(reg_query))
        return query.order_by(User.id)

    async def count_audience(
        self,
        filters: dict[str, Any],
        *,
        now: datetime,
        active_days: int,
        new_days: int,
    ) -> int:
        query = self.audience_query(filters, now=now, active_days=active_days, new_days=new_days)
        count_query = select(func.count()).select_from(query.subquery())
        return int(await self.session.scalar(count_query) or 0)

    async def audience_page(
        self,
        filters: dict[str, Any],
        *,
        now: datetime,
        active_days: int,
        new_days: int,
        offset: int,
        limit: int,
    ) -> list[User]:
        query = self.audience_query(filters, now=now, active_days=active_days, new_days=new_days)
        result = await self.session.scalars(query.offset(offset).limit(limit))
        return list(result)

    async def statistics(self, *, now: datetime, active_days: int, new_days: int) -> dict[str, int]:
        active_since = now - timedelta(days=active_days)
        new_since = now - timedelta(days=new_days)
        row = (
            await self.session.execute(
                select(
                    func.count(User.id),
                    func.count(User.id).filter(User.registered_at >= new_since),
                    func.count(User.id).filter(User.last_activity_at >= active_since),
                    func.count(User.id).filter(User.last_activity_at < active_since),
                    func.count(User.id).filter(User.is_subscribed.is_(True)),
                    func.count(User.id).filter(User.is_subscribed.is_(False)),
                    func.count(User.id).filter(User.is_blocked.is_(True)),
                )
            )
        ).one()
        keys = ["total", "new", "active", "inactive", "subscribed", "unsubscribed", "blocked"]
        return {key: int(value or 0) for key, value in zip(keys, row, strict=True)}

    async def distribution(self, field: str) -> list[tuple[str, int]]:
        column = User.country if field == "country" else User.age_group
        result = await self.session.execute(
            select(column, func.count(User.id))
            .where(column.is_not(None))
            .group_by(column)
            .order_by(func.count(User.id).desc())
        )
        return [(str(name), int(count)) for name, count in result.all()]

    async def registration_dynamics(self, *, since: datetime) -> list[tuple[str, int]]:
        day = func.date(User.registered_at)
        result = await self.session.execute(
            select(day, func.count(User.id))
            .where(User.registered_at >= since)
            .group_by(day)
            .order_by(day.asc())
        )
        return [(str(value), int(count)) for value, count in result.all()]
