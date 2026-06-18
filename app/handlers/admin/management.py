from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.admin import (
    admins_keyboard,
    cancel_keyboard,
    export_keyboard,
    roles_keyboard,
    user_card_keyboard,
    users_admin_keyboard,
    users_results_keyboard,
)
from app.models.content_audit import Admin, AdminAction
from app.models.enums import AdminRole
from app.repositories.admins import AdminRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsService
from app.services.export import ExportService
from app.services.permissions import PermissionService
from app.services.users import determine_age_group
from app.states.admin import AdminManagementStates, AdminUserStates
from app.utils.time import format_datetime, utcnow

router = Router(name="admin_management")


@router.callback_query(F.data == "adm:stats")
async def dashboard(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "statistics"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await AnalyticsService(session, settings).dashboard(utcnow())
    users = data["users"]
    countries = ", ".join(f"{name}: {count}" for name, count in data["countries"][:10])
    age_groups = ", ".join(f"{name}: {count}" for name, count in data["age_groups"][:10])
    dynamics = ", ".join(f"{day}: {count}" for day, count in data["registration_dynamics"][-14:])
    text = (
        "<b>Общая статистика</b>\n\n"
        f"Пользователи: {users['total']}\n"
        f"Новые: {users['new']}\n"
        f"Активные: {users['active']}\n"
        f"Неактивные: {users['inactive']}\n"
        f"Подписаны: {users['subscribed']}\n"
        f"Отписаны: {users['unsubscribed']}\n"
        f"Заблокировали бота: {users['blocked']}\n\n"
        f"Мероприятия: {data['events']}\n"
        f"Рассылки: {data['broadcasts']}\n"
        f"Запланированные рассылки: {data['broadcasts_scheduled']}\n"
        f"Успешно отправлено: {data['sent_messages']}\n"
        f"Ошибок отправки: {data['failed_messages']}\n"
        f"Блокировок при отправке: {data['blocked_messages']}\n"
        f"Переходы по tracking-ссылкам: {data['clicks']}\n\n"
        f"Страны: {countries or 'нет данных'}\n"
        f"Возрастные группы: {age_groups or 'нет данных'}\n"
        f"Регистрации по дням: {dynamics or 'нет данных'}\n\n"
        "Открытия сообщений недоступны в Telegram Bot API."
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "adm:users")
async def users_menu(
    callback: CallbackQuery,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.answer(
        "<b>Пользователи</b>\n\n"
        "Здесь можно найти участника, открыть его карточку, исправить данные "
        "или выгрузить всю базу.",
        reply_markup=users_admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "ausr:recent")
async def users_recent(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    users = await UserRepository(session).list_paginated(0, 30)
    await callback.message.answer(
        "Последние зарегистрированные пользователи",
        reply_markup=users_results_keyboard(users),
    )
    await callback.answer()


@router.callback_query(F.data == "ausr:search")
async def user_search_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminUserStates.search)
    await callback.message.answer(
        "Введите числовой Telegram ID или username пользователя. "
        "Username можно вводить с @ или без него.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminUserStates.search, F.text)
async def user_search_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    users = await UserRepository(session).search(message.text or "")
    await state.clear()
    if not users:
        await message.answer("Пользователь не найден.", reply_markup=users_admin_keyboard())
        return
    await message.answer(
        f"Найдено: {len(users)}",
        reply_markup=users_results_keyboard(users),
    )


def user_card_text(user: object, settings: Settings) -> str:
    from app.models.users_events import User

    if not isinstance(user, User):
        return "Пользователь не найден."
    username = f"@{user.username}" if user.username else "не указан"
    first_name = escape(user.first_name or "не указано")
    last_name = escape(user.last_name or "не указана")
    age_group = escape(user.age_group or "не указана")
    country = escape(user.country or "не указана")
    participation_history = escape(user.participation_history or "не указана")
    return (
        "<b>Карточка пользователя</b>\n\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {escape(username)}\n"
        f"Имя: {first_name}\n"
        f"Фамилия: {last_name}\n"
        f"Возраст: {user.age if user.age is not None else 'не указан'}\n"
        f"Возрастная группа: {age_group}\n"
        f"Страна: {country}\n"
        f"История участия: {participation_history}\n"
        f"Регистрация: {format_datetime(user.registered_at, settings.default_timezone)}\n"
        f"Последняя активность: "
        f"{format_datetime(user.last_activity_at, settings.default_timezone)}\n"
        f"Уведомления: {'включены' if user.is_subscribed else 'отключены'}\n"
        f"Бот заблокирован: {'да' if user.is_blocked else 'нет'}\n"
        f"Регистрация завершена: {'да' if user.registration_completed else 'нет'}"
    )


@router.callback_query(F.data.startswith("ausr:") & ~F.data.in_({"ausr:search", "ausr:recent"}))
async def user_card(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = callback.data.split(":", 1)[1]
    user = await UserRepository(session).get(user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.message.answer(
        user_card_text(user, settings),
        reply_markup=user_card_keyboard(user.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("auedit:"))
async def user_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, user_id, field = callback.data.split(":", 2)
    user = await UserRepository(session).get(user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    labels = {
        "first": "имя",
        "last": "фамилию",
        "age": "возраст числом",
        "country": "страну",
        "history": "историю участия",
    }
    if field not in labels:
        await callback.answer("Поле не поддерживается", show_alert=True)
        return
    await state.set_state(AdminUserStates.edit_value)
    await state.update_data(user_id=user_id, field=field)
    await callback.message.answer(
        f"Введите новое значение: {labels[field]}.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminUserStates.edit_value, F.text)
async def user_edit_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    data = await state.get_data()
    user = await UserRepository(session).get(str(data["user_id"]))
    if user is None:
        await state.clear()
        await message.answer("Пользователь не найден.")
        return
    field = str(data["field"])
    value = (message.text or "").strip()
    if field in {"first", "last"}:
        if not 2 <= len(value) <= 128:
            await message.answer("Значение должно содержать от 2 до 128 символов.")
            return
        if field == "first":
            user.first_name = value
        else:
            user.last_name = value
    elif field == "country":
        if not 2 <= len(value) <= 128:
            await message.answer("Название страны должно содержать от 2 до 128 символов.")
            return
        user.country = value
    elif field == "history":
        if not 2 <= len(value) <= 2000:
            await message.answer("История должна содержать от 2 до 2000 символов.")
            return
        user.participation_history = value
    elif field == "age":
        try:
            age = int(value)
            if age < 5 or age > 120:
                raise ValueError
        except ValueError:
            await message.answer("Возраст должен быть целым числом от 5 до 120.")
            return
        user.age = age
        user.age_group = determine_age_group(age, settings.age_groups)
    await session.flush()
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="user_profile_updated",
        entity_type="user",
        entity_id=user.id,
        now=utcnow(),
        metadata={"field": field},
    )
    await state.clear()
    await message.answer(
        "Данные пользователя обновлены.\n\n" + user_card_text(user, settings),
        reply_markup=user_card_keyboard(user.id),
    )


@router.callback_query(F.data.startswith("autoggle:"))
async def user_subscription_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user = await UserRepository(session).get(callback.data.split(":", 1)[1])
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    user.is_subscribed = not user.is_subscribed
    user.notifications_consent = user.is_subscribed
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="user_subscription_toggled",
        entity_type="user",
        entity_id=user.id,
        now=utcnow(),
        metadata={"is_subscribed": user.is_subscribed},
    )
    await callback.message.answer(
        user_card_text(user, settings), reply_markup=user_card_keyboard(user.id)
    )
    await callback.answer("Статус уведомлений изменён", show_alert=True)


@router.callback_query(F.data == "adm:export")
async def export_menu(callback: CallbackQuery, admin_model: Admin) -> None:
    if not PermissionService.has_permission(admin_model, "export"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.answer("Экспорт данных", reply_markup=export_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("exp:users:"))
async def export_users(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "export"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    fmt = callback.data.rsplit(":", 1)[1]
    service = ExportService(session)
    if fmt == "csv":
        content = await service.users_csv()
        filename = "users.csv"
    else:
        content = await service.users_xlsx()
        filename = "users.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="users_exported",
        entity_type="users",
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data.startswith("exp:tickets:"))
async def export_tickets(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "export"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    fmt = callback.data.rsplit(":", 1)[1]
    service = ExportService(session)
    if fmt == "csv":
        content = await service.tickets_csv()
        filename = "support_tickets.csv"
    else:
        content = await service.tickets_xlsx()
        filename = "support_tickets.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="support_tickets_exported",
        entity_type="support_tickets",
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data.startswith("exp:history:"))
async def export_participation_history(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "export"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    fmt = callback.data.rsplit(":", 1)[1]
    service = ExportService(session)
    if fmt == "csv":
        content = await service.participation_csv()
        filename = "participation_history.csv"
    else:
        content = await service.participation_xlsx()
        filename = "participation_history.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="participation_history_exported",
        entity_type="registrations",
        now=utcnow(),
        metadata={"format": fmt},
    )
    await callback.answer()


@router.callback_query(F.data == "adm:logs")
async def admin_logs(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
    settings: Settings,
) -> None:
    if not PermissionService.has_permission(admin_model, "logs"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    actions = list(
        await session.scalars(select(AdminAction).order_by(AdminAction.created_at.desc()).limit(50))
    )
    lines = ["<b>Последние действия администраторов</b>"]
    for action in actions:
        lines.append(
            f"{format_datetime(action.created_at, settings.default_timezone)} · "
            f"{action.action} · {action.entity_type or '-'} {action.entity_id or ''}"
        )
    await callback.message.answer("\n".join(lines) if actions else "Журнал пока пуст.")
    await callback.answer()


@router.callback_query(F.data == "adm:settings")
async def admin_settings(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.answer(
        "<b>Настройки приложения</b>\n\n"
        f"Режим: {settings.bot_mode}\n"
        f"Часовой пояс: {settings.default_timezone}\n"
        f"Активный пользователь: {settings.active_user_days} дней\n"
        f"Новый пользователь: {settings.new_user_days} дней\n"
        f"Размер пакета рассылки: {settings.broadcast_batch_size}\n"
        f"Конкурентность рассылки: {settings.broadcast_concurrency}\n"
        "Изменение системных параметров выполняется через переменные окружения Railway/.env."
    )
    await callback.answer()


@router.callback_query(F.data == "adm:admins")
async def admins_list(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Только superadmin может управлять администраторами", show_alert=True)
        return
    admins = await AdminRepository(session).list_all()
    await callback.message.answer("Администраторы", reply_markup=admins_keyboard(admins))
    await callback.answer()


@router.callback_query(F.data == "aadmin:new")
async def add_admin_start(callback: CallbackQuery, state: FSMContext, admin_model: Admin) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminManagementStates.telegram_id)
    await callback.message.answer(
        "Введите Telegram ID нового администратора.", reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminManagementStates.telegram_id, F.text)
async def add_admin_id(message: Message, state: FSMContext) -> None:
    try:
        telegram_id = int(message.text or "")
        if telegram_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Telegram ID должен быть положительным целым числом.")
        return
    await state.update_data(telegram_id=telegram_id)
    await state.set_state(AdminManagementStates.role)
    await message.answer("Выберите роль.", reply_markup=roles_keyboard())


@router.callback_query(AdminManagementStates.role, F.data.startswith("arole:"))
async def add_admin_role(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    role = AdminRole(callback.data.split(":", 1)[1])
    data = await state.get_data()
    admin = await AdminRepository(session).upsert(
        telegram_id=int(data["telegram_id"]),
        role=role,
        added_by_admin_id=admin_model.id,
    )
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="admin_upserted",
        entity_type="admin",
        entity_id=admin.id,
        now=utcnow(),
        metadata={"telegram_id": admin.telegram_id, "role": role.value},
    )
    await state.clear()
    await callback.message.answer(
        f"Администратор {admin.telegram_id} добавлен с ролью {role.value}."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aadmin:") & ~F.data.in_({"aadmin:new"}))
async def admin_card(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    target = await AdminRepository(session).get(callback.data.split(":", 1)[1])
    if target is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Деактивировать", callback_data=f"aadmoff:{target.id}")],
            [InlineKeyboardButton(text="К списку", callback_data="adm:admins")],
        ]
    )
    await callback.message.answer(
        f"Telegram ID: {target.telegram_id}\nРоль: {target.role.value}\nАктивен: {target.is_active}",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aadmoff:"))
async def deactivate_admin(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    target = await AdminRepository(session).get(callback.data.split(":", 1)[1])
    if target is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    if target.id == admin_model.id:
        await callback.answer("Нельзя деактивировать себя", show_alert=True)
        return
    await AdminRepository(session).deactivate(target, utcnow())
    await callback.answer("Администратор деактивирован", show_alert=True)
