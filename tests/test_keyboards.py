from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.keyboards.admin import (
    admin_menu,
    admins_keyboard,
    broadcast_actions,
    broadcast_media_keyboard,
    broadcasts_keyboard,
    event_actions,
    event_edit_fields,
    event_media_keyboard,
    events_keyboard,
    faq_actions,
    faq_admin_keyboard,
    participants_keyboard,
    support_admin_keyboard,
    support_ticket_actions,
    text_delete_confirmation,
    text_groups_keyboard,
    text_item_actions,
    text_items_keyboard,
    user_card_keyboard,
    users_admin_keyboard,
    users_results_keyboard,
)
from app.keyboards.user import (
    event_card_keyboard,
    events_list_keyboard,
    faq_keyboard,
    main_menu,
    registrations_keyboard,
    ticket_keyboard,
    tickets_keyboard,
)
from app.models.broadcast_support import (
    Broadcast,
    BroadcastButton,
    BroadcastFile,
    SupportTicket,
)
from app.models.content_audit import FAQ, Admin, BotText
from app.models.enums import (
    AdminRole,
    BroadcastStatus,
    EventStatus,
    FileType,
    RegistrationStatus,
    TicketStatus,
)
from app.models.users_events import Event, EventFile, EventLink, Registration, User


def callback_lengths(markup: InlineKeyboardMarkup | ReplyKeyboardMarkup) -> list[int]:
    if isinstance(markup, ReplyKeyboardMarkup):
        return []
    return [
        len(button.callback_data.encode("utf-8"))
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_callback_data_respects_telegram_limit() -> None:
    now = datetime.now(UTC)
    event = Event(
        id="1" * 36,
        title="Событие",
        start_at=now,
        timezone="UTC",
        status=EventStatus.DRAFT,
    )
    event.files = [
        EventFile(
            id="2" * 36,
            event_id=event.id,
            file_id="file",
            file_unique_id="unique",
            file_type=FileType.PHOTO,
            position=0,
        )
    ]
    event.links = [
        EventLink(
            id="3" * 36,
            event_id=event.id,
            title="Ссылка",
            url="https://example.com",
            position=0,
        )
    ]
    user = User(
        id="4" * 36,
        telegram_id=100,
        registered_at=now,
        last_activity_at=now,
    )
    registration = Registration(
        id="5" * 36,
        user_id=user.id,
        event_id=event.id,
        registered_at=now,
        status=RegistrationStatus.REGISTERED,
    )
    registration.user = user
    registration.event = event

    broadcast = Broadcast(
        id="6" * 36,
        title="Рассылка",
        text="Текст",
        status=BroadcastStatus.DRAFT,
        audience_filter={},
    )
    broadcast.files = [
        BroadcastFile(
            id="7" * 36,
            broadcast_id=broadcast.id,
            file_id="file",
            file_unique_id="unique",
            file_type=FileType.PHOTO,
            position=0,
        )
    ]
    broadcast.buttons = [
        BroadcastButton(
            id="8" * 36,
            broadcast_id=broadcast.id,
            text="Кнопка",
            url="https://example.com",
            position=0,
        )
    ]
    faq = FAQ(id="9" * 36, question="Вопрос", answer="Ответ")
    ticket = SupportTicket(
        id="a" * 36,
        number=1,
        user_id=user.id,
        subject="Тема",
        status=TicketStatus.NEW,
    )
    admin = Admin(id="b" * 36, telegram_id=1, role=AdminRole.ADMIN)

    bot_text = BotText(
        id="c" * 36,
        text_key="registration_name",
        content="Текст",
        is_active=True,
        position=0,
    )

    markups = [
        events_keyboard([event], 0, True),
        event_actions(event),
        event_edit_fields(event.id),
        event_media_keyboard(event),
        participants_keyboard([registration], event.id),
        broadcasts_keyboard([broadcast], 0, True),
        broadcast_actions(broadcast),
        broadcast_media_keyboard(broadcast),
        faq_admin_keyboard([faq]),
        faq_actions(faq),
        support_admin_keyboard([ticket]),
        support_ticket_actions(ticket),
        admins_keyboard([admin]),
        events_list_keyboard([event], 0, True, "all"),
        event_card_keyboard(event, registration, []),
        registrations_keyboard([registration]),
        faq_keyboard([faq]),
        tickets_keyboard([(ticket.id, ticket.number, "Новое")]),
        ticket_keyboard(ticket.id, False),
        main_menu(),
        text_groups_keyboard([("registration_name", "Запрос имени", 10, 10)]),
        text_items_keyboard("registration_name", [bot_text]),
        text_item_actions(bot_text),
        text_delete_confirmation(bot_text),
        users_admin_keyboard(),
        users_results_keyboard([user]),
        user_card_keyboard(user.id),
    ]

    assert max(length for markup in markups for length in callback_lengths(markup)) <= 64


def test_faq_is_hidden_from_admin_menu() -> None:
    markup = admin_menu()
    labels = [button.text for row in markup.inline_keyboard for button in row]

    assert "FAQ" not in labels
    assert "Статистика" in labels


def test_support_ticket_actions_are_simplified() -> None:
    now = datetime.now(UTC)
    user = User(
        id="d" * 36,
        telegram_id=200,
        registered_at=now,
        last_activity_at=now,
    )
    ticket = SupportTicket(
        id="e" * 36,
        number=2,
        user_id=user.id,
        subject="Обращение",
        status=TicketStatus.NEW,
    )
    markup = support_ticket_actions(ticket)
    labels = [button.text for row in markup.inline_keyboard for button in row]

    assert labels == ["Данные пользователя", "Ответить", "Назад"]
    assert "Назначить на себя" not in labels
    assert "Закрыть" not in labels


def test_broadcast_card_hides_unneeded_buttons() -> None:
    broadcast = Broadcast(
        id="f" * 36,
        title="Рассылка",
        text="Текст",
        status=BroadcastStatus.DRAFT,
        audience_filter={},
    )
    broadcast.files = []
    broadcast.buttons = [
        BroadcastButton(
            id="1" * 36,
            broadcast_id=broadcast.id,
            text="Скрытая кнопка",
            url="https://example.com",
            position=0,
        )
    ]

    actions = broadcast_actions(broadcast)
    action_labels = [button.text for row in actions.inline_keyboard for button in row]
    media = broadcast_media_keyboard(broadcast)
    media_labels = [button.text for row in media.inline_keyboard for button in row]

    assert "Добавить кнопку" not in action_labels
    assert "Получатели CSV" not in action_labels
    assert "Сегмент CSV" not in action_labels
    assert "Получатели XLSX" in action_labels
    assert "Сегмент XLSX" in action_labels
    assert "Файлы" not in action_labels
    assert "Добавить кнопку" not in media_labels
    assert not any(label.startswith("Удалить кнопку:") for label in media_labels)


def test_admin_menu_hides_settings_and_export_uses_only_xlsx() -> None:
    from app.keyboards.admin import export_keyboard

    menu_labels = [button.text for row in admin_menu().inline_keyboard for button in row]
    export_labels = [button.text for row in export_keyboard().inline_keyboard for button in row]

    assert "Настройки" not in menu_labels
    assert all("CSV" not in label for label in export_labels)
    assert "Пользователи XLSX" in export_labels
    assert "Обращения XLSX" in export_labels
    assert "История участия XLSX" in export_labels


def test_support_finish_button_appears_after_admin_reply() -> None:
    ticket = SupportTicket(
        id="8" * 36,
        number=7,
        user_id="9" * 36,
        subject="Вопрос",
        status=TicketStatus.WAITING_USER,
    )
    labels = [
        button.text for row in support_ticket_actions(ticket).inline_keyboard for button in row
    ]
    assert "Завершить разговор" in labels
