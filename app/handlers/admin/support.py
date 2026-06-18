from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.filters.admin import AdminFilter
from app.keyboards.admin import cancel_keyboard, support_admin_keyboard, support_ticket_actions
from app.models.broadcast_support import SupportAttachment
from app.models.content_audit import Admin
from app.models.enums import FileType
from app.repositories.admins import AdminRepository
from app.repositories.support import SupportRepository
from app.services.permissions import PermissionService
from app.services.support import SupportService
from app.states.admin import AdminSupportStates
from app.texts.common import TICKET_STATUS_LABELS
from app.utils.time import format_datetime, utcnow

router = Router(name="admin_support")
router.message.filter(AdminFilter("support"))
router.callback_query.filter(AdminFilter("support"))


async def require_support(admin: Admin) -> None:
    if not PermissionService.has_permission(admin, "support"):
        raise PermissionError("Недостаточно прав для обращений")


@router.callback_query(F.data == "adm:support")
async def support_list(callback: CallbackQuery, session: AsyncSession, admin_model: Admin) -> None:
    await require_support(admin_model)
    items = await SupportRepository(session).list_open(0, 50)
    await callback.message.answer(
        "Обращения пользователей" if items else "Новых обращений нет.",
        reply_markup=support_admin_keyboard(items),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ast:") & ~F.data.startswith("astu:"))
async def support_card(callback: CallbackQuery, session: AsyncSession, admin_model: Admin) -> None:
    await require_support(admin_model)
    ticket = await SupportRepository(session).get(callback.data.split(":", 1)[1])
    if ticket is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    messages = "\n\n".join(
        f"<b>{'Пользователь' if msg.author_type.value == 'user' else 'Администратор'}:</b> "
        f"{escape(msg.text or '[вложение]')}"
        for msg in ticket.messages[-15:]
    )
    await callback.message.answer(
        f"<b>Обращение №{ticket.number}</b>\n"
        f"Статус: {TICKET_STATUS_LABELS[ticket.status.value]}\n\n{messages}",
        reply_markup=support_ticket_actions(ticket),
    )
    for support_message in ticket.messages[-15:]:
        for attachment in support_message.attachments:
            if attachment.file_type == FileType.PHOTO and attachment.file_id:
                await callback.bot.send_photo(
                    callback.from_user.id, attachment.file_id, caption=attachment.caption
                )
            elif attachment.file_id:
                await callback.bot.send_document(
                    callback.from_user.id, attachment.file_id, caption=attachment.caption
                )
    await callback.answer()


@router.callback_query(F.data.startswith("astu:"))
async def support_user_data(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
) -> None:
    await require_support(admin_model)
    ticket = await SupportRepository(session).get(callback.data.split(":", 1)[1])
    if ticket is None:
        await callback.answer("Обращение не найдено", show_alert=True)
        return
    user = ticket.user
    username = f"@{user.username}" if user.username else "не указан"
    name = " ".join(part for part in [user.first_name, user.last_name] if part) or "не указано"
    await callback.message.answer(
        "<b>Данные пользователя</b>\n\n"
        f"ФИО: {escape(name)}\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {escape(username)}\n"
        f"Возраст: {user.age if user.age is not None else 'не указан'}\n"
        f"Страна: {escape(user.country or 'не указана')}\n"
        f"Телефон: {escape(user.phone or 'не указан')}\n"
        f"Email: {escape(user.email or 'не указан')}\n"
        f"История участия: {escape(user.participation_history or 'не указана')}\n"
        f"Уведомления: {'включены' if user.is_subscribed else 'отключены'}\n"
        f"Регистрация: {format_datetime(user.registered_at, settings.default_timezone)}",
        reply_markup=support_ticket_actions(ticket),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("astfinish:"))
async def support_finish(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    await require_support(admin_model)
    ticket_id = callback.data.split(":", 1)[1]
    ticket = await SupportRepository(session).get(ticket_id)
    if ticket is None:
        await callback.answer("Обращение уже завершено", show_alert=True)
        return
    ticket_number = ticket.number
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="support_conversation_completed",
        entity_type="support_ticket",
        entity_id=ticket.id,
        now=utcnow(),
        metadata={"ticket_number": ticket_number},
    )
    await SupportRepository(session).delete_ticket(ticket.id)
    items = await SupportRepository(session).list_open(0, 50)
    await callback.message.answer(
        f"Разговор по обращению №{ticket_number} завершён. Обращение удалено из списка.",
        reply_markup=support_admin_keyboard(items),
    )
    await callback.answer("Разговор завершён", show_alert=True)


@router.callback_query(F.data.startswith("astr:"))
async def support_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(ticket_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminSupportStates.reply)
    await callback.message.answer("Введите ответ пользователю.", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminSupportStates.reply)
async def support_reply(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    admin_model: Admin,
    bot: Bot,
) -> None:
    data = await state.get_data()
    file_size = None
    if message.photo:
        file_size = message.photo[-1].file_size
    elif message.document:
        file_size = message.document.file_size
    if file_size is not None and file_size > settings.max_upload_bytes:
        await message.answer("Файл превышает допустимый размер.")
        return
    if not message.text and not message.caption and not message.photo and not message.document:
        await message.answer("Отправьте текст, фотографию или документ.")
        return
    ticket = await SupportRepository(session).get(str(data["ticket_id"]))
    if ticket is None:
        await state.clear()
        await message.answer("Обращение не найдено.")
        return
    support_message = await SupportService(session, settings).reply_as_admin(
        ticket=ticket,
        admin=admin_model,
        text=message.text or message.caption or "Вложение",
        now=utcnow(),
    )
    attachment: SupportAttachment | None = None
    if message.photo:
        photo = message.photo[-1]
        attachment = SupportAttachment(
            message_id=support_message.id,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_type=FileType.PHOTO,
            mime_type="image/jpeg",
            size=photo.file_size,
            caption=message.caption,
            position=0,
        )
    elif message.document:
        document = message.document
        attachment = SupportAttachment(
            message_id=support_message.id,
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            file_type=FileType.DOCUMENT,
            file_name=document.file_name,
            mime_type=document.mime_type,
            size=document.file_size,
            caption=message.caption,
            position=0,
        )
    if attachment is not None:
        session.add(attachment)
    response_text = message.text or message.caption or "Вложение"
    await bot.send_message(
        ticket.user.telegram_id,
        f"Ответ администратора:\n\n{response_text}",
    )
    if attachment and attachment.file_id:
        if attachment.file_type == FileType.PHOTO:
            await bot.send_photo(
                ticket.user.telegram_id, attachment.file_id, caption=attachment.caption
            )
        else:
            await bot.send_document(
                ticket.user.telegram_id, attachment.file_id, caption=attachment.caption
            )
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="support_reply_sent",
        entity_type="support_ticket",
        entity_id=ticket.id,
        now=utcnow(),
        metadata={"ticket_number": ticket.number},
    )
    await state.clear()
    await message.answer(
        "Ответ отправлен пользователю. Если вопрос закрыт, нажмите «Завершить разговор».",
        reply_markup=support_ticket_actions(ticket),
    )
