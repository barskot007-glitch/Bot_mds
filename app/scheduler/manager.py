from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.models.content_audit import ScheduledTask
from app.models.enums import (
    BroadcastStatus,
    EventStatus,
    RegistrationStatus,
    ScheduledTaskStatus,
    ScheduledTaskType,
)
from app.models.users_events import Event, EventReminder, Registration
from app.repositories.broadcasts import BroadcastRepository
from app.repositories.events import EventRepository
from app.repositories.scheduled_tasks import ScheduledTaskRepository
from app.services.broadcasts import BroadcastSender
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        broadcast_sender: BroadcastSender,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self.broadcast_sender = broadcast_sender
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self.process_due_items,
            "interval",
            seconds=20,
            id="process-due-items",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.process_event_reminders,
            "interval",
            seconds=60,
            id="process-event-reminders",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.cleanup_finished_tasks,
            "interval",
            hours=24,
            id="cleanup-finished-tasks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        await self.restore_active_work()
        logger.info("Scheduler запущен")

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        await self.broadcast_sender.shutdown()
        logger.info("Scheduler остановлен")

    def _start_broadcast(self, broadcast_id: str) -> None:
        self.broadcast_sender.start(broadcast_id)

    async def restore_active_work(self) -> None:
        async with self.session_factory() as session:
            repo = BroadcastRepository(session)
            for broadcast in await repo.resumable():
                self._start_broadcast(broadcast.id)
            for broadcast in await repo.due(utcnow()):
                broadcast.status = BroadcastStatus.SENDING
                self._start_broadcast(broadcast.id)
            await session.commit()
        await self.process_database_tasks()

    async def process_due_items(self) -> None:
        now = utcnow()
        async with self.session_factory() as session:
            broadcast_repo = BroadcastRepository(session)
            for broadcast in await broadcast_repo.due(now):
                broadcast.status = BroadcastStatus.SENDING
                self._start_broadcast(broadcast.id)

            event_repo = EventRepository(session)
            for event in await event_repo.due_publications(now):
                event.status = EventStatus.PUBLISHED
                event.published_at = now
                logger.info("Автоматически опубликовано мероприятие %s", event.id)
            for event in await event_repo.due_registration_closures(now):
                event.status = EventStatus.REGISTRATION_CLOSED
                event.registration_enabled = False
                logger.info("Регистрация автоматически закрыта для %s", event.id)

            completed = list(
                await session.scalars(
                    select(Event).where(
                        Event.status.in_([EventStatus.PUBLISHED, EventStatus.REGISTRATION_CLOSED]),
                        Event.end_at.is_not(None),
                        Event.end_at <= now,
                        Event.deleted_at.is_(None),
                    )
                )
            )
            for event in completed:
                event.status = EventStatus.COMPLETED
                event.registration_enabled = False
            await session.commit()
        await self.process_database_tasks()

    async def process_database_tasks(self) -> None:
        now = utcnow()
        async with self.session_factory() as session:
            tasks = await ScheduledTaskRepository(session).due(now)
            for task in tasks:
                task.status = ScheduledTaskStatus.RUNNING
                task.locked_at = now
                task.attempts += 1
                try:
                    if task.task_type == ScheduledTaskType.BROADCAST:
                        broadcast_id = str(task.payload["broadcast_id"])
                        self._start_broadcast(broadcast_id)
                    elif task.task_type == ScheduledTaskType.EVENT_PUBLICATION:
                        event = await session.get(Event, str(task.payload["event_id"]))
                        if event:
                            event.status = EventStatus.PUBLISHED
                            event.published_at = now
                    elif task.task_type == ScheduledTaskType.REGISTRATION_CLOSE:
                        event = await session.get(Event, str(task.payload["event_id"]))
                        if event:
                            event.status = EventStatus.REGISTRATION_CLOSED
                            event.registration_enabled = False
                    task.status = ScheduledTaskStatus.COMPLETED
                    task.completed_at = now
                    task.error_message = None
                except Exception as exc:
                    task.status = ScheduledTaskStatus.FAILED
                    task.error_message = str(exc)[:2000]
                    logger.exception("Ошибка scheduled task %s", task.id)
            await session.commit()

    async def process_event_reminders(self) -> None:
        now = utcnow()
        async with self.session_factory() as session:
            reminders = list(
                await session.scalars(
                    select(EventReminder)
                    .join(Event)
                    .where(
                        EventReminder.enabled.is_(True),
                        EventReminder.last_sent_at.is_(None),
                        Event.status.in_([EventStatus.PUBLISHED, EventStatus.REGISTRATION_CLOSED]),
                        Event.start_at > now,
                        Event.start_at <= now + timedelta(days=30),
                        Event.deleted_at.is_(None),
                    )
                    .options(selectinload(EventReminder.event))
                )
            )
            for reminder in reminders:
                trigger_at = reminder.event.start_at - timedelta(minutes=reminder.minutes_before)
                if trigger_at > now:
                    continue
                registrations = list(
                    await session.scalars(
                        select(Registration)
                        .where(
                            Registration.event_id == reminder.event_id,
                            Registration.status == RegistrationStatus.REGISTERED,
                        )
                        .options(selectinload(Registration.user))
                    )
                )
                for registration in registrations:
                    user = registration.user
                    if user.is_blocked or not user.is_subscribed:
                        continue
                    try:
                        await self.bot.send_message(
                            user.telegram_id,
                            f"Напоминание: мероприятие «{reminder.event.title}» начнётся "
                            f"через {reminder.minutes_before} минут.",
                        )
                        await asyncio.sleep(0.04)
                    except TelegramRetryAfter as exc:
                        await asyncio.sleep(float(exc.retry_after) + 0.2)
                    except TelegramForbiddenError:
                        user.is_blocked = True
                    except Exception:
                        logger.exception(
                            "Ошибка напоминания event=%s user=%s",
                            reminder.event_id,
                            user.telegram_id,
                        )
                reminder.last_sent_at = now
            await session.commit()

    async def cleanup_finished_tasks(self) -> None:
        cutoff = utcnow() - timedelta(days=30)
        async with self.session_factory() as session:
            tasks = list(
                await session.scalars(
                    select(ScheduledTask).where(
                        ScheduledTask.status.in_(
                            [ScheduledTaskStatus.COMPLETED, ScheduledTaskStatus.CANCELLED]
                        ),
                        ScheduledTask.updated_at < cutoff,
                    )
                )
            )
            for task in tasks:
                await session.delete(task)
            await session.commit()
            logger.info("Удалено старых scheduled tasks: %s", len(tasks))
