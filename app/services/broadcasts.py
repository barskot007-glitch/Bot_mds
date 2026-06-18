from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.models.broadcast_support import Broadcast, BroadcastRecipient
from app.models.enums import BroadcastStatus, RecipientStatus
from app.models.users_events import User
from app.repositories.broadcasts import BroadcastRepository
from app.repositories.users import UserRepository
from app.services.tracking import TrackingService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SendResult:
    recipient_id: str
    status: RecipientStatus
    message_id: int | None = None
    error: str | None = None


class BroadcastService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = BroadcastRepository(session)
        self.users = UserRepository(session)

    async def create(
        self,
        *,
        title: str,
        text: str,
        audience_filter: dict[str, object],
        author_admin_id: str,
    ) -> Broadcast:
        if not title.strip() or not text.strip():
            raise ValueError("Название и текст рассылки обязательны")
        if len(text) > 4096:
            raise ValueError("Текст рассылки не должен превышать 4096 символов")
        return await self.repository.create(
            title=title.strip(),
            text=text.strip(),
            audience_filter=audience_filter,
            author_admin_id=author_admin_id,
            timezone=self.settings.default_timezone,
        )

    async def count_audience(self, filters: dict[str, object], now: datetime) -> int:
        return await self.users.count_audience(
            filters,
            now=now,
            active_days=self.settings.active_user_days,
            new_days=self.settings.new_user_days,
        )

    async def prepare_recipients(self, broadcast: Broadcast, now: datetime) -> int:
        offset = 0
        page_size = 500
        while True:
            users = await self.users.audience_page(
                broadcast.audience_filter,
                now=now,
                active_days=self.settings.active_user_days,
                new_days=self.settings.new_user_days,
                offset=offset,
                limit=page_size,
            )
            if not users:
                break
            user_ids = [user.id for user in users]
            existing = set(
                await self.session.scalars(
                    select(BroadcastRecipient.user_id).where(
                        BroadcastRecipient.broadcast_id == broadcast.id,
                        BroadcastRecipient.user_id.in_(user_ids),
                    )
                )
            )
            for user in users:
                if user.id not in existing:
                    self.session.add(BroadcastRecipient(broadcast_id=broadcast.id, user_id=user.id))
            await self.session.flush()
            offset += page_size
        total = await self.users.count_audience(
            broadcast.audience_filter,
            now=now,
            active_days=self.settings.active_user_days,
            new_days=self.settings.new_user_days,
        )
        broadcast.total_recipients = total
        return total


