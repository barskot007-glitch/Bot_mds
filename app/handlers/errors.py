from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

from app.texts.common import GENERIC_ERROR

router = Router(name="errors")
logger = logging.getLogger(__name__)


@router.error()
async def handle_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled update error", exc_info=event.exception)
    update = event.update
    if update.callback_query:
        try:
            await update.callback_query.answer(GENERIC_ERROR, show_alert=True)
        except Exception:
            logger.debug("Не удалось ответить на callback после ошибки")
    elif update.message:
        try:
            await update.message.answer(GENERIC_ERROR)
        except Exception:
            logger.debug("Не удалось отправить сообщение после ошибки")
    return True
