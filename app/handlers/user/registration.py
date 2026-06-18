from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.user import consent_keyboard, main_menu
from app.models.users_events import User
from app.services.users import UserService
from app.states.user import RegistrationStates
from app.texts.common import MAIN_MENU, WELCOME

router = Router(name="user_registration")


@router.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext,
    user_model: User,
    session: AsyncSession,
    settings: Settings,
    command: CommandObject,
) -> None:
    if command.args and not user_model.source:
        user_model.source = command.args[:255]
    if user_model.registration_completed:
        await state.clear()
        await message.answer(MAIN_MENU, reply_markup=main_menu())
        return
    await state.set_state(RegistrationStates.country)
    await message.answer(
        f"{WELCOME}\n\nУкажите страну проживания. Например: Армения.",
    )


@router.message(RegistrationStates.country, F.text)
async def registration_country(message: Message, state: FSMContext) -> None:
    country = (message.text or "").strip()
    if len(country) < 2 or len(country) > 128:
        await message.answer("Укажите корректное название страны длиной от 2 до 128 символов.")
        return
    await state.update_data(country=country)
    await state.set_state(RegistrationStates.age)
    await message.answer("Укажите ваш возраст числом от 5 до 120.")


@router.message(RegistrationStates.age, F.text)
async def registration_age(message: Message, state: FSMContext) -> None:
    try:
        age = int((message.text or "").strip())
        if age < 5 or age > 120:
            raise ValueError
    except ValueError:
        await message.answer("Возраст должен быть целым числом от 5 до 120.")
        return
    await state.update_data(age=age)
    await state.set_state(RegistrationStates.notifications_consent)
    await message.answer(
        "Согласны получать уведомления о мероприятиях и рассылки?",
        reply_markup=consent_keyboard("regnotify"),
    )


@router.callback_query(RegistrationStates.notifications_consent, F.data.startswith("regnotify:"))
async def registration_notifications(callback: CallbackQuery, state: FSMContext) -> None:
    consent = callback.data == "regnotify:yes"
    await state.update_data(notifications_consent=consent)
    await state.set_state(RegistrationStates.data_consent)
    await callback.message.answer(
        "Согласны на обработку данных, необходимых для работы бота? Без этого регистрация невозможна.",
        reply_markup=consent_keyboard("regdata"),
    )
    await callback.answer()


@router.callback_query(RegistrationStates.data_consent, F.data.startswith("regdata:"))
async def registration_data_consent(
    callback: CallbackQuery,
    state: FSMContext,
    user_model: User,
    session: AsyncSession,
    settings: Settings,
) -> None:
    accepted = callback.data == "regdata:yes"
    if not accepted:
        await callback.answer("Для регистрации требуется согласие", show_alert=True)
        return
    data = await state.get_data()
    await UserService(session, settings).complete_registration(
        user_model,
        country=str(data["country"]),
        age=int(data["age"]),
        notifications_consent=bool(data["notifications_consent"]),
        data_processing_consent=True,
    )
    await state.clear()
    await callback.message.answer(
        "Регистрация завершена.\n\nГлавное меню", reply_markup=main_menu()
    )
    await callback.answer()
