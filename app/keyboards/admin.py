from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.broadcast_support import Broadcast, SupportTicket
from app.models.content_audit import FAQ, Admin, BotText
from app.models.users_events import Event, Registration, User
from app.texts.common import BROADCAST_STATUS_LABELS, EVENT_STATUS_LABELS, TICKET_STATUS_LABELS


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мероприятия", callback_data="adm:events"),
                InlineKeyboardButton(text="Рассылки", callback_data="adm:broadcasts"),
            ],
            [
                InlineKeyboardButton(text="Пользователи", callback_data="adm:users"),
                InlineKeyboardButton(text="Обращения", callback_data="adm:support"),
            ],
            [
                InlineKeyboardButton(text="FAQ", callback_data="adm:faq"),
                InlineKeyboardButton(text="Статистика", callback_data="adm:stats"),
            ],
            [
                InlineKeyboardButton(text="Экспорт", callback_data="adm:export"),
                InlineKeyboardButton(text="Журнал действий", callback_data="adm:logs"),
            ],
            [
                InlineKeyboardButton(text="Библиотека текстов", callback_data="adm:texts"),
                InlineKeyboardButton(text="Настройки", callback_data="adm:settings"),
            ],
            [InlineKeyboardButton(text="Администраторы", callback_data="adm:admins")],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
            [InlineKeyboardButton(text="Главное меню", callback_data="adm:menu")],
        ]
    )


def skip_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="adm:skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
            [InlineKeyboardButton(text="Главное меню", callback_data="adm:menu")],
        ]
    )


def events_keyboard(events: list[Event], page: int, has_next: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать мероприятие", callback_data="aev:new")
    for event in events:
        status = EVENT_STATUS_LABELS.get(event.status.value, event.status.value)
        builder.button(text=f"{event.title[:35]} · {status}", callback_data=f"aev:{event.id}")
    builder.adjust(1)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="Назад", callback_data=f"aevl:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Далее", callback_data=f"aevl:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def event_actions(event: Event) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if event.status.value == "draft":
        rows.append([InlineKeyboardButton(text="Опубликовать", callback_data=f"aevpub:{event.id}")])
    rows.append(
        [
            InlineKeyboardButton(text="Редактировать", callback_data=f"aevedit:{event.id}"),
            InlineKeyboardButton(text="Файлы и ссылки", callback_data=f"aevmedia:{event.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Участники", callback_data=f"aevpart:{event.id}"),
            InlineKeyboardButton(text="Статистика", callback_data=f"aevstat:{event.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Отключить регистрацию"
                if event.registration_enabled
                else "Включить регистрацию",
                callback_data=f"aevreg:{event.id}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Напоминание", callback_data=f"aevrem:{event.id}"),
            InlineKeyboardButton(text="Сообщение участникам", callback_data=f"aevmsg:{event.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Архивировать", callback_data=f"aevarc:{event.id}"),
            InlineKeyboardButton(text="Отменить событие", callback_data=f"aevcan:{event.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Удалить", callback_data=f"aevdel:{event.id}")])
    rows.append([InlineKeyboardButton(text="К списку", callback_data="adm:events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete(prefix: str, entity_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить удаление", callback_data=f"{prefix}:{entity_id}"
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
        ]
    )


def event_edit_fields(event_id: str) -> InlineKeyboardMarkup:
    fields = [
        ("Название", "t"),
        ("Краткое описание", "s"),
        ("Полное описание", "d"),
        ("Дата начала", "b"),
        ("Дата окончания", "e"),
        ("Страна", "c"),
        ("Город", "y"),
        ("Адрес", "a"),
        ("Лимит", "l"),
        ("Ссылка подробнее", "u"),
        ("Ссылка на карту", "m"),
        ("Широта", "x"),
        ("Долгота", "o"),
        ("Часовой пояс", "z"),
        ("Дедлайн регистрации", "r"),
        ("Автопубликация", "p"),
    ]
    builder = InlineKeyboardBuilder()
    for label, field_key in fields:
        builder.button(text=label, callback_data=f"aef:{event_id}:{field_key}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"aev:{event_id}"))
    return builder.as_markup()


def event_media_keyboard(event: Event) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Добавить файл", callback_data=f"aevaddfile:{event.id}"),
        InlineKeyboardButton(text="Добавить ссылку", callback_data=f"aevaddlink:{event.id}"),
    )
    for file in event.files:
        label = (file.file_name or file.file_type.value)[:24]
        builder.row(
            InlineKeyboardButton(text="↑", callback_data=f"aefup:{file.id}"),
            InlineKeyboardButton(text="↓", callback_data=f"aefdn:{file.id}"),
            InlineKeyboardButton(text=f"Удалить файл: {label}", callback_data=f"aefrm:{file.id}"),
        )
    for link in event.links:
        builder.row(
            InlineKeyboardButton(text="↑", callback_data=f"aelup:{link.id}"),
            InlineKeyboardButton(text="↓", callback_data=f"aeldn:{link.id}"),
            InlineKeyboardButton(
                text=f"Удалить ссылку: {link.title[:24]}", callback_data=f"aelrm:{link.id}"
            ),
        )
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"aev:{event.id}"))
    return builder.as_markup()


