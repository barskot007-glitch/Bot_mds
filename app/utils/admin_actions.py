from __future__ import annotations

from typing import Any

ACTION_LABELS: dict[str, str] = {
    "event_created": "создал мероприятие",
    "event_updated": "изменил мероприятие",
    "event_published": "опубликовал мероприятие",
    "event_hidden": "скрыл мероприятие",
    "event_deleted": "удалил мероприятие",
    "event_participant_broadcast_started": "запустил сообщение участникам мероприятия",
    "event_participants_exported": "выгрузил список участников мероприятия",
    "event_statistics_exported": "выгрузил статистику мероприятия",
    "add_file": "добавил файл к мероприятию",
    "add_link": "добавил ссылку к мероприятию",
    "edit_field": "изменил данные мероприятия",
    "participant_message": "отправил сообщение участникам",
    "reminder": "изменил напоминание мероприятия",
    "broadcast_created": "создал рассылку",
    "broadcast_updated": "изменил рассылку",
    "broadcast_started": "запустил рассылку",
    "broadcast_deleted": "удалил рассылку",
    "broadcast_file": "добавил файл к рассылке",
    "broadcast_button": "изменил кнопку рассылки",
    "broadcast_recipients_exported": "выгрузил получателей рассылки",
    "broadcast_audience_exported": "выгрузил сегмент рассылки",
    "broadcast_statistics_exported": "выгрузил статистику рассылки",
    "crm_users_exported": "выгрузил базу пользователей",
    "users_exported": "выгрузил базу пользователей",
    "support_tickets_exported": "выгрузил обращения пользователей",
    "participation_history_exported": "выгрузил историю участия",
    "user_profile_updated": "изменил данные пользователя",
    "user_subscription_toggled": "изменил статус уведомлений пользователя",
    "admin_added": "добавил администратора",
    "admin_removed": "удалил администратора",
    "support_reply_sent": "ответил пользователю",
    "support_conversation_completed": "завершил обращение пользователя",
    "support_reply_sent_and_ticket_deleted": "ответил пользователю и завершил обращение",
    "bot_text_created": "добавил текст в библиотеку",
    "bot_text_updated": "изменил текст в библиотеке",
    "bot_text_toggled": "включил или выключил текст в библиотеке",
    "bot_text_deleted": "удалил текст из библиотеки",
}

ENTITY_LABELS: dict[str, str] = {
    "event": "мероприятие",
    "broadcast": "рассылка",
    "broadcasts": "рассылки",
    "user": "пользователь",
    "users": "пользователи",
    "admin": "администратор",
    "support_ticket": "обращение",
    "support_tickets": "обращения",
    "registrations": "история участия",
    "bot_text": "текст библиотеки",
}

FIELD_LABELS: dict[str, str] = {
    "first": "имя",
    "last": "фамилию",
    "age": "возраст",
    "country": "страну",
    "phone": "телефон",
    "email": "электронную почту",
    "history": "историю участия",
}


def human_action(action: str, metadata: dict[str, Any] | None = None) -> str:
    """Преобразует технический код действия в понятную русскую фразу."""
    label = ACTION_LABELS.get(action, "выполнил административное действие")
    details = metadata or {}

    if action == "user_profile_updated":
        field = FIELD_LABELS.get(str(details.get("field", "")))
        if field:
            return f"изменил {field} пользователя"
    if action in {"admin_added", "admin_removed"} and details.get("telegram_id"):
        return f"{label} с Telegram ID {details['telegram_id']}"
    if action.startswith("support_") and details.get("ticket_number"):
        return f"{label} №{details['ticket_number']}"

    return label


def human_entity(entity_type: str | None) -> str:
    if not entity_type:
        return ""
    return ENTITY_LABELS.get(entity_type, "")
