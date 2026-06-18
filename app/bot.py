from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.handlers.admin import build_admin_router
from app.handlers.errors import router as errors_router
from app.handlers.user import build_user_router
from app.middlewares.action_logging import ActionLoggingMiddleware
from app.middlewares.database import DatabaseSessionMiddleware
from app.middlewares.rate_limit import RateLimitMiddleware
from app.middlewares.user_context import UserContextMiddleware
from app.services.broadcasts import BroadcastSender


def create_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    sender: BroadcastSender,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage(), settings=settings, sender=sender)
    dispatcher.update.outer_middleware(DatabaseSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(UserContextMiddleware(settings))
    dispatcher.update.outer_middleware(RateLimitMiddleware(settings.rate_limit_seconds))
    dispatcher.update.outer_middleware(ActionLoggingMiddleware())
    dispatcher.include_router(build_admin_router())
    dispatcher.include_router(build_user_router())
    dispatcher.include_router(errors_router)
    return dispatcher