def participants_keyboard(registrations: list[Registration], event_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for registration in registrations:
        name = (
            registration.user.username
            or registration.user.first_name
            or str(registration.user.telegram_id)
        )
        builder.row(
            InlineKeyboardButton(
                text=f"{name[:22]}: был", callback_data=f"att:y:{registration.id}"
            ),
            InlineKeyboardButton(text="не был", callback_data=f"att:n:{registration.id}"),
        )
    builder.row(
        InlineKeyboardButton(text="Экспорт CSV", callback_data=f"aevpexp:{event_id}:csv"),
        InlineKeyboardButton(text="Экспорт XLSX", callback_data=f"aevpexp:{event_id}:xlsx"),
    )
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"aev:{event_id}"))
    return builder.as_markup()


def broadcasts_keyboard(items: list[Broadcast], page: int, has_next: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать рассылку", callback_data="abc:new")
    for item in items:
        builder.button(
            text=f"{item.title[:35]} · {BROADCAST_STATUS_LABELS[item.status.value]}",
            callback_data=f"abc:{item.id}",
        )
    builder.adjust(1)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="Назад", callback_data=f"abcl:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Далее", callback_data=f"abcl:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def audience_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Все подписанные", callback_data="aud:all"),
                InlineKeyboardButton(text="Все пользователи", callback_data="aud:everyone"),
            ],
            [
                InlineKeyboardButton(text="Страна", callback_data="aud:country"),
                InlineKeyboardButton(text="Возрастная группа", callback_data="aud:age"),
            ],
            [
                InlineKeyboardButton(text="Активные", callback_data="aud:active"),
                InlineKeyboardButton(text="Неактивные", callback_data="aud:inactive"),
                InlineKeyboardButton(text="Новые", callback_data="aud:new"),
            ],
            [
                InlineKeyboardButton(text="Новые: период", callback_data="aud:new_days"),
                InlineKeyboardButton(text="Дата регистрации", callback_data="aud:period"),
            ],
            [
                InlineKeyboardButton(
                    text="Регистрация на событие", callback_data="aud:event_registered"
                ),
                InlineKeyboardButton(text="Посетили событие", callback_data="aud:event_attended"),
            ],
            [InlineKeyboardButton(text="Участвовали в событиях", callback_data="aud:event_any")],
            [InlineKeyboardButton(text="Продолжить", callback_data="aud:done")],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
        ]
    )


