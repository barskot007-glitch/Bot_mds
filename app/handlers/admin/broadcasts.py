from __future__ import annotations

from aiogram import Bot, F, Router
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
    audience_keyboard,
    broadcast_actions,
    broadcast_media_keyboard,
    broadcast_segment_keyboard,
    broadcasts_keyboard,
    cancel_keyboard,
    confirm_delete,
    country_multiselect_keyboard,
    photo_collection_keyboard,
)
from app.models.broadcast_support import BroadcastButton, BroadcastFile
from app.models.content_audit import Admin
from app.models.enums import BroadcastStatus, FileType
from app.repositories.admins import AdminRepository
from app.repositories.broadcasts import BroadcastRepository
from app.repositories.events import EventRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsService
from app.services.broadcasts import BroadcastSender, BroadcastService
from app.services.export import ExportService
from app.services.permissions import PermissionService
from app.states.admin import AdminBroadcastStates
from app.texts.common import BROADCAST_STATUS_LABELS
from app.utils.time import format_datetime, parse_local_datetime, utcnow
from app.utils.validators import validate_url

router = Router(name="admin_broadcasts")
router.message.filter(AdminFilter("broadcasts"))
router.callback_query.filter(AdminFilter("broadcasts"))
PAGE_SIZE = 8


async def require_broadcasts(admin: Admin) -> None:
    if not PermissionService.has_permission(admin, "broadcasts"):
        raise PermissionError("Недостаточно прав для рассылок")


def broadcast_text(item, settings: Settings) -> str:
    return (
        f"<b>{item.title}</b>\n"
        f"Статус: {BROADCAST_STATUS_LABELS[item.status.value]}\n"
        f"Получателей: {item.total_recipients}\n"
        f"Успешно отправлено: {item.sent_count}\n"
        f"Ошибок: {item.failed_count}\n"
        f"Блокировок: {item.blocked_count}\n"
        f"Запланировано: {format_datetime(item.scheduled_at, settings.default_timezone)}\n"
        f"Аудитория: {item.audience_filter}\n\n"
        f"{item.text}"
    )


def can_edit_broadcast(status: BroadcastStatus) -> bool:
    return status in {BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED, BroadcastStatus.FAILED}


async def send_broadcast_preview(bot: Bot, chat_id: int, item) -> None:
    photos = [file for file in item.files if file.file_type == FileType.PHOTO]
    if len(photos) > 1:
        from aiogram.types import InputMediaPhoto

        media = [
            InputMediaPhoto(
                media=photo.file_id,
                caption=item.text[:1024] if index == 0 else None,
                parse_mode=item.parse_mode if index == 0 else None,
            )
            for index, photo in enumerate(photos[:10])
        ]
        await bot.send_media_group(chat_id, media=media)
        if len(item.text) > 1024:
            await bot.send_message(chat_id, item.text, parse_mode=item.parse_mode)
        return
    if photos:
        await bot.send_photo(
            chat_id,
            photos[0].file_id,
            caption=item.text[:1024],
            parse_mode=item.parse_mode,
        )
        if len(item.text) > 1024:
            await bot.send_message(chat_id, item.text, parse_mode=item.parse_mode)
        return
    await bot.send_message(chat_id, item.text, parse_mode=item.parse_mode)


@router.callback_query(F.data == "adm:broadcasts")
@router.callback_query(F.data.startswith("abcl:"))
async def list_broadcasts(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    await require_broadcasts(admin_model)
    page = int(callback.data.split(":")[1]) if callback.data.startswith("abcl:") else 0
    items = await BroadcastRepository(session).list_admin(page * PAGE_SIZE, PAGE_SIZE + 1)
    await callback.message.answer(
        "Управление рассылками",
        reply_markup=broadcasts_keyboard(items[:PAGE_SIZE], page, len(items) > PAGE_SIZE),
    )
    await callback.answer()


@router.callback_query(F.data == "abc:new")
async def new_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    admin_model: Admin,
) -> None:
    await require_broadcasts(admin_model)
    await state.clear()
    await state.update_data(
        audience={"subscribed_only": True},
        broadcast_age_mode="all",
        broadcast_photos=[],
        new_broadcast_wizard=True,
    )
    await state.set_state(AdminBroadcastStates.audience)
    await callback.message.answer(
        "<b>Новая рассылка: выбор аудитории</b>\n\n"
        "Можно выбрать возраст и несколько стран одновременно.",
        reply_markup=broadcast_segment_keyboard(),
    )
    await callback.answer()


