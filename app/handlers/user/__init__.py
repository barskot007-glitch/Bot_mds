from aiogram import Router

from app.handlers.user import events, menu, registration, support


def build_user_router() -> Router:
    router = Router(name="user")
    router.include_router(registration.router)
    router.include_router(events.router)
    router.include_router(support.router)
    router.include_router(menu.router)
    return router