def broadcast_actions(item: Broadcast) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Предпросмотр", callback_data=f"abcprev:{item.id}"),
            InlineKeyboardButton(text="Тест себе", callback_data=f"abctest:{item.id}"),
        ],
        [
            InlineKeyboardButton(
                text="Изменить название", callback_data=f"abcedit:{item.id}:title"
            ),
            InlineKeyboardButton(text="Изменить текст", callback_data=f"abcedit:{item.id}:text"),
        ],
        [
            InlineKeyboardButton(text="Изменить аудиторию", callback_data=f"abcaud:{item.id}"),
            InlineKeyboardButton(text="Добавить файл", callback_data=f"abcfile:{item.id}"),
        ],
        [
            InlineKeyboardButton(text="Добавить кнопку", callback_data=f"abcbutton:{item.id}"),
            InlineKeyboardButton(text="Файлы и кнопки", callback_data=f"abcm:{item.id}"),
        ],
        [
            InlineKeyboardButton(text="Отправить сейчас", callback_data=f"abcsend:{item.id}"),
            InlineKeyboardButton(text="Запланировать", callback_data=f"abcplan:{item.id}"),
        ],
        [InlineKeyboardButton(text="Статистика", callback_data=f"abcstat:{item.id}")],
        [
            InlineKeyboardButton(text="Получатели CSV", callback_data=f"abcexp:{item.id}:csv"),
            InlineKeyboardButton(text="Получатели XLSX", callback_data=f"abcexp:{item.id}:xlsx"),
        ],
        [
            InlineKeyboardButton(text="Сегмент CSV", callback_data=f"abcseg:{item.id}:csv"),
            InlineKeyboardButton(text="Сегмент XLSX", callback_data=f"abcseg:{item.id}:xlsx"),
        ],
        [
            InlineKeyboardButton(text="Отменить рассылку", callback_data=f"abccancel:{item.id}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"abcdel:{item.id}"),
        ],
        [InlineKeyboardButton(text="К списку", callback_data="adm:broadcasts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_media_keyboard(item: Broadcast) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Добавить файл", callback_data=f"abcfile:{item.id}"),
        InlineKeyboardButton(text="Добавить кнопку", callback_data=f"abcbutton:{item.id}"),
    )
    for file in item.files:
        label = (file.file_name or file.file_type.value)[:22]
        builder.row(
            InlineKeyboardButton(text="↑", callback_data=f"abfu:{file.id}"),
            InlineKeyboardButton(text="↓", callback_data=f"abfd:{file.id}"),
            InlineKeyboardButton(text=f"Удалить: {label}", callback_data=f"abfr:{file.id}"),
        )
    for button in item.buttons:
        builder.row(
            InlineKeyboardButton(text="↑", callback_data=f"abbu:{button.id}"),
            InlineKeyboardButton(text="↓", callback_data=f"abbd:{button.id}"),
            InlineKeyboardButton(
                text=f"Удалить кнопку: {button.text[:18]}", callback_data=f"abbr:{button.id}"
            ),
        )
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"abc:{item.id}"))
    return builder.as_markup()


def faq_admin_keyboard(items: list[FAQ]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить FAQ", callback_data="afaq:new")
    for item in items:
        marker = "вкл" if item.is_published else "выкл"
        builder.button(text=f"{item.question[:40]} · {marker}", callback_data=f"afaq:{item.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def faq_actions(item: FAQ) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Редактировать вопрос", callback_data=f"afqeq:{item.id}"),
                InlineKeyboardButton(text="Редактировать ответ", callback_data=f"afqea:{item.id}"),
            ],
            [
                InlineKeyboardButton(text="Выше", callback_data=f"afqup:{item.id}"),
                InlineKeyboardButton(text="Ниже", callback_data=f"afqdn:{item.id}"),
            ],
            [InlineKeyboardButton(text="Включить/выключить", callback_data=f"afqtg:{item.id}")],
            [InlineKeyboardButton(text="Удалить", callback_data=f"afqdel:{item.id}")],
            [InlineKeyboardButton(text="К FAQ", callback_data="adm:faq")],
        ]
    )


def support_admin_keyboard(items: list[SupportTicket]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(
            text=f"№{item.number} · {TICKET_STATUS_LABELS[item.status.value]}",
            callback_data=f"ast:{item.id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def support_ticket_actions(ticket: SupportTicket) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ответить", callback_data=f"astr:{ticket.id}"),
                InlineKeyboardButton(
                    text="Назначить на себя", callback_data=f"astclaim:{ticket.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="В работе", callback_data=f"aststatus:{ticket.id}:in_progress"
                ),
                InlineKeyboardButton(
                    text="Решено", callback_data=f"aststatus:{ticket.id}:resolved"
                ),
            ],
            [
                InlineKeyboardButton(text="Закрыть", callback_data=f"aststatus:{ticket.id}:closed"),
                InlineKeyboardButton(text="Открыть", callback_data=f"aststatus:{ticket.id}:new"),
            ],
            [InlineKeyboardButton(text="К обращениям", callback_data="adm:support")],
        ]
    )


