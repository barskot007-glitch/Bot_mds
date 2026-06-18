from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.filters.admin import AdminFilter
from app.keyboards.admin import (
    cancel_keyboard,
    confirm_delete,
    event_actions,
    event_edit_fields,
    event_media_keyboard,
    events_keyboard,
    participants_keyboard,
    skip_cancel_keyboard,
)
from app.keyboards.user import event_card_text
from app.models.content_audit import Admin
from app.models.enums import EventStatus, FileType
from app.models.users_events import Event, EventFile, EventLink, EventReminder, Registration
from app.repositories.admins import AdminRepository
from app.repositories.events import EventRepository
from app.services.analytics import AnalyticsService
from app.services.broadcasts import BroadcastSender, BroadcastService
from app.services.events import EventService
from app.services.export import ExportService
from app.services.permissions import PermissionService
from app.states.admin import AdminEventStates
from app.utils.time import format_datetime, parse_local_datetime, utcnow
from app.utils.validators import validate_url

router = Router(name="admin_events")
router.message.filter(AdminFilter("events"))
router.callback_query.filter(AdminFilter("events"))
PAGE_SIZE = 8
EVENT_FIELD_KEYS = {
    "t": "title",
    "s": "short_description",
    "d": "full_description",
    "b": "start_at",
    "e": "end_at",
    "c": "country",
    "y": "city",
    "a": "address",
    "l": "capacity",
    "u": "details_url",
    "m": "map_url",
    "x": "latitude",
    "o": "longitude",
    "z": "timezone",
    "r": "registration_deadline",
    "p": "scheduled_publish_at",
}


def event_admin_text(event: Event, settings: Settings) -> str:
    return event_card_text(event, None, settings.default_timezone) + (
        f"\nID: <code>{event.id}</code>"
        f"\nРегистрация: {'включена' if event.registration_enabled else 'выключена'}"
        f"\nДедлайн: {format_datetime(event.registration_deadline, settings.default_timezone)}"
        f"\nАвтопубликация: {format_datetime(event.scheduled_publish_at, settings.default_timezone)}"
    )


async def require_events(session: AsyncSession, settings: Settings, admin: Admin) -> None:
    if not PermissionService.has_permission(admin, "events"):
        raise PermissionError("Недостаточно прав для управления мероприятиями")


async def show_event_card(
    message: Message, session: AsyncSession, settings: Settings, event_id: str
) -> None:
    event = await EventRepository(session).get(event_id, with_relations=True)
    if event is None:
        await message.answer("Мероприятие не найдено.")
        return
    await message.answer(event_admin_text(event, settings), reply_markup=event_actions(event))


