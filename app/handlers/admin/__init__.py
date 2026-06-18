from aiogram import Router

from app.filters.admin import AdminFilter
from app.handlers.admin import broadcasts, common, events, faq, management, support, texts


def build_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(AdminFilter())
    router.callback_query.filter(AdminFilter())
    router.include_router(common.router)
    router.include_router(events.router)
    router.include_router(broadcasts.router)
    router.include_router(support.router)
    router.include_router(faq.router)
    router.include_router(texts.router)
    router.include_router(management.router)
    return router
