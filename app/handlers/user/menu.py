from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.user import faq_keyboard, main_menu, settings_keyboard
from app.models.users_events import User
from app.repositories.faq import FAQRepository
from app.texts.common import MAIN_MENU

router = Router(name="user_menu")


@router.callback_query(F.data == "user:menu")
async def callback_main_menu(callback: CallbackQuery) -> None:
    await callback.message.answer(MAIN_MENU, reply_markup=main_menu())
    await callback.answer()


@router.message(F.text == "FAQ")
async def show_faq(message: Message, session: AsyncSession, user_model: User) -> None:
    if not user_model.registration_completed:
        await message.answer("Сначала выполните команду /start и завершите регистрацию.")
        return
    items = await FAQRepository(session).list_published()
    if not items:
        await message.answer("Раздел FAQ пока не заполнен.")
        return
    await message.answer("Частые вопросы", reply_markup=faq_keyboard(items))


@router.callback_query(F.data.startswith("faq:"))
async def show_faq_item(callback: CallbackQuery, session: AsyncSession) -> None:
    faq_id = callback.data.split(":", maxsplit=1)[1]
    item = await FAQRepository(session).get(faq_id)
    if item is None or not item.is_published:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.message.answer(f"<b>{item.question}</b>\n\n{item.answer}")
    await callback.answer()


@router.message(F.text == "Настройки")
async def show_settings(message: Message, user_model: User) -> None:
    await message.answer(
        f"Уведомления: {'включены' if user_model.is_subscribed else 'отключены'}",
        reply_markup=settings_keyboard(user_model.is_subscribed),
    )


@router.callback_query(F.data == "sub:toggle")
async def toggle_subscription(
    callback: CallbackQuery, session: AsyncSession, user_model: User
) -> None:
    user_model.is_subscribed = not user_model.is_subscribed
    user_model.notifications_consent = user_model.is_subscribed
    await session.flush()
    await callback.message.answer(
        f"Уведомления {'включены' if user_model.is_subscribed else 'отключены'}.",
        reply_markup=settings_keyboard(user_model.is_subscribed),
    )
    await callback.answer()