def export_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Пользователи CSV", callback_data="exp:users:csv"),
                InlineKeyboardButton(text="Пользователи XLSX", callback_data="exp:users:xlsx"),
            ],
            [
                InlineKeyboardButton(text="Обращения CSV", callback_data="exp:tickets:csv"),
                InlineKeyboardButton(text="Обращения XLSX", callback_data="exp:tickets:xlsx"),
            ],
            [
                InlineKeyboardButton(text="История участия CSV", callback_data="exp:history:csv"),
                InlineKeyboardButton(text="История участия XLSX", callback_data="exp:history:xlsx"),
            ],
            [InlineKeyboardButton(text="Главное меню", callback_data="adm:menu")],
        ]
    )


def admins_keyboard(admins: list[Admin]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить администратора", callback_data="aadmin:new")
    for item in admins:
        builder.button(
            text=f"{item.telegram_id} · {item.role.value}", callback_data=f"aadmin:{item.id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def roles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Admin", callback_data="arole:admin")],
            [InlineKeyboardButton(text="Moderator", callback_data="arole:moderator")],
            [InlineKeyboardButton(text="Support", callback_data="arole:support")],
            [InlineKeyboardButton(text="Superadmin", callback_data="arole:superadmin")],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")],
        ]
    )


def text_groups_keyboard(
    groups: list[tuple[str, str, int, int]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label, total, active in groups:
        builder.button(
            text=f"{label} · {active}/{total}",
            callback_data=f"atxg:{key}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="adm:menu"))
    return builder.as_markup()


def text_items_keyboard(text_key: str, items: list[BotText]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Добавить вариант", callback_data=f"atxnew:{text_key}"))
    for number, item in enumerate(items, start=1):
        marker = "вкл" if item.is_active else "выкл"
        preview = item.content.replace("\n", " ")[:34]
        builder.button(
            text=f"{number}. {preview} · {marker}",
            callback_data=f"atx:{item.id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="К группам", callback_data="adm:texts"))
    return builder.as_markup()


def text_item_actions(item: BotText) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Редактировать", callback_data=f"atxedit:{item.id}")],
            [
                InlineKeyboardButton(
                    text="Выключить" if item.is_active else "Включить",
                    callback_data=f"atxtoggle:{item.id}",
                ),
                InlineKeyboardButton(text="Удалить", callback_data=f"atxdelq:{item.id}"),
            ],
            [InlineKeyboardButton(text="Назад", callback_data=f"atxg:{item.text_key}")],
        ]
    )


def text_delete_confirmation(item: BotText) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить удаление", callback_data=f"atxdel:{item.id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"atx:{item.id}")],
        ]
    )


def users_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Найти пользователя", callback_data="ausr:search")],
            [InlineKeyboardButton(text="Последние регистрации", callback_data="ausr:recent")],
            [InlineKeyboardButton(text="Выгрузить базу", callback_data="adm:export")],
            [InlineKeyboardButton(text="Главное меню", callback_data="adm:menu")],
        ]
    )


def users_results_keyboard(users: list[User]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        name = (
            " ".join(part for part in [user.first_name, user.last_name] if part)
            or user.username
            or str(user.telegram_id)
        )
        builder.button(text=f"{name[:32]} · {user.telegram_id}", callback_data=f"ausr:{user.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Назад", callback_data="adm:users"))
    return builder.as_markup()


def user_card_keyboard(user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Имя", callback_data=f"auedit:{user_id}:first"),
                InlineKeyboardButton(text="Фамилия", callback_data=f"auedit:{user_id}:last"),
            ],
            [
                InlineKeyboardButton(text="Возраст", callback_data=f"auedit:{user_id}:age"),
                InlineKeyboardButton(text="Страна", callback_data=f"auedit:{user_id}:country"),
            ],
            [
                InlineKeyboardButton(
                    text="История участия", callback_data=f"auedit:{user_id}:history"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Вкл/выкл уведомления", callback_data=f"autoggle:{user_id}"
                )
            ],
            [InlineKeyboardButton(text="К пользователям", callback_data="adm:users")],
        ]
    )
