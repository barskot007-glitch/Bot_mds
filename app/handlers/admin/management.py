from __future__ import annotations

from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.admin import (
    admins_keyboard,
    back_to_admin_keyboard,
    cancel_keyboard,
    confirm_action_keyboard,
    country_multiselect_keyboard,
    crm_export_scope_keyboard,
    crm_filters_keyboard,
    export_keyboard,
    user_card_keyboard,
    users_admin_keyboard,
    users_results_keyboard,
)
from app.models.content_audit import Admin, AdminAction
from app.models.enums import AdminRole, EventStatus, RegistrationStatus
from app.models.users_events import Event, Registration, User
from app.repositories.admins import AdminRepository
from app.repositories.users import UserRepository
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
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    total_users = int(await session.scalar(select(func.count(User.id))) or 0)
    registrations_24h = int(
        await session.scalar(select(func.count(User.id)).where(User.registered_at >= day_ago)) or 0
    )
    active_events = int(
        await session.scalar(
            select(func.count(Event.id)).where(
                Event.deleted_at.is_(None),
                Event.status.in_([EventStatus.PUBLISHED, EventStatus.REGISTRATION_CLOSED]),
            )
        )
        or 0
    )
    participants = int(
        await session.scalar(
            select(func.count(Registration.id)).where(
                Registration.status.in_(
                    [
                        RegistrationStatus.REGISTERED,
                        RegistrationStatus.ATTENDED,
                        RegistrationStatus.WAITING_LIST,
                    ]
                )
            )
        )
        or 0
    )
    actions = list(
        await session.scalars(select(AdminAction).order_by(AdminAction.created_at.desc()).limit(10))
    )
    lines = [
        "<b>Статистика</b>",
        "",
        f"Пользователей в базе: {total_users}",
        f"Регистраций за 24 часа: {registrations_24h}",
        f"Активных мероприятий: {active_events}",
        f"Нажали «Буду участвовать»: {participants}",
        "",
        "<b>Последние действия администраторов</b>",
    ]
    if actions:
        for action in actions:
            lines.append(
                f"{format_datetime(action.created_at, settings.default_timezone)} · "
                f"{escape(action.action)} · {escape(action.entity_type or '-')}"
            )
    else:
        lines.append("Журнал пока пуст.")
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=back_to_admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:users")
async def users_menu(
    callback: CallbackQuery,
    state: FSMContext,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "users"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    age_mode = str(data.get("crm_age_mode") or "all")
    selected = set(filters.get("countries") or [])
    await callback.message.answer(
        "<b>База пользователей (CRM)</b>\n\n"
        "Поиск выполняется по Telegram ID или username. "
        "Возраст и несколько стран можно использовать одновременно.",
        reply_markup=crm_filters_keyboard(
            age_mode=age_mode,
            selected_countries=len(selected),
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crm:age:"))
async def crm_age_filter(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.rsplit(":", 1)[1]
    if mode not in {"all", "under18", "adult"}:
        await callback.answer("Неизвестный фильтр", show_alert=True)
        return
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    filters.pop("age_min", None)
    filters.pop("age_max", None)
    if mode == "under18":
        filters["age_max"] = 17
    elif mode == "adult":
        filters["age_min"] = 18
    await state.update_data(crm_filters=filters, crm_age_mode=mode)
    await callback.message.answer(
        "Фильтр возраста обновлён.",
        reply_markup=crm_filters_keyboard(
            age_mode=mode,
            selected_countries=len(filters.get("countries") or []),
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "crm:countries")
async def crm_countries(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    countries = await UserRepository(session).list_countries()
    if not countries:
        await callback.answer("В базе пока нет стран", show_alert=True)
        return
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    selected = set(filters.get("countries") or [])
    await state.update_data(crm_country_options=countries)
    await callback.message.answer(
        "Выберите одну или несколько стран:",
        reply_markup=country_multiselect_keyboard(
            countries,
            selected,
            prefix="crmct",
            done_callback="crm:countries_done",
            clear_callback="crm:countries_clear",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crmct:"))
async def crm_country_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    countries = list(data.get("crm_country_options") or [])
    try:
        country = countries[int(callback.data.split(":", 1)[1])]
    except (ValueError, IndexError):
        await callback.answer("Страна не найдена", show_alert=True)
        return
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    selected = set(filters.get("countries") or [])
    if country in selected:
        selected.remove(country)
    else:
        selected.add(country)
    if selected:
        filters["countries"] = sorted(selected)
    else:
        filters.pop("countries", None)
    await state.update_data(crm_filters=filters)
    await callback.message.edit_reply_markup(
        reply_markup=country_multiselect_keyboard(
            countries,
            selected,
            prefix="crmct",
            done_callback="crm:countries_done",
            clear_callback="crm:countries_clear",
        )
    )
    await callback.answer("Выбор обновлён")


@router.callback_query(F.data == "crm:countries_clear")
async def crm_countries_clear(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    filters.pop("countries", None)
    countries = list(data.get("crm_country_options") or [])
    await state.update_data(crm_filters=filters)
    await callback.message.edit_reply_markup(
        reply_markup=country_multiselect_keyboard(
            countries,
            set(),
            prefix="crmct",
            done_callback="crm:countries_done",
            clear_callback="crm:countries_clear",
        )
    )
    await callback.answer("Выбор очищен")


@router.callback_query(F.data == "crm:countries_done")
async def crm_countries_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    await callback.message.answer(
        "Фильтр стран сохранён.",
        reply_markup=crm_filters_keyboard(
            age_mode=str(data.get("crm_age_mode") or "all"),
            selected_countries=len(filters.get("countries") or []),
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "crm:apply")
async def crm_apply(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    data = await state.get_data()
    filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    repo = UserRepository(session)
    count = await repo.count_audience(
        filters,
        now=utcnow(),
        active_days=settings.active_user_days,
        new_days=settings.new_user_days,
    )
    users = await repo.audience_page(
        filters,
        now=utcnow(),
        active_days=settings.active_user_days,
        new_days=settings.new_user_days,
        offset=0,
        limit=30,
    )
    await callback.message.answer(
        f"Найдено пользователей: {count}. Показаны первые {len(users)}.",
        reply_markup=users_results_keyboard(users),
    )
    await callback.answer()


@router.callback_query(F.data == "crm:export")
async def crm_export_prompt(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Какую базу выгрузить?",
        reply_markup=crm_export_scope_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crmexp:"))
async def crm_export(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    scope = callback.data.split(":", 1)[1]
    data = await state.get_data()
    filters = None
    if scope == "filtered":
        filters = dict(data.get("crm_filters") or {"subscribed_only": False})
    service = ExportService(
        session,
        active_user_days=settings.active_user_days,
        new_user_days=settings.new_user_days,
    )
    content = await service.users_xlsx(filters)
    filename = "users_filtered.xlsx" if filters is not None else "users_full.xlsx"
    await callback.message.answer_document(BufferedInputFile(content, filename=filename))
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="crm_users_exported",
        entity_type="users",
        now=utcnow(),
        metadata={"scope": scope, "filters": filters or {}},
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
    await callback.message.answer(
        "\n".join(lines) if actions else "Журнал пока пуст.",
        reply_markup=back_to_admin_keyboard(),
    )
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
        "Изменение системных параметров выполняется через переменные окружения Railway/.env.",
        reply_markup=back_to_admin_keyboard(),
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
    admins = [item for item in await AdminRepository(session).list_all() if item.is_active]
    names: dict[int, str] = {}
    users_repo = UserRepository(session)
    for item in admins:
        user = await users_repo.get_by_telegram_id(item.telegram_id)
        if user is not None:
            names[item.telegram_id] = " ".join(
                part for part in [user.first_name, user.last_name] if part
            ) or (f"@{user.username}" if user.username else "Без имени")
    await callback.message.answer(
        "<b>Управление админами</b>\n\n"
        "Администраторы добавляются и удаляются прямо здесь. "
        "SUPERADMIN_IDS в Railway остаётся резервным владельцем и не удаляется через бота.",
        reply_markup=admins_keyboard(admins, names),
    )
    await callback.answer()


@router.callback_query(F.data == "aadmin:new")
async def add_admin_start(callback: CallbackQuery, state: FSMContext, admin_model: Admin) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminManagementStates.telegram_id)
    await callback.message.answer(
        "Введите числовой Telegram ID нового администратора.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminManagementStates.telegram_id, F.text)
async def add_admin_id(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        telegram_id = int(message.text or "")
        if telegram_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Telegram ID должен быть положительным целым числом.")
        return
    existing = await AdminRepository(session).get_by_telegram_id(telegram_id)
    if existing is not None:
        await state.clear()
        await message.answer("Этот пользователь уже является администратором.")
        return
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    name = "Не зарегистрирован в боте"
    if user is not None:
        name = " ".join(part for part in [user.first_name, user.last_name] if part) or (
            f"@{user.username}" if user.username else "Без имени"
        )
    await state.update_data(telegram_id=telegram_id)
    await state.set_state(AdminManagementStates.confirm_add)
    await message.answer(
        f"Добавить администратора?\n\nИмя: {escape(name)}\nTelegram ID: <code>{telegram_id}</code>",
        reply_markup=confirm_action_keyboard(
            confirm_text="Подтвердить добавление",
            confirm_callback="aadmin:add_confirm",
            cancel_callback="adm:admins",
        ),
    )


@router.callback_query(AdminManagementStates.confirm_add, F.data == "aadmin:add_confirm")
async def add_admin_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await state.get_data()
    telegram_id = int(data["telegram_id"])
    admin = await AdminRepository(session).upsert(
        telegram_id=telegram_id,
        role=AdminRole.ADMIN,
        added_by_admin_id=admin_model.id,
    )
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="admin_added",
        entity_type="admin",
        entity_id=admin.id,
        now=utcnow(),
        metadata={"telegram_id": telegram_id},
    )
    await state.clear()
    await callback.message.answer(
        f"Администратор <code>{telegram_id}</code> добавлен.",
        reply_markup=back_to_admin_keyboard(),
    )
    await callback.answer("Добавлено", show_alert=True)


@router.callback_query(
    F.data.startswith("aadmin:") & ~F.data.in_({"aadmin:new", "aadmin:add_confirm"})
)
async def admin_card(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    target = await AdminRepository(session).get(callback.data.split(":", 1)[1])
    if target is None or not target.is_active:
        await callback.answer("Администратор не найден", show_alert=True)
        return
    user = await UserRepository(session).get_by_telegram_id(target.telegram_id)
    name = "Не зарегистрирован в боте"
    if user is not None:
        name = " ".join(part for part in [user.first_name, user.last_name] if part) or (
            f"@{user.username}" if user.username else "Без имени"
        )
    await callback.message.answer(
        f"<b>{escape(name)}</b>\n"
        f"Telegram ID: <code>{target.telegram_id}</code>\n"
        f"Роль: {target.role.value}",
        reply_markup=confirm_action_keyboard(
            confirm_text="Удалить администратора",
            confirm_callback=f"aadmoffq:{target.id}",
            cancel_callback="adm:admins",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aadmoffq:"))
async def deactivate_admin_question(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    target = await AdminRepository(session).get(callback.data.split(":", 1)[1])
    if target is None or not target.is_active:
        await callback.answer("Администратор не найден", show_alert=True)
        return
    if target.telegram_id in settings.superadmin_ids:
        await callback.answer(
            "Этот ID закреплён в SUPERADMIN_IDS Railway. Сначала замените резервного владельца.",
            show_alert=True,
        )
        return
    active = [item for item in await AdminRepository(session).list_all() if item.is_active]
    if len(active) <= 1:
        await callback.answer("Нельзя удалить последнего администратора", show_alert=True)
        return
    if target.id == admin_model.id:
        await callback.answer("Нельзя удалить собственный доступ", show_alert=True)
        return
    await callback.message.answer(
        f"Подтвердите удаление администратора <code>{target.telegram_id}</code>.",
        reply_markup=confirm_action_keyboard(
            confirm_text="Подтвердить удаление",
            confirm_callback=f"aadmoff:{target.id}",
            cancel_callback="adm:admins",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aadmoff:"))
async def deactivate_admin(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    if admin_model.role != AdminRole.SUPERADMIN:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    target = await AdminRepository(session).get(callback.data.split(":", 1)[1])
    if target is None or not target.is_active:
        await callback.answer("Администратор не найден", show_alert=True)
        return
    active = [item for item in await AdminRepository(session).list_all() if item.is_active]
    if len(active) <= 1 or target.telegram_id in settings.superadmin_ids:
        await callback.answer("Удаление заблокировано системой безопасности", show_alert=True)
        return
    if target.id == admin_model.id:
        await callback.answer("Нельзя удалить собственный доступ", show_alert=True)
        return
    await AdminRepository(session).deactivate(target, utcnow())
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="admin_removed",
        entity_type="admin",
        entity_id=target.id,
        now=utcnow(),
        metadata={"telegram_id": target.telegram_id},
    )
    await callback.message.answer(
        f"Администратор <code>{target.telegram_id}</code> удалён.",
        reply_markup=back_to_admin_keyboard(),
    )
    await callback.answer("Удалено", show_alert=True)
