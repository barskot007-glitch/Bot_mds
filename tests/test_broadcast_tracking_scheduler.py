from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.models.broadcast_support import Broadcast, BroadcastRecipient
from app.models.content_audit import Admin
from app.models.enums import (
    AdminRole,
    BroadcastStatus,
    EventStatus,
    RecipientStatus,
    ScheduledTaskType,
)
from app.models.users_events import Event
from app.repositories.scheduled_tasks import ScheduledTaskRepository
from app.repositories.users import UserRepository
from app.scheduler.manager import SchedulerManager
from app.services.broadcasts import BroadcastSender, BroadcastService
from app.services.tracking import TrackingService
from app.utils.time import utcnow
from tests.conftest import make_event, make_user


class ForbiddenBot:
    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        raise TelegramForbiddenError(
            method=SendMessage(chat_id=chat_id, text=text), message="bot was blocked"
        )


class NoopBot:
    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        return type("Message", (), {"message_id": 1})()


class NoopSender:
    async def run(self, broadcast_id: str) -> None:
        return None


async def test_combined_audience_selection(session: AsyncSession, settings: Settings) -> None:
    await make_user(session, telegram_id=1, country="Армения", age_group="25–34")
    await make_user(session, telegram_id=2, country="Испания", age_group="25–34")
    await make_user(session, telegram_id=3, country="Армения", age_group="18–24")
    count = await UserRepository(session).count_audience(
        {
            "subscribed_only": True,
            "countries": ["Армения"],
            "age_groups": ["25–34"],
            "activity": "active",
        },
        now=utcnow(),
        active_days=settings.active_user_days,
        new_days=settings.new_user_days,
    )
    assert count == 1


async def test_create_broadcast(session: AsyncSession, settings: Settings) -> None:
    admin = Admin(telegram_id=9001, role=AdminRole.ADMIN, is_active=True)
    session.add(admin)
    await session.flush()
    item = await BroadcastService(session, settings).create(
        title="Новости",
        text="Текст рассылки",
        audience_filter={"subscribed_only": True},
        author_admin_id=admin.id,
    )
    assert item.status == BroadcastStatus.DRAFT
    assert item.audience_filter == {"subscribed_only": True}


async def test_blocked_user_result(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session:
        user = await make_user(session, telegram_id=444)
        broadcast = Broadcast(
            title="Blocked",
            text="Test",
            audience_filter={},
            status=BroadcastStatus.SENDING,
        )
        broadcast.files = []
        broadcast.buttons = []
        session.add(broadcast)
        await session.flush()
        recipient = BroadcastRecipient(broadcast_id=broadcast.id, user_id=user.id)
        recipient.user = user
        session.add(recipient)
        await session.flush()
        sender = BroadcastSender(
            bot=cast(Any, ForbiddenBot()),
            session_factory=session_factory,
            settings=settings,
        )
        result = await sender._send_one(broadcast, recipient, None)
        assert result.status == RecipientStatus.BLOCKED


async def test_tracking_link_records_click(session: AsyncSession, settings: Settings) -> None:
    user = await make_user(session)
    service = TrackingService(session, settings.public_base_url)
    url = await service.create_url(target_url="https://example.com/final", user_id=user.id)
    token = url.rsplit("/", 1)[1]
    resolved = await service.resolve_and_record(
        token=token,
        now=utcnow(),
        ip="127.0.0.1",
        user_agent="pytest",
    )
    assert resolved == "https://example.com/final"


async def test_restore_scheduled_event_publication(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session:
        event = await make_event(session, status=EventStatus.DRAFT)
        await ScheduledTaskRepository(session).create_or_update(
            task_type=ScheduledTaskType.EVENT_PUBLICATION,
            run_at=utcnow() - timedelta(seconds=1),
            payload={"event_id": event.id},
            idempotency_key=f"publish:{event.id}",
        )
        await session.commit()
        event_id = event.id

    manager = SchedulerManager(
        bot=cast(Any, NoopBot()),
        session_factory=session_factory,
        settings=settings,
        broadcast_sender=cast(Any, NoopSender()),
    )
    await manager.process_database_tasks()

    async with session_factory() as session:
        event = await session.get(Event, event_id)
        task = await ScheduledTaskRepository(session).due(utcnow() + timedelta(days=1), limit=10)
        assert event is not None
        assert event.status == EventStatus.PUBLISHED
        assert not task
