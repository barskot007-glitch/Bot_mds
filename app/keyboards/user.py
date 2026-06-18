from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.content_audit import FAQ
from app.models.enums import RegistrationStatus
from app.models.users_events import Event, Registration
from app.texts.common import EVENT_STATUS_LABELS, REGISTRATION_STATUS_LABELS
from app.utils.time import format_datetime


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мероприятия", callback_data="menu:events")],
            [
                InlineKeyboardButton(text="📡 М'МДС", url="https://t.me/MDS_molod"),
                InlineKeyboardButton(text="📡 МДС", url="https://t.me/mosdoms"),
            ],
            [InlineKeyboardButton(text="📞 Связаться с нами", callback_data="menu:contact")],
            [
                InlineKeyboardButton(text="Мои регистрации", callback_data="menu:registrations"),
                InlineKeyboardButton(text="История участия", callback_data="menu:history"),
            ],
            [
                InlineKeyboardButton(text="FAQ", callback_data="menu:faq"),
                InlineKeyboardButton(text="Настройки уведомлений", callback_data="menu:settings"),
            ],
        ]
    )


def consent_keyboard(
    prefix: str,
    *,
    yes_text: str = "Да",
    no_text: str = "Нет",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=yes_text, callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text=no_text, callback_data=f"{prefix}:no"),
            ]
        ]
    )


def events_list_keyboard(
    events: list[Event], page: int, has_next: bool, filter_key: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Все актуальные", callback_data="evflt:all"),
        InlineKeyboardButton(text="Регистрация открыта", callback_data="evflt:open"),
    )
    builder.row(InlineKeyboardButton(text="На ближайшие 7 дней", callback_data="evflt:week"))
    for event in events:
        builder.button(text=event.title[:48], callback_data=f"ev:{event.id}")
    builder.adjust(1)
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="Назад", callback_data=f"evl:{filter_key}:{page - 1}")
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(text="Далее", callback_data=f"evl:{filter_key}:{page + 1}")
        )
    if navigation:
        builder.row(*navigation)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="user:menu"))
    return builder.as_markup()


def event_card_keyboard(
    event: Event,
    registration: Registration | None,
    tracked_links: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    active = registration and registration.status != RegistrationStatus.CANCELLED
    if event.registration_enabled and event.status.value in {"published", "registration_closed"}:
        if active:
            builder.button(text="Отменить регистрацию", callback_data=f"evc:{event.id}")
        else:
            builder.button(text="Зарегистрироваться", callback_data=f"evr:{event.id}")
    for label, url in tracked_links:
        builder.button(text=label[:64], url=url)
    for file in event.files[:5]:
        label = file.file_name or ("Изображение" if file.file_type.value == "photo" else "Документ")
        builder.button(text=f"Файл: {label[:36]}", callback_data=f"evf:{file.id}")
    builder.button(text="К списку", callback_data="evl:all:0")
    builder.adjust(1)
    return builder.as_markup()


def event_card_text(event: Event, registration: Registration | None, timezone_name: str) -> str:
    status = EVENT_STATUS_LABELS.get(event.status.value, event.status.value)
    location = ", ".join(item for item in [event.country, event.city, event.address] if item)
    lines = [
        f"<b>{event.title}</b>",
        event.full_description or event.short_description or "Описание не указано.",
        "",
        f"Начало: {format_datetime(event.start_at, timezone_name)}",
        f"Окончание: {format_datetime(event.end_at, timezone_name)}",
        f"Место: {location or 'не указано'}",
        f"Статус: {status}",
    ]
    if event.capacity:
        lines.append(f"Лимит участников: {event.capacity}")
    if registration:
        lines.append(
            f"Ваша регистрация: {REGISTRATION_STATUS_LABELS.get(registration.status.value, registration.status.value)}"
        )
    return "\n".join(lines)


def registrations_keyboard(registrations: list[Registration]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for registration in registrations:
        builder.button(
            text=f"{registration.event.title[:36]} — {REGISTRATION_STATUS_LABELS[registration.status.value]}",
            callback_data=f"ev:{registration.event_id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="user:menu"))
    return builder.as_markup()


def faq_keyboard(items: list[FAQ]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=item.question[:55], callback_data=f"faq:{item.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="user:menu"))
    return builder.as_markup()


def settings_keyboard(subscribed: bool) -> InlineKeyboardMarkup:
    label = "Отписаться от уведомлений" if subscribed else "Подписаться на уведомления"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="sub:toggle")],
            [InlineKeyboardButton(text="Главное меню", callback_data="user:menu")],
        ]
    )


def tickets_keyboard(ticket_ids: list[tuple[str, int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket_id, number, status in ticket_ids:
        builder.button(text=f"№{number} — {status}", callback_data=f"tkt:{ticket_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Новое обращение", callback_data="tkt:new"))
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="user:menu"))
    return builder.as_markup()


def ticket_keyboard(ticket_id: str, closed: bool) -> InlineKeyboardMarkup:
    rows = []
    if not closed:
        rows.append([InlineKeyboardButton(text="Ответить", callback_data=f"tktr:{ticket_id}")])
    else:
        rows.append(
            [InlineKeyboardButton(text="Открыть повторно", callback_data=f"tkto:{ticket_id}")]
        )
    rows.append([InlineKeyboardButton(text="К обращениям", callback_data="tkt:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
