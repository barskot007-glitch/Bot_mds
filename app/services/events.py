from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventStatus, RegistrationStatus
from app.models.users_events import Event, Registration, User
from app.repositories.events import EventRepository


class EventUnavailableError(ValueError):
    """Raised when an event cannot accept a registration."""


class DuplicateRegistrationError(ValueError):
    """Raised when a user already has an active event registration."""


class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = EventRepository(session)

    async def create(self, **values: Any) -> Event:
        if values["start_at"] <= values.get(
            "created_at", datetime.min.replace(tzinfo=values["start_at"].tzinfo)
        ):
            values.pop("created_at", None)
        if values.get("end_at") and values["end_at"] <= values["start_at"]:
            raise ValueError("Дата окончания должна быть позже даты начала")
        if values.get("capacity") is not None and int(values["capacity"]) < 1:
            raise ValueError("Лимит участников должен быть больше нуля")
        return await self.repository.create(**values)

    async def register(
        self,
        *,
        user: User,
        event_id: str,
        now: datetime,
        source: str | None = None,
    ) -> Registration:
        event = await self.repository.get_for_update(event_id)
        if event is None:
            raise EventUnavailableError("Мероприятие не найдено")
        if event.status not in {EventStatus.PUBLISHED, EventStatus.REGISTRATION_CLOSED}:
            raise EventUnavailableError("Регистрация на мероприятие закрыта")
        if not event.registration_enabled:
            raise EventUnavailableError("Регистрация на мероприятие закрыта")
        if event.registration_deadline and now > event.registration_deadline:
            event.status = EventStatus.REGISTRATION_CLOSED
            raise EventUnavailableError("Срок регистрации завершён")
        existing = await self.repository.get_registration(user.id, event_id)
        if existing is not None and existing.status != RegistrationStatus.CANCELLED:
            raise DuplicateRegistrationError("Вы уже зарегистрированы на это мероприятие")

        count = await self.repository.count_registered(event_id)
        status = RegistrationStatus.REGISTERED
        if event.capacity is not None and count >= event.capacity:
            status = RegistrationStatus.WAITING_LIST
            event.status = EventStatus.REGISTRATION_CLOSED

        if existing is not None:
            existing.status = status
            existing.registered_at = now
            existing.cancelled_at = None
            existing.source = source
            return existing
        try:
            return await self.repository.add_registration(
                user_id=user.id,
                event_id=event_id,
                status=status,
                source=source,
                now=now,
            )
        except IntegrityError as exc:
            raise DuplicateRegistrationError("Вы уже зарегистрированы на это мероприятие") from exc

    async def cancel(self, *, user: User, event_id: str, now: datetime) -> Registration:
        registration = await self.repository.get_registration(user.id, event_id)
        if registration is None or registration.status == RegistrationStatus.CANCELLED:
            raise ValueError("Активная регистрация не найдена")
        if registration.status in {RegistrationStatus.ATTENDED, RegistrationStatus.ABSENT}:
            raise ValueError("Завершённую регистрацию отменить нельзя")
        previous_status = registration.status
        registration.status = RegistrationStatus.CANCELLED
        registration.cancelled_at = now
        await self.session.flush()
        event = await self.repository.get_for_update(event_id)
        if (
            event
            and event.registration_enabled
            and (not event.registration_deadline or event.registration_deadline > now)
        ):
            if previous_status == RegistrationStatus.REGISTERED and event.capacity is not None:
                waiting = await self.repository.next_waiting_registration(event_id)
                if waiting is not None:
                    waiting.status = RegistrationStatus.REGISTERED
                    waiting.cancelled_at = None
            await self.session.flush()
            registered_count = await self.repository.count_registered(event_id)
            event.status = (
                EventStatus.REGISTRATION_CLOSED
                if event.capacity is not None and registered_count >= event.capacity
                else EventStatus.PUBLISHED
            )
        return registration

    async def mark_attendance(
        self,
        registration: Registration,
        *,
        attended: bool,
        now: datetime,
        comment: str | None = None,
    ) -> Registration:
        registration.attended = attended
        registration.status = RegistrationStatus.ATTENDED if attended else RegistrationStatus.ABSENT
        registration.attendance_confirmed_at = now
        registration.admin_comment = comment
        return registration

    async def publish(self, event: Event, now: datetime) -> None:
        if not event.title or not event.start_at:
            raise ValueError("Для публикации нужны название и дата начала")
        event.status = EventStatus.PUBLISHED
        event.published_at = now

    async def archive(self, event: Event) -> None:
        event.status = EventStatus.ARCHIVED
        event.registration_enabled = False

    async def cancel_event(self, event: Event) -> None:
        event.status = EventStatus.CANCELLED
        event.registration_enabled = False

    async def soft_delete(self, event: Event, now: datetime) -> None:
        event.deleted_at = now
        event.status = EventStatus.ARCHIVED
        event.registration_enabled = False

    async def record_view(self, event_id: str, user_id: str, now: datetime) -> None:
        await self.repository.record_view(event_id, user_id, now)
