from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.admin import admins_keyboard, cancel_keyboard, export_keyboard, roles_keyboard
from app.models.content_audit import Admin, AdminAction
from app.models.enums import AdminRole
from app.repositories.admins import AdminRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsService
from app.services.export import ExportService
from app.services.permissions import PermissionService
from app.states.admin import AdminManagementStates
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
async def users_list(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    users = await UserRepository(session).list_paginated(0, 30)
    lines = ["<b>Последние пользователи</b>"]
    for user in users:
        name = user.username or user.first_name or "без имени"
        lines.append(
            f"{user.telegram_id} · {name} · {user.country or 'страна не указана'} · "
            f"{'подписан' if user.is_subscribed else 'отписан'}"
        )
    await callback.message.answer("\n".join(lines) if users else "Пользователей нет.")
    await callback.answer()


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
