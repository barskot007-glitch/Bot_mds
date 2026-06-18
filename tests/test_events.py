from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventStatus, RegistrationStatus
from app.services.analytics import AnalyticsService
from app.services.events import DuplicateRegistrationError, EventService
from app.utils.time import utcnow
from tests.conftest import make_event, make_user


async def test_create_event(session: AsyncSession) -> None:
    event = await make_event(session, title="Конференция")
    assert event.title == "Конференция"
    assert event.status == EventStatus.PUBLISHED


async def test_register_for_event(session: AsyncSession) -> None:
    user = await make_user(session)
    event = await make_event(session)
    registration = await EventService(session).register(
        user=user, event_id=event.id, now=utcnow(), source="test"
    )
    assert registration.status == RegistrationStatus.REGISTERED


async def test_duplicate_registration_is_rejected(session: AsyncSession) -> None:
    user = await make_user(session)
    event = await make_event(session)
    service = EventService(session)
    await service.register(user=user, event_id=event.id, now=utcnow())
    with pytest.raises(DuplicateRegistrationError):
        await service.register(user=user, event_id=event.id, now=utcnow())


async def test_capacity_creates_waiting_list(session: AsyncSession) -> None:
    first = await make_user(session, telegram_id=101)
    second = await make_user(session, telegram_id=102)
    event = await make_event(session, capacity=1)
    service = EventService(session)
    first_registration = await service.register(user=first, event_id=event.id, now=utcnow())
    second_registration = await service.register(user=second, event_id=event.id, now=utcnow())
    assert first_registration.status == RegistrationStatus.REGISTERED
    assert second_registration.status == RegistrationStatus.WAITING_LIST
    assert event.status == EventStatus.REGISTRATION_CLOSED


async def test_event_statistics(session: AsyncSession, settings) -> None:
    user = await make_user(session)
    event = await make_event(session, capacity=10)
    service = EventService(session)
    await service.record_view(event.id, user.id, utcnow())
    await service.register(user=user, event_id=event.id, now=utcnow())
    stats = await AnalyticsService(session, settings).event_statistics(event.id)
    assert stats["views"] == 1
    assert stats["unique_views"] == 1
    assert stats["registrations"] == 1
    assert stats["view_to_registration"] == 100.0
    assert stats["occupancy"] == 10.0


async def test_cancellation_promotes_waiting_list(session: AsyncSession) -> None:
    first = await make_user(session, telegram_id=201)
    second = await make_user(session, telegram_id=202)
    event = await make_event(session, capacity=1)
    service = EventService(session)
    first_registration = await service.register(user=first, event_id=event.id, now=utcnow())
    waiting_registration = await service.register(user=second, event_id=event.id, now=utcnow())

    await service.cancel(user=first, event_id=event.id, now=utcnow())

    assert first_registration.status == RegistrationStatus.CANCELLED
    assert waiting_registration.status == RegistrationStatus.REGISTERED
    assert event.status == EventStatus.REGISTRATION_CLOSED
