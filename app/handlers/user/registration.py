from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.user import consent_keyboard, main_menu
from app.models.users_events import User
from app.services.text_library import TextLibraryService
from app.services.users import UserService
from app.states.user import RegistrationStates
from app.utils.validators import validate_email, validate_phone

router = Router(name="user_registration")
NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁёÀ-ÖØ-öø-ÿ'’\- ]{2,128}$")


def valid_name(value: str) -> bool:
    return bool(NAME_PATTERN.fullmatch(value.strip()))


def message_phone(message: Message) -> str:
    if message.contact is not None:
        return validate_phone(message.contact.phone_number)
    return validate_phone(message.text or "")


async def show_main_menu(message: Message, session: AsyncSession) -> None:
    texts = TextLibraryService(session)
    await message.answer(await texts.get("main_menu"), reply_markup=main_menu(), parse_mode=None)


async def finish_contact_completion(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await state.clear()
    texts = TextLibraryService(session)
    await message.answer(
        await texts.get("registration_contacts_complete"),
        reply_markup=main_menu(),
        parse_mode=None,
    )


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
    texts = TextLibraryService(session)
    if user_model.registration_completed:
        await state.clear()
        if not user_model.phone:
            await state.update_data(profile_completion=True)
            await state.set_state(RegistrationStates.phone)
            await message.answer(await texts.get("registration_phone"), parse_mode=None)
            return
        if not user_model.email:
            await state.update_data(profile_completion=True)
            await state.set_state(RegistrationStates.email)
            await message.answer(await texts.get("registration_email"), parse_mode=None)
            return
        await show_main_menu(message, session)
        return
    await state.clear()
    await state.set_state(RegistrationStates.first_name)
    welcome = await texts.get("registration_welcome")
    name_prompt = await texts.get("registration_name")
    await message.answer(f"{welcome}\n\n{name_prompt}", parse_mode=None)


@router.message(RegistrationStates.first_name, F.text)
async def registration_first_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    first_name = (message.text or "").strip()
    if not valid_name(first_name):
        await message.answer(
            "Напишите только имя: от 2 до 128 букв. Допустимы пробел, дефис и апостроф."
        )
        return
    await state.update_data(first_name=first_name)
    await state.set_state(RegistrationStates.last_name)
    await message.answer(
        await TextLibraryService(session).get("registration_last_name"), parse_mode=None
    )


@router.message(RegistrationStates.last_name, F.text)
async def registration_last_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    last_name = (message.text or "").strip()
    if not valid_name(last_name):
        await message.answer(
            "Напишите только фамилию: от 2 до 128 букв. Допустимы пробел, дефис и апостроф."
        )
        return
    await state.update_data(last_name=last_name)
    await state.set_state(RegistrationStates.age)
    await message.answer(await TextLibraryService(session).get("registration_age"), parse_mode=None)


@router.message(RegistrationStates.age, F.text)
async def registration_age(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        age = int((message.text or "").strip())
        if age < 5 or age > 120:
            raise ValueError
    except ValueError:
        await message.answer("Возраст должен быть целым числом от 5 до 120.")
        return
    await state.update_data(age=age)
    await state.set_state(RegistrationStates.country)
    await message.answer(
        await TextLibraryService(session).get("registration_country"), parse_mode=None
    )


@router.message(RegistrationStates.country, F.text)
async def registration_country(message: Message, state: FSMContext, session: AsyncSession) -> None:
    country = (message.text or "").strip()
    if len(country) < 2 or len(country) > 128:
        await message.answer("Укажите корректное название страны длиной от 2 до 128 символов.")
        return
    await state.update_data(country=country)
    await state.set_state(RegistrationStates.phone)
    await message.answer(
        await TextLibraryService(session).get("registration_phone"), parse_mode=None
    )


@router.message(RegistrationStates.phone)
async def registration_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_model: User,
) -> None:
    try:
        phone = message_phone(message)
    except ValueError:
        await message.answer(
            "Укажите корректный номер телефона: можно использовать +, цифры, пробелы, скобки и дефисы."
        )
        return
    data = await state.get_data()
    if bool(data.get("profile_completion")) and user_model.email:
        user_model.phone = phone
        await session.flush()
        await finish_contact_completion(message, state, session)
        return
    await state.update_data(phone=phone)
    await state.set_state(RegistrationStates.email)
    await message.answer(
        await TextLibraryService(session).get("registration_email"), parse_mode=None
    )


@router.message(RegistrationStates.email, F.text)
async def registration_email(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_model: User,
) -> None:
    try:
        email = validate_email(message.text or "")
    except ValueError:
        await message.answer(
            "Укажите корректный адрес электронной почты, например name@example.com."
        )
        return
    data = await state.get_data()
    if bool(data.get("profile_completion")):
        phone = data.get("phone")
        if phone:
            user_model.phone = str(phone)
        user_model.email = email
        await session.flush()
        await finish_contact_completion(message, state, session)
        return
    await state.update_data(email=email)
    await state.set_state(RegistrationStates.participation_history)
    await message.answer(
        await TextLibraryService(session).get("registration_history"), parse_mode=None
    )


@router.message(RegistrationStates.participation_history, F.text)
async def registration_history(message: Message, state: FSMContext, session: AsyncSession) -> None:
    history = (message.text or "").strip()
    if len(history) < 2 or len(history) > 2000:
        await message.answer("Ответ должен содержать от 2 до 2000 символов.")
        return
    await state.update_data(participation_history=history)
    await state.set_state(RegistrationStates.notifications_consent)
    await message.answer(
        await TextLibraryService(session).get("registration_notifications"),
        reply_markup=consent_keyboard("regnotify", yes_text="Разрешаю", no_text="Запрещаю"),
        parse_mode=None,
    )


@router.callback_query(RegistrationStates.notifications_consent, F.data.startswith("regnotify:"))
async def registration_notifications(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    consent = callback.data == "regnotify:yes"
    await state.update_data(notifications_consent=consent)
    await state.set_state(RegistrationStates.data_consent)
    await callback.message.answer(
        await TextLibraryService(session).get("registration_data_consent"),
        reply_markup=consent_keyboard("regdata", yes_text="Согласен", no_text="Не согласен"),
        parse_mode=None,
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
        first_name=str(data["first_name"]),
        last_name=str(data["last_name"]),
        country=str(data["country"]),
        phone=str(data["phone"]),
        email=str(data["email"]),
        age=int(data["age"]),
        participation_history=str(data["participation_history"]),
        notifications_consent=bool(data["notifications_consent"]),
        data_processing_consent=True,
    )
    await state.clear()
    texts = TextLibraryService(session)
    await callback.message.answer(
        await texts.get("registration_complete"),
        reply_markup=main_menu(),
        parse_mode=None,
    )
    await callback.answer()