class BroadcastSender:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def _lock_for(self, broadcast_id: str) -> asyncio.Lock:
        return self._locks.setdefault(broadcast_id, asyncio.Lock())

    def start(self, broadcast_id: str) -> asyncio.Task[None]:
        """Запустить рассылку в фоне и сохранить сильную ссылку на задачу."""
        existing = self._tasks.get(broadcast_id)
        if existing is not None and not existing.done():
            return existing
        task = asyncio.create_task(self.run(broadcast_id), name=f"broadcast-{broadcast_id}")
        self._tasks[broadcast_id] = task
        task.add_done_callback(lambda completed: self._finish_task(broadcast_id, completed))
        return task

    def _finish_task(self, broadcast_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(broadcast_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Фоновая задача рассылки %s завершилась с ошибкой",
                broadcast_id,
                exc_info=(type(error), error, error.__traceback__),
            )

    async def shutdown(self) -> None:
        """Корректно остановить активные фоновые отправки."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def run(self, broadcast_id: str) -> None:
        async with self._lock_for(broadcast_id):
            async with self.session_factory() as session:
                repo = BroadcastRepository(session)
                broadcast = await repo.get(broadcast_id, with_relations=True)
                if broadcast is None or broadcast.status in {
                    BroadcastStatus.COMPLETED,
                    BroadcastStatus.CANCELLED,
                }:
                    return
                service = BroadcastService(session, self.settings)
                await service.prepare_recipients(broadcast, utcnow())
                broadcast.status = BroadcastStatus.SENDING
                broadcast.started_at = broadcast.started_at or utcnow()
                await session.commit()

            while True:
                async with self.session_factory() as session:
                    repo = BroadcastRepository(session)
                    broadcast = await repo.get(broadcast_id, with_relations=True)
                    if broadcast is None or broadcast.status == BroadcastStatus.CANCELLED:
                        return
                    recipients = await repo.pending_recipients(
                        broadcast_id, self.settings.broadcast_batch_size
                    )
                    if not recipients:
                        broadcast.status = BroadcastStatus.COMPLETED
                        broadcast.completed_at = utcnow()
                        await session.commit()
                        logger.info("Рассылка %s завершена", broadcast_id)
                        return
                    active_broadcast: Broadcast = broadcast
                    payloads = await self._build_payloads(session, active_broadcast, recipients)
                    for recipient in recipients:
                        recipient.status = RecipientStatus.PROCESSING
                    await session.commit()

                semaphore = asyncio.Semaphore(self.settings.broadcast_concurrency)

                async def guarded_send(
                    recipient: BroadcastRecipient,
                    keyboard: InlineKeyboardMarkup | None,
                    *,
                    limiter: asyncio.Semaphore = semaphore,
                    current_broadcast: Broadcast = active_broadcast,
                ) -> SendResult:
                    async with limiter:
                        return await self._send_one(current_broadcast, recipient, keyboard)

                results = await asyncio.gather(
                    *(guarded_send(recipient, payloads[recipient.id]) for recipient in recipients)
                )

                async with self.session_factory() as session:
                    repo = BroadcastRepository(session)
                    fresh_broadcast = await repo.get(broadcast_id)
                    if fresh_broadcast is None:
                        return
                    recipient_map = {
                        recipient.id: recipient
                        for recipient in await repo.pending_recipients(
                            broadcast_id, self.settings.broadcast_batch_size * 2
                        )
                    }
                    for result in results:
                        target_recipient: BroadcastRecipient | None = recipient_map.get(
                            result.recipient_id
                        )
                        if target_recipient is None:
                            target_recipient = await session.get(
                                BroadcastRecipient, result.recipient_id
                            )
                        if target_recipient is None:
                            continue
                        target_recipient.status = result.status
                        target_recipient.telegram_message_id = result.message_id
                        target_recipient.error_message = result.error
                        target_recipient.attempts += 1
                        if result.status == RecipientStatus.SENT:
                            target_recipient.sent_at = utcnow()
                            fresh_broadcast.sent_count += 1
                        elif result.status == RecipientStatus.BLOCKED:
                            fresh_broadcast.blocked_count += 1
                            user = await session.get(User, target_recipient.user_id)
                            if user is not None:
                                user.is_blocked = True
                        else:
                            fresh_broadcast.failed_count += 1
                    await session.commit()
                await asyncio.sleep(self.settings.broadcast_delay_seconds)

    async def _build_payloads(
        self,
        session: AsyncSession,
        broadcast: Broadcast,
        recipients: list[BroadcastRecipient],
    ) -> dict[str, InlineKeyboardMarkup | None]:
        payloads: dict[str, InlineKeyboardMarkup | None] = {}
        tracking = TrackingService(session, self.settings.public_base_url)
        for recipient in recipients:
            rows: list[list[InlineKeyboardButton]] = []
            for button in broadcast.buttons:
                if button.url:
                    tracked_url = await tracking.create_url(
                        target_url=button.url,
                        user_id=recipient.user_id,
                        broadcast_id=broadcast.id,
                        button_id=button.id,
                    )
                    rows.append([InlineKeyboardButton(text=button.text, url=tracked_url)])
                elif button.callback_key:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                text=button.text,
                                callback_data=f"bc:{broadcast.id[:8]}:{button.callback_key[:24]}",
                            )
                        ]
                    )
            payloads[recipient.id] = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        await session.flush()
        return payloads

    async def _send_one(
        self,
        broadcast: Broadcast,
        recipient: BroadcastRecipient,
        keyboard: InlineKeyboardMarkup | None,
    ) -> SendResult:
        telegram_id = recipient.user.telegram_id
        for attempt in range(1, self.settings.broadcast_max_attempts + 1):
            try:
                message_id = await self._send_content(
                    telegram_id=telegram_id,
                    broadcast=broadcast,
                    keyboard=keyboard,
                )
                return SendResult(recipient.id, RecipientStatus.SENT, message_id=message_id)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after) + 0.2)
            except TelegramForbiddenError as exc:
                return SendResult(recipient.id, RecipientStatus.BLOCKED, error=str(exc)[:1000])
            except (TelegramNetworkError, TelegramServerError) as exc:
                if attempt == self.settings.broadcast_max_attempts:
                    return SendResult(recipient.id, RecipientStatus.FAILED, error=str(exc)[:1000])
                await asyncio.sleep(min(2**attempt, 30))
            except Exception as exc:
                logger.exception("Ошибка отправки получателю %s", telegram_id)
                return SendResult(recipient.id, RecipientStatus.FAILED, error=str(exc)[:1000])
        return SendResult(recipient.id, RecipientStatus.FAILED, error="Лимит попыток исчерпан")

    async def _send_content(
        self,
        *,
        telegram_id: int,
        broadcast: Broadcast,
        keyboard: InlineKeyboardMarkup | None,
    ) -> int:
        files = sorted(broadcast.files, key=lambda item: item.position)
        if not files:
            message = await self.bot.send_message(
                telegram_id,
                broadcast.text,
                parse_mode=broadcast.parse_mode,
                reply_markup=keyboard,
            )
            return message.message_id

        first = files[0]
        caption = broadcast.text if len(broadcast.text) <= 1024 else None
        media_keyboard = keyboard if caption is not None else None
        if first.file_type.value == "photo":
            message = await self.bot.send_photo(
                telegram_id,
                first.file_id,
                caption=caption,
                parse_mode=broadcast.parse_mode,
                reply_markup=media_keyboard,
            )
        else:
            message = await self.bot.send_document(
                telegram_id,
                first.file_id,
                caption=caption,
                parse_mode=broadcast.parse_mode,
                reply_markup=media_keyboard,
            )
        for attachment in files[1:]:
            if attachment.file_type.value == "photo":
                await self.bot.send_photo(telegram_id, attachment.file_id)
            else:
                await self.bot.send_document(telegram_id, attachment.file_id)
        if caption is None:
            text_message = await self.bot.send_message(
                telegram_id,
                broadcast.text,
                parse_mode=broadcast.parse_mode,
                reply_markup=keyboard,
            )
            return text_message.message_id
        return message.message_id
