from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.keyboards.admin import admin_menu
from app.models.content_audit import Admin
from app.texts.common import ADMIN_MENU, CANCELLED

router = Router(name="admin_common")


@router.message(Command("admin"))
async def admin_entry(message: Message, admin_model: Admin) -> None:
    await message.answer(
        "Режим администратора включён.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        f"{ADMIN_MENU}\nРоль: {admin_model.role.value}",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "adm:menu")
async def admin_main_menu(callback: CallbackQuery, state: FSMContext, admin_model: Admin) -> None:
    await state.clear()
    await callback.message.answer(
        f"{ADMIN_MENU}\nРоль: {admin_model.role.value}", reply_markup=admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "adm:cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(CANCELLED, reply_markup=admin_menu())
    await callback.answer()