@router.callback_query(F.data == "adm:events")
@router.callback_query(F.data.startswith("aevl:"))
async def list_events(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    await require_events(session, settings, admin_model)
    page = int(callback.data.split(":")[1]) if callback.data.startswith("aevl:") else 0
    items = await EventRepository(session).list_admin(page * PAGE_SIZE, PAGE_SIZE + 1)
    await callback.message.answer(
        "Управление мероприятиями",
        reply_markup=events_keyboard(items[:PAGE_SIZE], page, len(items) > PAGE_SIZE),
    )
    await callback.answer()


@router.callback_query(F.data == "aev:new")
async def create_event_start(
    callback: CallbackQuery, state: FSMContext, admin_model: Admin
) -> None:
    if not PermissionService.has_permission(admin_model, "events"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminEventStates.title)
    await callback.message.answer("Введите название мероприятия.", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminEventStates.title, F.text)
async def create_event_title(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not 3 <= len(value) <= 255:
        await message.answer("Название должно содержать от 3 до 255 символов.")
        return
    await state.update_data(title=value)
    await state.set_state(AdminEventStates.short_description)
    await message.answer(
        "Введите краткое описание до 1024 символов.", reply_markup=cancel_keyboard()
    )


@router.message(AdminEventStates.short_description, F.text)
async def create_event_short(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 1024:
        await message.answer("Краткое описание обязательно и не должно превышать 1024 символа.")
        return
    await state.update_data(short_description=value)
    await state.set_state(AdminEventStates.full_description)
    await message.answer(
        "Введите полное описание до 4096 символов.", reply_markup=cancel_keyboard()
    )


@router.message(AdminEventStates.full_description, F.text)
async def create_event_full(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 4096:
        await message.answer("Описание обязательно и не должно превышать 4096 символов.")
        return
    await state.update_data(full_description=value)
    await state.set_state(AdminEventStates.start_at)
    await message.answer(
        "Введите дату и время начала в формате ДД.ММ.ГГГГ ЧЧ:ММ.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminEventStates.start_at, F.text)
async def create_event_start_at(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        value = parse_local_datetime(message.text or "", settings.default_timezone)
        if value <= utcnow():
            raise ValueError("Дата начала должна быть в будущем")
    except ValueError as exc:
        await message.answer(f"Некорректная дата. {exc}")
        return
    await state.update_data(start_at=value.isoformat())
    await state.set_state(AdminEventStates.end_at)
    await message.answer(
        "Введите дату окончания в том же формате или нажмите «Пропустить».",
        reply_markup=skip_cancel_keyboard(),
    )


@router.message(AdminEventStates.end_at, F.text)
async def create_event_end_at(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        value = parse_local_datetime(message.text or "", settings.default_timezone)
        data = await state.get_data()
        if value <= parse_local_datetime_from_iso(str(data["start_at"])):
            raise ValueError("Дата окончания должна быть позже начала")
    except ValueError as exc:
        await message.answer(f"Некорректная дата. {exc}")
        return
    await state.update_data(end_at=value.isoformat())
    await ask_country(message, state)


def parse_local_datetime_from_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


async def ask_country(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminEventStates.country)
    await message.answer("Укажите страну или пропустите.", reply_markup=skip_cancel_keyboard())


@router.callback_query(AdminEventStates.end_at, F.data == "adm:skip")
async def skip_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(end_at=None)
    await ask_country(callback.message, state)
    await callback.answer()


@router.message(AdminEventStates.country, F.text)
async def create_event_country(message: Message, state: FSMContext) -> None:
    await state.update_data(country=(message.text or "").strip()[:128])
    await state.set_state(AdminEventStates.city)
    await message.answer("Укажите город или пропустите.", reply_markup=skip_cancel_keyboard())


@router.callback_query(AdminEventStates.country, F.data == "adm:skip")
async def skip_country(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(country=None)
    await state.set_state(AdminEventStates.city)
    await callback.message.answer(
        "Укажите город или пропустите.", reply_markup=skip_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminEventStates.city, F.text)
async def create_event_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=(message.text or "").strip()[:128])
    await state.set_state(AdminEventStates.address)
    await message.answer("Укажите адрес или пропустите.", reply_markup=skip_cancel_keyboard())


@router.callback_query(AdminEventStates.city, F.data == "adm:skip")
async def skip_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=None)
    await state.set_state(AdminEventStates.address)
    await callback.message.answer(
        "Укажите адрес или пропустите.", reply_markup=skip_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminEventStates.address, F.text)
async def create_event_address(message: Message, state: FSMContext) -> None:
    await state.update_data(address=(message.text or "").strip()[:512])
    await state.set_state(AdminEventStates.capacity)
    await message.answer(
        "Укажите лимит участников числом или пропустите.", reply_markup=skip_cancel_keyboard()
    )


@router.callback_query(AdminEventStates.address, F.data == "adm:skip")
async def skip_address(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(address=None)
    await state.set_state(AdminEventStates.capacity)
    await callback.message.answer(
        "Укажите лимит участников числом или пропустите.", reply_markup=skip_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminEventStates.capacity, F.text)
async def create_event_capacity(message: Message, state: FSMContext) -> None:
    try:
        capacity = int(message.text or "")
        if capacity < 1:
            raise ValueError
    except ValueError:
        await message.answer("Лимит должен быть положительным целым числом.")
        return
    await state.update_data(capacity=capacity)
    await state.set_state(AdminEventStates.details_url)
    await message.answer(
        "Укажите ссылку «Узнать подробнее» или пропустите.", reply_markup=skip_cancel_keyboard()
    )


@router.callback_query(AdminEventStates.capacity, F.data == "adm:skip")
async def skip_capacity(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(capacity=None)
    await state.set_state(AdminEventStates.details_url)
    await callback.message.answer(
        "Укажите ссылку «Узнать подробнее» или пропустите.", reply_markup=skip_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminEventStates.details_url, F.text)
async def create_event_url(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        url = validate_url(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(details_url=url)
    await show_create_preview(message, state, settings)


@router.callback_query(AdminEventStates.details_url, F.data == "adm:skip")
async def skip_url(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.update_data(details_url=None)
    await show_create_preview(callback.message, state, settings)
    await callback.answer()


async def show_create_preview(message: Message, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    await state.set_state(AdminEventStates.confirm)
    text = (
        f"<b>Предпросмотр</b>\n\n"
        f"{data['title']}\n{data['full_description']}\n\n"
        f"Начало: {format_datetime(parse_local_datetime_from_iso(str(data['start_at'])), settings.default_timezone)}\n"
        f"Окончание: {format_datetime(parse_local_datetime_from_iso(str(data['end_at'])) if data.get('end_at') else None, settings.default_timezone)}\n"
        f"Место: {', '.join(str(data.get(key)) for key in ('country', 'city', 'address') if data.get(key)) or 'не указано'}\n"
        f"Лимит: {data.get('capacity') or 'без лимита'}"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить черновик", callback_data="aevsave:draft")],
            [
                InlineKeyboardButton(
                    text="Сохранить и опубликовать", callback_data="aevsave:published"
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(AdminEventStates.confirm, F.data.startswith("aevsave:"))
async def save_created_event(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    data = await state.get_data()
    event = await EventService(session).create(
        title=str(data["title"]),
        short_description=str(data["short_description"]),
        full_description=str(data["full_description"]),
        start_at=parse_local_datetime_from_iso(str(data["start_at"])),
        end_at=parse_local_datetime_from_iso(str(data["end_at"])) if data.get("end_at") else None,
        timezone=settings.default_timezone,
        country=data.get("country"),
        city=data.get("city"),
        address=data.get("address"),
        capacity=data.get("capacity"),
        details_url=data.get("details_url"),
        status=EventStatus.DRAFT,
        author_admin_id=admin_model.id,
    )
    if callback.data.endswith("published"):
        await EventService(session).publish(event, utcnow())
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="event_created",
        entity_type="event",
        entity_id=event.id,
        now=utcnow(),
    )
    await state.clear()
    await callback.message.answer("Мероприятие сохранено.")
    await show_event_card(callback.message, session, settings, event.id)
    await callback.answer()


@router.callback_query(F.data.startswith("aev:") & ~F.data.in_({"aev:new"}))
async def event_card(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    await require_events(session, settings, admin_model)
    await show_event_card(callback.message, session, settings, callback.data.split(":", 1)[1])
    await callback.answer()


@router.callback_query(F.data.startswith("aevpub:"))
async def publish_event(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, admin_model: Admin
) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1])
    if event is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await EventService(session).publish(event, utcnow())
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="event_published",
        entity_type="event",
        entity_id=event.id,
        now=utcnow(),
    )
    await callback.answer("Опубликовано", show_alert=True)


@router.callback_query(F.data.startswith("aevreg:"))
async def toggle_event_registration(callback: CallbackQuery, session: AsyncSession) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1])
    if event is None:
        await callback.answer("Мероприятие не найдено", show_alert=True)
        return
    event.registration_enabled = not event.registration_enabled
    if not event.registration_enabled and event.status == EventStatus.PUBLISHED:
        event.status = EventStatus.REGISTRATION_CLOSED
    elif event.registration_enabled and event.status == EventStatus.REGISTRATION_CLOSED:
        registered = await EventRepository(session).count_registered(event.id)
        if event.capacity is None or registered < event.capacity:
            event.status = EventStatus.PUBLISHED
    await callback.answer(
        "Регистрация включена" if event.registration_enabled else "Регистрация отключена",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("aevarc:"))
async def archive_event(callback: CallbackQuery, session: AsyncSession) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1])
    if event:
        await EventService(session).archive(event)
    await callback.answer("Перемещено в архив", show_alert=True)


@router.callback_query(F.data.startswith("aevcan:"))
async def cancel_event(callback: CallbackQuery, session: AsyncSession) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1])
    if event:
        await EventService(session).cancel_event(event)
    await callback.answer("Мероприятие отменено", show_alert=True)


@router.callback_query(F.data.startswith("aevdel:"))
async def delete_event_confirm(callback: CallbackQuery) -> None:
    event_id = callback.data.split(":", 1)[1]
    await callback.message.answer(
        "Подтвердите удаление. При наличии регистраций данные будут сохранены через мягкое удаление.",
        reply_markup=confirm_delete("aevdelok", event_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aevdelok:"))
async def delete_event(callback: CallbackQuery, session: AsyncSession, admin_model: Admin) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1])
    if event:
        await EventService(session).soft_delete(event, utcnow())
        await AdminRepository(session).log_action(
            admin_id=admin_model.id,
            action="event_deleted",
            entity_type="event",
            entity_id=event.id,
            now=utcnow(),
        )
    await callback.answer("Удалено", show_alert=True)


@router.callback_query(F.data.startswith("aevedit:"))
async def edit_event_menu(callback: CallbackQuery) -> None:
    event_id = callback.data.split(":", 1)[1]
    await callback.message.answer("Выберите поле.", reply_markup=event_edit_fields(event_id))
    await callback.answer()


@router.callback_query(F.data.startswith("aef:"))
async def edit_event_field_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, event_id, field_key = callback.data.split(":", 2)
    field = EVENT_FIELD_KEYS.get(field_key)
    if field is None:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.update_data(action="edit_field", event_id=event_id, field=field)
    await state.set_state(AdminEventStates.edit_value)
    hint = (
        "ДД.ММ.ГГГГ ЧЧ:ММ"
        if field in {"start_at", "end_at", "registration_deadline", "scheduled_publish_at"}
        else "новое значение"
    )
    await callback.message.answer(
        f"Введите {hint}. Для очистки необязательного поля отправьте «-».",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminEventStates.edit_value, F.text)
async def edit_event_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    sender: BroadcastSender,
    admin_model: Admin,
) -> None:
    data = await state.get_data()
    action = data.get("action")
    event_id = str(data.get("event_id"))
    event = await EventRepository(session).get(event_id, with_relations=True)
    if event is None:
        await state.clear()
        await message.answer("Мероприятие не найдено.")
        return
    value = (message.text or "").strip()
    if action == "edit_field":
        field = str(data["field"])
        parsed: object = None if value == "-" else value
        if (
            field in {"start_at", "end_at", "registration_deadline", "scheduled_publish_at"}
            and value != "-"
        ):
            try:
                parsed = parse_local_datetime(value, settings.default_timezone)
            except ValueError as exc:
                await message.answer(f"Некорректная дата: {exc}")
                return
        elif field == "capacity" and value != "-":
            try:
                parsed = int(value)
                if parsed < 1:
                    raise ValueError
            except ValueError:
                await message.answer("Введите положительное целое число или «-».")
                return
        elif field in {"details_url", "map_url"} and value != "-":
            try:
                parsed = validate_url(value)
            except ValueError as exc:
                await message.answer(str(exc))
                return
        elif field in {"latitude", "longitude"} and value != "-":
            try:
                parsed = float(value.replace(",", "."))
                limit = 90 if field == "latitude" else 180
                if not -limit <= parsed <= limit:
                    raise ValueError
            except ValueError:
                await message.answer("Введите корректное число в диапазоне широты/долготы или «-».")
                return
        elif field == "timezone" and value != "-":
            try:
                ZoneInfo(value)
                parsed = value
            except Exception:
                await message.answer("Укажите корректный IANA-часовой пояс, например Asia/Yerevan.")
                return
        setattr(event, field, parsed)
        if field == "scheduled_publish_at" and parsed:
            event.status = EventStatus.DRAFT
        await state.clear()
        await message.answer("Изменение сохранено.")
        await show_event_card(message, session, settings, event.id)
        return
    if action == "add_link":
        if "|" not in value:
            await message.answer("Используйте формат: Название | https://example.com")
            return
        title, raw_url = (part.strip() for part in value.split("|", 1))
        try:
            url = validate_url(raw_url)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        position = len(event.links)
        session.add(EventLink(event_id=event.id, title=title[:128], url=url, position=position))
        await state.clear()
        await message.answer("Ссылка добавлена.")
        return
    if action == "reminder":
        try:
            minutes = int(value)
            if minutes < 1:
                raise ValueError
        except ValueError:
            await message.answer("Введите количество минут больше нуля.")
            return
        existing = await session.scalar(
            select(EventReminder).where(
                EventReminder.event_id == event.id, EventReminder.minutes_before == minutes
            )
        )
        if existing:
            existing.enabled = True
            existing.last_sent_at = None
        else:
            session.add(EventReminder(event_id=event.id, minutes_before=minutes))
        await state.clear()
        await message.answer("Напоминание настроено.")
        return
    if action == "participant_message":
        broadcast_service = BroadcastService(session, settings)
        audience = {
            "subscribed_only": False,
            "event_id": event.id,
            "participation": "any",
        }
        broadcast = await broadcast_service.create(
            title=f"Участникам: {event.title}"[:255],
            text=value,
            audience_filter=audience,
            author_admin_id=admin_model.id,
        )
        broadcast.total_recipients = await broadcast_service.count_audience(audience, utcnow())
        await AdminRepository(session).log_action(
            admin_id=admin_model.id,
            action="event_participant_broadcast_started",
            entity_type="event",
            entity_id=event.id,
            now=utcnow(),
            metadata={
                "broadcast_id": broadcast.id,
                "audience_count": broadcast.total_recipients,
            },
        )
        await session.commit()
        sender.start(broadcast.id)
        await state.clear()
        await message.answer(
            "Сообщение поставлено в устойчивую очередь рассылки. "
            f"Получателей: {broadcast.total_recipients}."
        )


@router.callback_query(F.data.startswith("aevmedia:"))
async def event_media(callback: CallbackQuery, session: AsyncSession) -> None:
    event = await EventRepository(session).get(callback.data.split(":", 1)[1], with_relations=True)
    if event is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.answer("Файлы и ссылки", reply_markup=event_media_keyboard(event))
    await callback.answer()


@router.callback_query(F.data.startswith("aevaddfile:"))
async def add_event_file_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="add_file", event_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminEventStates.edit_value)
    await callback.message.answer(
        "Отправьте изображение или документ.", reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminEventStates.edit_value, F.photo | F.document)
async def add_event_file(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    data = await state.get_data()
    if data.get("action") not in {"add_file", "broadcast_file"}:
        await message.answer("В текущем шаге ожидается текстовое значение.")
        return
    if data.get("action") == "broadcast_file":
        return
    event = await EventRepository(session).get(str(data["event_id"]), with_relations=True)
    if event is None:
        await state.clear()
        await message.answer("Мероприятие не найдено.")
        return
    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        unique = photo.file_unique_id
        size = photo.file_size
        file_type = FileType.PHOTO
        name = None
        mime = "image/jpeg"
    else:
        document = message.document
        if document is None:
            await message.answer("Документ не распознан.")
            return
        file_id = document.file_id
        unique = document.file_unique_id
        size = document.file_size
        file_type = FileType.DOCUMENT
        name = document.file_name
        mime = document.mime_type
    if size and size > settings.max_upload_bytes:
        await message.answer("Файл превышает допустимый размер.")
        return
    session.add(
        EventFile(
            event_id=event.id,
            file_id=file_id,
            file_unique_id=unique,
            file_type=file_type,
            file_name=name,
            mime_type=mime,
            size=size,
            caption=message.caption,
            position=len(event.files),
        )
    )
    await state.clear()
    await message.answer("Файл добавлен.")


@router.callback_query(F.data.startswith("aevaddlink:"))
async def add_event_link_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="add_link", event_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminEventStates.edit_value)
    await callback.message.answer(
        "Отправьте ссылку в формате: Название | https://example.com",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aefrm:"))
async def remove_event_file(callback: CallbackQuery, session: AsyncSession) -> None:
    file = await session.get(EventFile, callback.data.split(":", 1)[1])
    if file:
        await session.delete(file)
    await callback.answer("Файл удалён", show_alert=True)


@router.callback_query(F.data.startswith(("aefup:", "aefdn:")))
async def move_event_file(callback: CallbackQuery, session: AsyncSession) -> None:
    prefix, file_id = callback.data.split(":", 1)
    item = await session.get(EventFile, file_id)
    if item is None:
        await callback.answer("Файл не найден", show_alert=True)
        return
    siblings = list(
        await session.scalars(
            select(EventFile)
            .where(EventFile.event_id == item.event_id)
            .order_by(EventFile.position.asc(), EventFile.created_at.asc())
        )
    )
    index = next((idx for idx, sibling in enumerate(siblings) if sibling.id == item.id), -1)
    target_index = index - 1 if prefix == "aefup" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(siblings):
        await callback.answer("Перемещение невозможно", show_alert=True)
        return
    target = siblings[target_index]
    item.position, target.position = target.position, item.position
    await callback.answer("Порядок файлов изменён", show_alert=True)


@router.callback_query(F.data.startswith("aelrm:"))
async def remove_event_link(callback: CallbackQuery, session: AsyncSession) -> None:
    link = await session.get(EventLink, callback.data.split(":", 1)[1])
    if link:
        await session.delete(link)
    await callback.answer("Ссылка удалена", show_alert=True)


@router.callback_query(F.data.startswith(("aelup:", "aeldn:")))
async def move_event_link(callback: CallbackQuery, session: AsyncSession) -> None:
    prefix, link_id = callback.data.split(":", 1)
    item = await session.get(EventLink, link_id)
    if item is None:
        await callback.answer("Ссылка не найдена", show_alert=True)
        return
    siblings = list(
        await session.scalars(
            select(EventLink)
            .where(EventLink.event_id == item.event_id)
            .order_by(EventLink.position.asc(), EventLink.created_at.asc())
        )
    )
    index = next((idx for idx, sibling in enumerate(siblings) if sibling.id == item.id), -1)
    target_index = index - 1 if prefix == "aelup" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(siblings):
        await callback.answer("Перемещение невозможно", show_alert=True)
        return
    target = siblings[target_index]
    item.position, target.position = target.position, item.position
    await callback.answer("Порядок ссылок изменён", show_alert=True)


@router.callback_query(F.data.startswith("aevpart:"))
async def event_participants(callback: CallbackQuery, session: AsyncSession) -> None:
    event_id = callback.data.split(":", 1)[1]
    items = await EventRepository(session).list_participants(event_id, 0, 100)
    await callback.message.answer(
        f"Участники: {len(items)}", reply_markup=participants_keyboard(items, event_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("att:"))
async def mark_attendance(callback: CallbackQuery, session: AsyncSession) -> None:
    _, flag, registration_id = callback.data.split(":", 2)
    registration = await session.get(Registration, registration_id)
    if registration is None:
        await callback.answer("Регистрация не найдена", show_alert=True)
        return
    await EventService(session).mark_attendance(registration, attended=flag == "y", now=utcnow())
    await callback.answer("Статус сохранён", show_alert=True)


@router.callback_query(F.data.startswith("aevstat:"))
async def event_stats(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    event_id = callback.data.split(":", 1)[1]
    stats = await AnalyticsService(session, settings).event_statistics(event_id)
    text = "\n".join(f"{key}: {value}" for key, value in stats.items())
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статистика CSV", callback_data=f"aevsexp:{event_id}:csv"
                ),
                InlineKeyboardButton(
                    text="Статистика XLSX", callback_data=f"aevsexp:{event_id}:xlsx"
                ),
            ]
        ]
    )
    await callback.message.answer(f"Статистика мероприятия\n\n{text}", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("aevrem:"))
async def event_reminder_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="reminder", event_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminEventStates.edit_value)
    await callback.message.answer("За сколько минут до начала отправить напоминание?")
    await callback.answer()


@router.callback_query(F.data.startswith("aevmsg:"))
async def participant_message_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="participant_message", event_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminEventStates.edit_value)
    await callback.message.answer("Введите сообщение участникам.")
    await callback.answer()


@router.callback_query(F.data.startswith("aevpexp:"))
async def export_participants(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    _, event_id, fmt = callback.data.split(":", 2)
    service = ExportService(session)
    if fmt == "csv":
        content = await service.participation_csv(event_id)
        filename = "event_participants.csv"
    else:
        content = await service.participation_xlsx(event_id)
        filename = "event_participants.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="event_participants_exported",
        entity_type="event",
        entity_id=event_id,
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aevsexp:"))
async def export_event_statistics(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    _, event_id, fmt = callback.data.split(":", 2)
    stats = await AnalyticsService(session, settings).event_statistics(event_id)
    if fmt == "csv":
        content = ExportService.statistics_csv(stats)
        filename = "event_statistics.csv"
    else:
        content = ExportService.statistics_xlsx("Статистика", stats)
        filename = "event_statistics.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="event_statistics_exported",
        entity_type="event",
        entity_id=event_id,
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()