@router.callback_query(AdminBroadcastStates.audience, F.data.startswith("bcrm:age:"))
async def broadcast_age_filter(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.rsplit(":", 1)[1]
    if mode not in {"all", "under18", "adult"}:
        await callback.answer("Неизвестный фильтр", show_alert=True)
        return
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    audience.pop("age_min", None)
    audience.pop("age_max", None)
    if mode == "under18":
        audience["age_max"] = 17
    elif mode == "adult":
        audience["age_min"] = 18
    await state.update_data(audience=audience, broadcast_age_mode=mode)
    await callback.message.answer(
        "Фильтр возраста обновлён.",
        reply_markup=broadcast_segment_keyboard(
            age_mode=mode,
            selected_countries=len(audience.get("countries") or []),
        ),
    )
    await callback.answer()


@router.callback_query(AdminBroadcastStates.audience, F.data == "bcrm:countries")
async def broadcast_countries(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    countries = await UserRepository(session).list_countries()
    if not countries:
        await callback.answer("В базе пока нет стран", show_alert=True)
        return
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    selected = set(audience.get("countries") or [])
    await state.update_data(broadcast_country_options=countries)
    await callback.message.answer(
        "Выберите страны для рассылки:",
        reply_markup=country_multiselect_keyboard(
            countries,
            selected,
            prefix="bcrmct",
            done_callback="bcrm:countries_done",
            clear_callback="bcrm:countries_clear",
        ),
    )
    await callback.answer()


@router.callback_query(AdminBroadcastStates.audience, F.data.startswith("bcrmct:"))
async def broadcast_country_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    countries = list(data.get("broadcast_country_options") or [])
    try:
        country = countries[int(callback.data.split(":", 1)[1])]
    except (ValueError, IndexError):
        await callback.answer("Страна не найдена", show_alert=True)
        return
    audience = dict(data.get("audience") or {"subscribed_only": True})
    selected = set(audience.get("countries") or [])
    if country in selected:
        selected.remove(country)
    else:
        selected.add(country)
    if selected:
        audience["countries"] = sorted(selected)
    else:
        audience.pop("countries", None)
    await state.update_data(audience=audience)
    await callback.message.edit_reply_markup(
        reply_markup=country_multiselect_keyboard(
            countries,
            selected,
            prefix="bcrmct",
            done_callback="bcrm:countries_done",
            clear_callback="bcrm:countries_clear",
        )
    )
    await callback.answer("Выбор обновлён")


@router.callback_query(AdminBroadcastStates.audience, F.data == "bcrm:countries_clear")
async def broadcast_countries_clear(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    audience.pop("countries", None)
    countries = list(data.get("broadcast_country_options") or [])
    await state.update_data(audience=audience)
    await callback.message.edit_reply_markup(
        reply_markup=country_multiselect_keyboard(
            countries,
            set(),
            prefix="bcrmct",
            done_callback="bcrm:countries_done",
            clear_callback="bcrm:countries_clear",
        )
    )
    await callback.answer("Выбор очищен")


@router.callback_query(AdminBroadcastStates.audience, F.data == "bcrm:countries_done")
async def broadcast_countries_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    await callback.message.answer(
        "Фильтр стран сохранён.",
        reply_markup=broadcast_segment_keyboard(
            age_mode=str(data.get("broadcast_age_mode") or "all"),
            selected_countries=len(audience.get("countries") or []),
        ),
    )
    await callback.answer()


@router.callback_query(AdminBroadcastStates.audience, F.data == "bcrm:done")
async def broadcast_segment_done(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    count = await BroadcastService(session, settings).count_audience(audience, utcnow())
    await state.update_data(audience=audience, estimated_count=count)
    await state.set_state(AdminBroadcastStates.text)
    await callback.message.answer(
        f"Получателей по выбранному сегменту: {count}.\n\nВведите текст рассылки.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.title, F.text)
async def broadcast_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 3 <= len(title) <= 255:
        await message.answer("Название должно содержать от 3 до 255 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(AdminBroadcastStates.text)
    await message.answer(
        "Введите текст рассылки. Допускается Telegram HTML, максимум 4096 символов.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminBroadcastStates.text, F.text)
async def broadcast_body(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 4096:
        await message.answer("Текст обязателен и не должен превышать 4096 символов.")
        return
    data = await state.get_data()
    if data.get("new_broadcast_wizard"):
        await state.update_data(text=text, broadcast_photos=[])
        await state.set_state(AdminBroadcastStates.photos)
        await message.answer(
            "Прикрепите одну или несколько фотографий. "
            "Когда закончите, нажмите «Просмотреть». Фото можно не добавлять.",
            reply_markup=photo_collection_keyboard(
                done_callback="bcwiz:preview",
                count=0,
            ),
        )
        return
    await state.update_data(text=text, audience={"subscribed_only": True})
    await state.set_state(AdminBroadcastStates.audience)
    await message.answer(
        "Настройте аудиторию. Фильтры страны, возраста и активности можно комбинировать.",
        reply_markup=audience_keyboard(),
    )


@router.message(AdminBroadcastStates.photos, F.photo)
async def broadcast_wizard_photo(
    message: Message,
    state: FSMContext,
    settings: Settings,
) -> None:
    data = await state.get_data()
    photos = list(data.get("broadcast_photos") or [])
    if len(photos) >= 10:
        await message.answer("Для одной альбомной рассылки можно добавить не более 10 фото.")
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > settings.max_upload_bytes:
        await message.answer("Фотография превышает допустимый размер.")
        return
    photos.append(
        {
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "size": photo.file_size,
            "caption": message.caption,
        }
    )
    await state.update_data(broadcast_photos=photos)
    await message.answer(
        f"Фото добавлено. Всего: {len(photos)}.",
        reply_markup=photo_collection_keyboard(
            done_callback="bcwiz:preview",
            count=len(photos),
        ),
    )


@router.callback_query(AdminBroadcastStates.photos, F.data == "bcwiz:preview")
async def broadcast_wizard_preview(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
    bot: Bot,
) -> None:
    data = await state.get_data()
    audience = dict(data.get("audience") or {"subscribed_only": True})
    text = str(data.get("text") or "").strip()
    if not text:
        await callback.answer("Текст рассылки не найден", show_alert=True)
        return
    title = f"Рассылка {utcnow().strftime('%d.%m.%Y %H:%M')}"
    item = await BroadcastService(session, settings).create(
        title=title,
        text=text,
        audience_filter=audience,
        author_admin_id=admin_model.id,
    )
    photos = list(data.get("broadcast_photos") or [])
    for position, photo in enumerate(photos):
        session.add(
            BroadcastFile(
                broadcast_id=item.id,
                file_id=str(photo["file_id"]),
                file_unique_id=str(photo["file_unique_id"]),
                file_type=FileType.PHOTO,
                file_name=None,
                mime_type="image/jpeg",
                size=photo.get("size"),
                caption=photo.get("caption"),
                position=position,
            )
        )
    item.total_recipients = await BroadcastService(session, settings).count_audience(
        audience,
        utcnow(),
    )
    await session.flush()
    item = await BroadcastRepository(session).get(item.id, with_relations=True)
    if item is None:
        await state.clear()
        await callback.answer("Не удалось создать рассылку", show_alert=True)
        return
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_created",
        entity_type="broadcast",
        entity_id=item.id,
        now=utcnow(),
        metadata={"audience_count": item.total_recipients, "photos": len(photos)},
    )
    await state.clear()
    await send_broadcast_preview(bot, callback.from_user.id, item)
    await callback.message.answer(
        f"<b>Черновик рассылки</b>\nПолучателей: {item.total_recipients}",
        reply_markup=broadcast_actions(item),
    )
    await callback.answer()


@router.callback_query(AdminBroadcastStates.audience, F.data.startswith("aud:"))
async def audience_action(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    audience = dict(data.get("audience", {"subscribed_only": True}))
    if action == "all":
        audience["subscribed_only"] = True
    elif action == "everyone":
        audience["subscribed_only"] = False
    elif action == "country":
        await state.update_data(audience=audience, audience_input="country")
        await callback.message.answer("Введите страны через запятую.")
        await callback.answer()
        return
    elif action == "age":
        await state.update_data(audience=audience, audience_input="age")
        await callback.message.answer(
            "Введите возрастные группы через запятую, например: 18–24, 25–34."
        )
        await callback.answer()
        return
    elif action in {"active", "inactive", "new"}:
        audience["activity"] = action
    elif action == "new_days":
        audience["activity"] = "new"
        await state.update_data(audience=audience, audience_input="new_days")
        await callback.message.answer("Введите период для новых пользователей в днях, например 14.")
        await callback.answer()
        return
    elif action == "period":
        await state.update_data(audience=audience, audience_input="period")
        await callback.message.answer("Введите период регистрации: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ.")
        await callback.answer()
        return
    elif action in {"event_registered", "event_attended"}:
        audience["participation"] = "registered" if action == "event_registered" else "attended"
        await state.update_data(audience=audience, audience_input="event_id")
        await callback.message.answer(
            "Введите UUID мероприятия. Его можно скопировать из карточки мероприятия администратора."
        )
        await callback.answer()
        return
    elif action == "event_any":
        audience.pop("event_id", None)
        audience["participation"] = "any"
    elif action == "done":
        count = await BroadcastService(session, settings).count_audience(audience, utcnow())
        edit_id = data.get("edit_broadcast_id")
        if edit_id:
            item = await BroadcastRepository(session).get(str(edit_id), with_relations=True)
            if item is None:
                await state.clear()
                await callback.answer("Рассылка не найдена", show_alert=True)
                return
            if not can_edit_broadcast(item.status):
                await state.clear()
                await callback.answer(
                    "Запущенную или завершённую рассылку изменять нельзя", show_alert=True
                )
                return
            item.audience_filter = audience
            item.total_recipients = count
            action_name = "broadcast_audience_updated"
            result_message = "Аудитория обновлена"
        else:
            item = await BroadcastService(session, settings).create(
                title=str(data["title"]),
                text=str(data["text"]),
                audience_filter=audience,
                author_admin_id=admin_model.id,
            )
            item.total_recipients = count
            action_name = "broadcast_created"
            result_message = "Черновик создан"
        await AdminRepository(session).log_action(
            admin_id=admin_model.id,
            action=action_name,
            entity_type="broadcast",
            entity_id=item.id,
            now=utcnow(),
            metadata={"audience_count": count},
        )
        await state.clear()
        await callback.message.answer(
            f"{result_message}. Расчётная аудитория: {count}.\n\n{broadcast_text(item, settings)}",
            reply_markup=broadcast_actions(item),
        )
        await callback.answer()
        return
    await state.update_data(audience=audience, audience_input=None)
    await callback.answer("Фильтр обновлён")


@router.message(AdminBroadcastStates.audience, F.text)
async def audience_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    data = await state.get_data()
    mode = data.get("audience_input")
    audience = dict(data.get("audience", {}))
    values = [item.strip() for item in (message.text or "").split(",") if item.strip()]
    if not values:
        await message.answer("Укажите хотя бы одно значение.")
        return
    if mode == "country":
        audience["countries"] = values
    elif mode == "age":
        audience["age_groups"] = values
    elif mode == "new_days":
        try:
            days = int(values[0])
            if not 1 <= days <= 3650:
                raise ValueError
        except ValueError:
            await message.answer("Введите целое число дней от 1 до 3650.")
            return
        audience["activity"] = "new"
        audience["new_days"] = days
    elif mode == "period":
        parts = [part.strip() for part in (message.text or "").split("-", 1)]
        if len(parts) != 2:
            await message.answer("Используйте формат: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ")
            return
        try:
            start = parse_local_datetime(f"{parts[0]} 00:00", settings.default_timezone)
            end = parse_local_datetime(f"{parts[1]} 23:59", settings.default_timezone)
            if end < start:
                raise ValueError("Дата окончания раньше даты начала")
        except ValueError as exc:
            await message.answer(f"Некорректный период: {exc}")
            return
        audience["registered_from"] = start.isoformat()
        audience["registered_to"] = end.isoformat()
    elif mode == "event_id":
        event_id = values[0]
        event = await EventRepository(session).get(event_id)
        if event is None:
            await message.answer("Мероприятие с таким UUID не найдено.")
            return
        audience["event_id"] = event.id
    else:
        await message.answer("Сначала выберите фильтр кнопкой.")
        return
    await state.update_data(audience=audience, audience_input=None)
    await message.answer(
        "Фильтр добавлен. Можно добавить другие фильтры или продолжить.",
        reply_markup=audience_keyboard(),
    )


@router.callback_query(F.data.startswith("abcedit:"))
async def edit_broadcast_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, broadcast_id, field = callback.data.split(":", 2)
    item = await BroadcastRepository(session).get(broadcast_id)
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    if not can_edit_broadcast(item.status):
        await callback.answer(
            "Запущенную или завершённую рассылку изменять нельзя", show_alert=True
        )
        return
    if field not in {"title", "text"}:
        await callback.answer("Недоступное поле", show_alert=True)
        return
    await state.update_data(edit_broadcast_id=item.id, edit_field=field)
    await state.set_state(AdminBroadcastStates.edit_value)
    current = item.title if field == "title" else item.text
    await callback.message.answer(
        f"Текущее значение:\n\n{current}\n\nВведите новое значение.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.edit_value, F.text)
async def edit_broadcast_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    data = await state.get_data()
    item = await BroadcastRepository(session).get(
        str(data.get("edit_broadcast_id")), with_relations=True
    )
    if item is None:
        await state.clear()
        await message.answer("Рассылка не найдена.")
        return
    if not can_edit_broadcast(item.status):
        await state.clear()
        await message.answer("Запущенную или завершённую рассылку изменять нельзя.")
        return
    field = str(data.get("edit_field"))
    value = (message.text or "").strip()
    if field == "title":
        if not 3 <= len(value) <= 255:
            await message.answer("Название должно содержать от 3 до 255 символов.")
            return
        item.title = value
    elif field == "text":
        if not value or len(value) > 4096:
            await message.answer("Текст обязателен и не должен превышать 4096 символов.")
            return
        item.text = value
    else:
        await state.clear()
        await message.answer("Недоступное поле.")
        return
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_updated",
        entity_type="broadcast",
        entity_id=item.id,
        now=utcnow(),
        metadata={"field": field},
    )
    await state.clear()
    await message.answer(
        "Рассылка обновлена.\n\n" + broadcast_text(item, settings),
        reply_markup=broadcast_actions(item),
    )


@router.callback_query(F.data.startswith("abcaud:"))
async def edit_broadcast_audience(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    item = await BroadcastRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    if not can_edit_broadcast(item.status):
        await callback.answer(
            "Запущенную или завершённую рассылку изменять нельзя", show_alert=True
        )
        return
    await state.update_data(
        edit_broadcast_id=item.id, audience=dict(item.audience_filter), audience_input=None
    )
    await state.set_state(AdminBroadcastStates.audience)
    await callback.message.answer(
        f"Текущая аудитория: {item.audience_filter}\nВыберите дополнительные фильтры или продолжите.",
        reply_markup=audience_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abc:") & ~F.data.in_({"abc:new"}))
async def broadcast_card(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, admin_model: Admin
) -> None:
    await require_broadcasts(admin_model)
    item = await BroadcastRepository(session).get(
        callback.data.split(":", 1)[1], with_relations=True
    )
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    await callback.message.answer(
        broadcast_text(item, settings), reply_markup=broadcast_actions(item)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcprev:"))
async def preview_broadcast(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    item = await BroadcastRepository(session).get(
        callback.data.split(":", 1)[1], with_relations=True
    )
    if item is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await send_broadcast_preview(bot, callback.from_user.id, item)
    await callback.answer()


@router.callback_query(F.data.startswith("abctest:"))
async def test_broadcast(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    item = await BroadcastRepository(session).get(
        callback.data.split(":", 1)[1], with_relations=True
    )
    if item is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await bot.send_message(callback.from_user.id, f"<b>Тестовая отправка</b>\n\n{item.text}")
    await callback.answer("Тест отправлен", show_alert=True)


@router.callback_query(F.data.startswith("abcm:"))
async def broadcast_media(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await BroadcastRepository(session).get(
        callback.data.split(":", 1)[1], with_relations=True
    )
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    await callback.message.answer(
        "Файлы и кнопки рассылки", reply_markup=broadcast_media_keyboard(item)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abfr:"))
async def remove_broadcast_file(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await session.get(BroadcastFile, callback.data.split(":", 1)[1])
    if item is not None:
        await session.delete(item)
    await callback.answer("Файл удалён", show_alert=True)


@router.callback_query(F.data.startswith(("abfu:", "abfd:")))
async def move_broadcast_file(callback: CallbackQuery, session: AsyncSession) -> None:
    prefix, file_id = callback.data.split(":", 1)
    item = await session.get(BroadcastFile, file_id)
    if item is None:
        await callback.answer("Файл не найден", show_alert=True)
        return
    siblings = list(
        await session.scalars(
            select(BroadcastFile)
            .where(BroadcastFile.broadcast_id == item.broadcast_id)
            .order_by(BroadcastFile.position.asc(), BroadcastFile.created_at.asc())
        )
    )
    index = next((idx for idx, sibling in enumerate(siblings) if sibling.id == item.id), -1)
    target_index = index - 1 if prefix == "abfu" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(siblings):
        await callback.answer("Перемещение невозможно", show_alert=True)
        return
    target = siblings[target_index]
    item.position, target.position = target.position, item.position
    await callback.answer("Порядок файлов изменён", show_alert=True)


@router.callback_query(F.data.startswith("abbr:"))
async def remove_broadcast_button(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await session.get(BroadcastButton, callback.data.split(":", 1)[1])
    if item is not None:
        await session.delete(item)
    await callback.answer("Кнопка удалена", show_alert=True)


@router.callback_query(F.data.startswith(("abbu:", "abbd:")))
async def move_broadcast_button(callback: CallbackQuery, session: AsyncSession) -> None:
    prefix, button_id = callback.data.split(":", 1)
    item = await session.get(BroadcastButton, button_id)
    if item is None:
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    siblings = list(
        await session.scalars(
            select(BroadcastButton)
            .where(BroadcastButton.broadcast_id == item.broadcast_id)
            .order_by(BroadcastButton.position.asc(), BroadcastButton.created_at.asc())
        )
    )
    index = next((idx for idx, sibling in enumerate(siblings) if sibling.id == item.id), -1)
    target_index = index - 1 if prefix == "abbu" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(siblings):
        await callback.answer("Перемещение невозможно", show_alert=True)
        return
    target = siblings[target_index]
    item.position, target.position = target.position, item.position
    await callback.answer("Порядок кнопок изменён", show_alert=True)


@router.callback_query(F.data.startswith("abcfile:"))
async def add_broadcast_file_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="broadcast_file", broadcast_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminBroadcastStates.confirm)
    await callback.message.answer(
        "Отправьте изображение или документ.", reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminBroadcastStates.confirm, F.photo | F.document)
async def add_broadcast_file(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    data = await state.get_data()
    if data.get("action") != "broadcast_file":
        await message.answer("Ожидается другое действие.")
        return
    item = await BroadcastRepository(session).get(str(data["broadcast_id"]), with_relations=True)
    if item is None:
        await state.clear()
        await message.answer("Рассылка не найдена.")
        return
    if message.photo:
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > settings.max_upload_bytes:
            await message.answer("Файл превышает допустимый размер.")
            return
        attachment = BroadcastFile(
            broadcast_id=item.id,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_type=FileType.PHOTO,
            file_name=None,
            mime_type="image/jpeg",
            size=photo.file_size,
            caption=message.caption,
            position=len(item.files),
        )
    else:
        document = message.document
        if document is None:
            await message.answer("Документ не распознан.")
            return
        if document.file_size and document.file_size > settings.max_upload_bytes:
            await message.answer("Файл превышает допустимый размер.")
            return
        attachment = BroadcastFile(
            broadcast_id=item.id,
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            file_type=FileType.DOCUMENT,
            file_name=document.file_name,
            mime_type=document.mime_type,
            size=document.file_size,
            caption=message.caption,
            position=len(item.files),
        )
    session.add(attachment)
    await state.clear()
    await message.answer("Файл добавлен.", reply_markup=broadcast_actions(item))


@router.callback_query(F.data.startswith("abcbutton:"))
async def add_broadcast_button_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(action="broadcast_button", broadcast_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminBroadcastStates.confirm)
    await callback.message.answer(
        "Введите кнопку в формате: Текст | https://example.com",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.confirm, F.text)
async def add_broadcast_button(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if data.get("action") != "broadcast_button":
        await message.answer("Некорректный шаг сценария.")
        return
    value = (message.text or "").strip()
    if "|" not in value:
        await message.answer("Используйте формат: Текст | https://example.com")
        return
    text, raw_url = (part.strip() for part in value.split("|", 1))
    try:
        url = validate_url(raw_url)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    item = await BroadcastRepository(session).get(str(data["broadcast_id"]), with_relations=True)
    if item is None:
        await state.clear()
        await message.answer("Рассылка не найдена.")
        return
    session.add(
        BroadcastButton(
            broadcast_id=item.id,
            text=text[:128],
            url=url,
            position=len(item.buttons),
            is_details=text.lower().strip() == "узнать подробнее",
        )
    )
    await state.clear()
    await message.answer("Кнопка добавлена.", reply_markup=broadcast_actions(item))


@router.callback_query(F.data.startswith("abcsend:"))
async def send_broadcast_confirm(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    item = await BroadcastRepository(session).get(
        callback.data.split(":", 1)[1], with_relations=True
    )
    if item is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    count = await BroadcastService(session, settings).count_audience(item.audience_filter, utcnow())
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить отправку", callback_data=f"abcsendok:{item.id}"
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data=f"abc:{item.id}")],
        ]
    )
    await callback.message.answer(
        f"<b>Подтверждение массовой отправки</b>\n"
        f"Рассылка: {item.title}\n"
        f"Аудитория: {item.audience_filter}\n"
        f"Предполагаемое количество: {count}\n"
        f"Дата: сейчас\n\n{item.text}",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcsendok:"))
async def send_broadcast_now(
    callback: CallbackQuery,
    sender: BroadcastSender,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    item_id = callback.data.split(":", 1)[1]
    item = await BroadcastRepository(session).get(item_id)
    if item is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    if item.status in {BroadcastStatus.SENDING, BroadcastStatus.COMPLETED}:
        await callback.answer("Рассылка уже запущена или завершена", show_alert=True)
        return
    item.status = BroadcastStatus.SENDING
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_started",
        entity_type="broadcast",
        entity_id=item.id,
        now=utcnow(),
    )
    await session.commit()
    sender.start(item_id)
    await callback.answer("Рассылка запущена", show_alert=True)


@router.callback_query(F.data.startswith("abcplan:"))
async def schedule_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(broadcast_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminBroadcastStates.schedule)
    await callback.message.answer(
        "Введите дату отправки в формате ДД.ММ.ГГГГ ЧЧ:ММ.", reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminBroadcastStates.schedule, F.text)
async def schedule_broadcast(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        when = parse_local_datetime(message.text or "", settings.default_timezone)
        if when <= utcnow():
            raise ValueError("Дата должна быть в будущем")
    except ValueError as exc:
        await message.answer(f"Некорректная дата: {exc}")
        return
    data = await state.get_data()
    item = await BroadcastRepository(session).get(str(data["broadcast_id"]))
    if item is None:
        await state.clear()
        await message.answer("Рассылка не найдена.")
        return
    await BroadcastRepository(session).schedule(item, when)
    await state.clear()
    await message.answer(
        f"Рассылка запланирована на {format_datetime(when, settings.default_timezone)}."
    )


@router.callback_query(F.data.startswith("abccancel:"))
async def cancel_broadcast(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await BroadcastRepository(session).get(callback.data.split(":", 1)[1])
    if item:
        await BroadcastRepository(session).cancel(item)
    await callback.answer("Рассылка отменена", show_alert=True)


@router.callback_query(F.data.startswith("abcdel:"))
async def delete_broadcast_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await BroadcastRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    if item.status == BroadcastStatus.SENDING:
        await callback.answer("Сначала отмените активную рассылку", show_alert=True)
        return
    await callback.message.answer(
        "Подтвердите удаление. История отправок и статистика останутся в базе.",
        reply_markup=confirm_delete("abcdelok", item.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcdelok:"))
async def delete_broadcast(
    callback: CallbackQuery, session: AsyncSession, admin_model: Admin
) -> None:
    item = await BroadcastRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    if item.status == BroadcastStatus.SENDING:
        await callback.answer("Сначала отмените активную рассылку", show_alert=True)
        return
    item.deleted_at = utcnow()
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_deleted",
        entity_type="broadcast",
        entity_id=item.id,
        now=utcnow(),
    )
    await callback.answer("Рассылка удалена", show_alert=True)


@router.callback_query(F.data.startswith("abcstat:"))
async def broadcast_stats(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    broadcast_id = callback.data.split(":", 1)[1]
    stats = await AnalyticsService(session, settings).broadcast_statistics(broadcast_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статистика CSV", callback_data=f"abcsxp:{broadcast_id}:csv"
                ),
                InlineKeyboardButton(
                    text="Статистика XLSX", callback_data=f"abcsxp:{broadcast_id}:xlsx"
                ),
            ]
        ]
    )
    await callback.message.answer(
        "Статистика рассылки\n\n" + "\n".join(f"{key}: {value}" for key, value in stats.items()),
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcexp:"))
async def export_broadcast_recipients(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    _, broadcast_id, fmt = callback.data.split(":", 2)
    item = await BroadcastRepository(session).get(broadcast_id)
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    service = ExportService(session)
    if fmt == "csv":
        content = await service.broadcast_recipients_csv(broadcast_id)
        filename = "broadcast_recipients.csv"
    else:
        content = await service.broadcast_recipients_xlsx(broadcast_id)
        filename = "broadcast_recipients.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_recipients_exported",
        entity_type="broadcast",
        entity_id=broadcast_id,
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcseg:"))
async def export_broadcast_segment(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    _, broadcast_id, fmt = callback.data.split(":", 2)
    item = await BroadcastRepository(session).get(broadcast_id)
    if item is None:
        await callback.answer("Рассылка не найдена", show_alert=True)
        return
    service = ExportService(
        session,
        active_user_days=settings.active_user_days,
        new_user_days=settings.new_user_days,
    )
    if fmt == "csv":
        content = await service.users_csv(item.audience_filter)
        filename = "broadcast_audience.csv"
    else:
        content = await service.users_xlsx(item.audience_filter)
        filename = "broadcast_audience.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_audience_exported",
        entity_type="broadcast",
        entity_id=broadcast_id,
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data.startswith("abcsxp:"))
async def export_broadcast_statistics(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    _, broadcast_id, fmt = callback.data.split(":", 2)
    stats = await AnalyticsService(session, settings).broadcast_statistics(broadcast_id)
    if fmt == "csv":
        content = ExportService.statistics_csv(stats)
        filename = "broadcast_statistics.csv"
    else:
        content = ExportService.statistics_xlsx("Статистика", stats)
        filename = "broadcast_statistics.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="broadcast_statistics_exported",
        entity_type="broadcast",
        entity_id=broadcast_id,
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()
