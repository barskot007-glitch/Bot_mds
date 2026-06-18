from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.user import (
    event_card_keyboard,
    event_card_text,
    events_list_keyboard,
    registrations_keyboard,
)
from app.models.users_events import EventFile, User
from app.repositories.events import EventRepository
from app.services.events import DuplicateRegistrationError, EventService, EventUnavailableError
from app.services.tracking import TrackingService
from app.utils.time import utcnow

router = Router(name="user_events")
PAGE_SIZE = 6


async def send_events_list(
    *,
    target: Message,
    session: AsyncSession,
    page: int,
    settings: Settings,
    filter_key: str = "all",
) -> None:
    now = utcnow()
    events = await EventRepository(session).list_published(
        now=now,
        offset=page * PAGE_SIZE,
        limit=PAGE_SIZE + 1,
        registration_open_only=filter_key == "open",
        date_to=now + timedelta(days=7) if filter_key == "week" else None,
    )
    has_next = len(events) > PAGE_SIZE
    visible = events[:PAGE_SIZE]
    if not visible:
        await target.answer("Актуальных мероприятий пока нет.")
        return
    await target.answer(
        "Актуальные мероприятия",
        reply_markup=events_list_keyboard(visible, page, has_next, filter_key),
    )


@router.message(F.text.in_({"Мероприятия", "📅 Мероприятия"}))
async def events_menu(message: Message, session: AsyncSession, settings: Settings) -> None:
    await send_events_list(
        target=message, session=session, page=0, settings=settings, filter_key="all"
    )


@router.callback_query(F.data == "menu:events")
async def events_menu_callback(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await send_events_list(
        target=callback.message, session=session, page=0, settings=settings, filter_key="all"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("evflt:"))
async def events_filter(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    filter_key = callback.data.split(":", 1)[1]
    if filter_key not in {"all", "open", "week"}:
        filter_key = "all"
    await send_events_list(
        target=callback.message,
        session=session,
        page=0,
        settings=settings,
        filter_key=filter_key,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("evl:"))
async def events_page(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    parts = callback.data.split(":")
    if len(parts) == 3:
        _, filter_key, raw_page = parts
    else:
        filter_key, raw_page = "all", parts[-1]
    page = max(0, int(raw_page))
    await send_events_list(
        target=callback.message,
        session=session,
        page=page,
        settings=settings,
        filter_key=filter_key,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ev:"))
async def event_details(
    callback: CallbackQuery,
    session: AsyncSession,
    user_model: User,
    settings: Settings,
    bot: Bot,
) -> None:
    event_id = callback.data.split(":", maxsplit=1)[1]
    repo = EventRepository(session)
    event = await repo.get(event_id, with_relations=True)
    if event is None:
        await callback.answer("Мероприятие не найдено", show_alert=True)
        return
    registration = await repo.get_registration(user_model.id, event_id)
    await EventService(session).record_view(event.id, user_model.id, utcnow())
    tracking = TrackingService(session, settings.public_base_url)
    tracked_links: list[tuple[str, str]] = []
    if event.details_url:
        tracked_links.append(
            (
                "Узнать подробнее",
                await tracking.create_url(
                    target_url=event.details_url,
                    user_id=user_model.id,
                    event_id=event.id,
                ),
            )
        )
    for link in event.links:
        tracked_links.append(
            (
                link.title,
                await tracking.create_url(
                    target_url=link.url,
                    user_id=user_model.id,
                    event_id=event.id,
                ),
            )
        )
    if event.map_url:
        tracked_links.append(
            (
                "Открыть карту",
                await tracking.create_url(
                    target_url=event.map_url,
                    user_id=user_model.id,
                    event_id=event.id,
                ),
            )
        )
    text = event_card_text(event, registration, settings.default_timezone)
    keyboard = event_card_keyboard(event, registration, tracked_links)
    photo = next((item for item in event.files if item.file_type.value == "photo"), None)
    if photo and len(text) <= 1024:
        await bot.send_photo(
            callback.from_user.id,
            photo.file_id,
            caption=text,
            reply_markup=keyboard,
        )
    elif photo:
        await bot.send_photo(callback.from_user.id, photo.file_id)
        await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)
    else:
        await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("evf:"))
async def send_event_file(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    file_id = callback.data.split(":", maxsplit=1)[1]
    file = await session.get(EventFile, file_id)
    if file is None:
        await callback.answer("Файл не найден", show_alert=True)
        return
    if file.file_type.value == "photo":
        await bot.send_photo(callback.from_user.id, file.file_id, caption=file.caption)
    else:
        await bot.send_document(callback.from_user.id, file.file_id, caption=file.caption)
    await callback.answer()


@router.callback_query(F.data.startswith("evr:"))
async def register_event(callback: CallbackQuery, session: AsyncSession, user_model: User) -> None:
    event_id = callback.data.split(":", maxsplit=1)[1]
    try:
        registration = await EventService(session).register(
            user=user_model,
            event_id=event_id,
            now=utcnow(),
            source="telegram_event_card",
        )
    except (EventUnavailableError, DuplicateRegistrationError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    message = (
        "Вы добавлены в лист ожидания."
        if registration.status.value == "waiting_list"
        else "Регистрация подтверждена."
    )
    await callback.answer(message, show_alert=True)


@router.callback_query(F.data.startswith("evc:"))
async def cancel_event_registration(
    callback: CallbackQuery, session: AsyncSession, user_model: User
) -> None:
    event_id = callback.data.split(":", maxsplit=1)[1]
    try:
        await EventService(session).cancel(user=user_model, event_id=event_id, now=utcnow())
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Регистрация отменена", show_alert=True)


@router.message(F.text == "Мои регистрации")
async def my_registrations(message: Message, session: AsyncSession, user_model: User) -> None:
    items = await EventRepository(session).list_user_registrations(
        user_id=user_model.id, future=True, now=utcnow(), offset=0, limit=30
    )
    if not items:
        await message.answer("У вас нет предстоящих мероприятий.")
        return
    await message.answer("Ваши предстоящие мероприятия", reply_markup=registrations_keyboard(items))


@router.message(F.text == "История участия")
async def participation_history(message: Message, session: AsyncSession, user_model: User) -> None:
    items = await EventRepository(session).list_user_registrations(
        user_id=user_model.id, future=False, now=utcnow(), offset=0, limit=30
    )
    if not items:
        await message.answer("История участия пока пуста.")
        return
    await message.answer("История участия", reply_markup=registrations_keyboard(items))


@router.callback_query(F.data == "menu:registrations")
async def my_registrations_callback(
    callback: CallbackQuery, session: AsyncSession, user_model: User
) -> None:
    items = await EventRepository(session).list_user_registrations(
        user_id=user_model.id, future=True, now=utcnow(), offset=0, limit=30
    )
    if not items:
        await callback.message.answer("У Вас нет предстоящих мероприятий.")
    else:
        await callback.message.answer(
            "Ваши предстоящие мероприятия", reply_markup=registrations_keyboard(items)
        )
    await callback.answer()


@router.callback_query(F.data == "menu:history")
async def participation_history_callback(
    callback: CallbackQuery, session: AsyncSession, user_model: User
) -> None:
    items = await EventRepository(session).list_user_registrations(
        user_id=user_model.id, future=False, now=utcnow(), offset=0, limit=30
    )
    if not items:
        await callback.message.answer("История участия пока пуста.")
    else:
        await callback.message.answer("История участия", reply_markup=registrations_keyboard(items))
    await callback.answer()
