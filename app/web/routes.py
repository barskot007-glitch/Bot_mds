from __future__ import annotations

from aiohttp import web
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.tracking import TrackingService
from app.utils.time import utcnow


async def health(request: web.Request) -> web.Response:
    session_factory: async_sessionmaker[AsyncSession] = request.app["session_factory"]
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return web.json_response({"status": "error", "database": "unavailable"}, status=503)
    return web.json_response({"status": "ok", "database": "available"})


async def tracking_redirect(request: web.Request) -> web.StreamResponse:
    token = request.match_info["token"]
    session_factory: async_sessionmaker[AsyncSession] = request.app["session_factory"]
    async with session_factory() as session:
        target = await TrackingService(session, "").resolve_and_record(
            token=token,
            now=utcnow(),
            ip=request.remote,
            user_agent=request.headers.get("User-Agent"),
        )
        await session.commit()
    if target is None:
        raise web.HTTPNotFound(text="Ссылка недействительна или устарела")
    raise web.HTTPFound(location=target)


def register_routes(app: web.Application) -> None:
    app.router.add_get("/health", health)
    app.router.add_get("/t/{token}", tracking_redirect)
