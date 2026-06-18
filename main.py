from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bot import create_dispatcher
from app.config.logging import setup_logging
from app.config.settings import Settings, get_settings
from app.database.init import ensure_superadmins, ensure_text_library
from app.database.session import create_engine, create_session_factory
from app.scheduler.manager import SchedulerManager
from app.services.broadcasts import BroadcastSender
from app.web.routes import register_routes

logger = logging.getLogger(__name__)


async def create_runtime() -> tuple[
    Settings,
    AsyncEngine,
    async_sessionmaker[AsyncSession],
    Bot,
    Dispatcher,
    SchedulerManager,
]:
    settings = get_settings()
    setup_logging(settings)
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sender = BroadcastSender(bot=bot, session_factory=session_factory, settings=settings)
    dispatcher = create_dispatcher(
        settings=settings,
        session_factory=session_factory,
        sender=sender,
    )
    scheduler = SchedulerManager(
        bot=bot,
        session_factory=session_factory,
        settings=settings,
        broadcast_sender=sender,
    )
    async with session_factory() as session:
        await ensure_superadmins(session, settings.superadmin_ids)
        await ensure_text_library(session)
    return settings, engine, session_factory, bot, dispatcher, scheduler


async def run_polling() -> None:
    settings, engine, session_factory, bot, dispatcher, scheduler = await create_runtime()
    app = web.Application()
    app["session_factory"] = session_factory
    register_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    await bot.delete_webhook(drop_pending_updates=False)
    await scheduler.start()
    logger.info("Bot polling started; health endpoint on %s:%s", settings.host, settings.port)
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await scheduler.shutdown()
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


async def run_webhook() -> None:
    settings, engine, session_factory, bot, dispatcher, scheduler = await create_runtime()
    app = web.Application()
    app["session_factory"] = session_factory
    register_routes(app)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)

    async def on_startup(_: web.Application) -> None:
        await bot.set_webhook(
            settings.webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
        await scheduler.start()
        logger.info("Webhook configured: %s", settings.webhook_url)

    async def on_cleanup(_: web.Application) -> None:
        await scheduler.shutdown()
        await bot.session.close()
        await engine.dispose()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    logger.info("Webhook server started on %s:%s", settings.host, settings.port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def main() -> None:
    settings = get_settings()
    if settings.bot_mode == "webhook":
        await run_webhook()
    else:
        await run_polling()


if __name__ == "__main__":
    asyncio.run(main())
