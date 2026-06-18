from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.user import ticket_keyboard, tickets_keyboard
from app.models.broadcast_support import SupportAttachment, SupportMessage
from app.models.enums import FileType, TicketStatus
from app.models.users_events import User
from app.repositories.support import SupportRepository
from app.services.support import SupportService
from app.states.user import SupportStates
from app.texts.common import TICKET_STATUS_LABELS
from app.utils.time import utcnow
from app.utils.validators import validate_url

router = Router(name="user_support")


def incoming_file_size(message: Message) -> int | None:
    if message.photo:
        return message.photo[-1].file_size
    if message.document:
        return message.document.file_size
    return None


def build_attachment(message: Message, support_message_id: str) -> SupportAttachment | None:
    if message.photo:
        photo = message.photo[-1]
        return SupportAttachment(
            message_id=support_message_id,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_type=FileType.PHOTO,
            mime_type="image/jpeg",
            size=photo.file_size,
            caption=message.caption,
            position=0,
        )
    if message.document:
        document = message.document
        return SupportAttachment(
            message_id=support_message_id,
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            file_type=FileType.DOCUMENT,
            file_name=document.file_name,
            mime_type=document.mime_type,
            size=document.file_size,
            caption=message.caption,
            position=0,
        )
    candidate = (message.text or "").strip()
    if candidate:
        try:
            url = validate_url(candidate)
        except ValueError:
            return None
        return SupportAttachment(
            message_id=support_message_id,
            url=url,
            position=0,
        )
    return None


async def show_ticket_list(message: Message, session: AsyncSession, user: User) -> None:
    tickets = await SupportRepository(session).list_for_user(user.id)
    data = [
        (ticket.id, ticket.number, TICKET_STATUS_LABELS[ticket.status.value]) for ticket in tickets
    ]
    await message.answer(
        "Ваши обращения" if tickets else "У вас пока нет обращений.",
        reply_markup=tickets_keyboard(data),
    )


@router.message(F.text == "Поддержка")
async def support_menu(message: Message, session: AsyncSession, user_model: User) -> None:
    await show_ticket_list(message, session, user_model)


@router.callback_query(F.data == "tkt:list")
async def support_list_callback(
    callback: CallbackQuery, session: AsyncSession, user_model: User
) -> None:
    await show_ticket_list(callback.message, session, user_model)
    await callback.answer()


@router.callback_query(F.data == "tkt:new")
async def new_ticket(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupportStates.subject)
    await callback.message.answer("Укажите тему обращения.")
    await callback.answer()


@router.message(SupportStates.subject, F.text)
async def ticket_subject(message: Message, state: FSMContext) -> None:
    subject = (message.text or "").strip()
    if not 3 <= len(subject) <= 255:
        await message.answer("Тема должна содержать от 3 до 255 символов.")
        return
    await state.update_data(subject=subject)
    await state.set_state(SupportStates.message)
    await message.answer(
        "Опишите вопрос. Можно отправить текст, изображение или документ. "
        "Ссылку можно указать в тексте."
    )


@router.message(SupportStates.message)
async def ticket_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    user_model: User,
) -> None:
    data = await state.get_data()
    file_size = incoming_file_size(message)
    if file_size is not None and file_size > settings.max_upload_bytes:
        await message.answer("Файл превышает допустимый размер.")
        return
    service = SupportService(session, settings)
    ticket = await service.create_ticket(
        user=user_model,
        subject=str(data["subject"]),
        text=message.text or message.caption or "Вложение",
        now=utcnow(),
    )
    first_message = await session.scalar(
        select(SupportMessage)
        .where(SupportMessage.ticket_id == ticket.id)
        .order_by(SupportMessage.created_at.desc())
    )
    if first_message is not None:
        attachment = build_attachment(message, first_message.id)
        if attachment is not None:
            session.add(attachment)
    await service.notify_admins(message.bot, ticket)
    await state.clear()
    await message.answer(f"Обращение №{ticket.number} создано.")


@router.callback_query(F.data.startswith("tkt:"))
async def ticket_details(callback: CallbackQuery, session: AsyncSession, user_model: User) -> None:
    ticket_id = callback.data.split(":", maxsplit=1)[1]
    ticket = await SupportRepository(session).get(ticket_id)
    if ticket is None or ticket.user_id != user_model.id:
        await callback.answer("Обращение не найдено", show_alert=True)
        return
    messages = "\n\n".join(
        f"<b>{'Вы' if item.author_type.value == 'user' else 'Поддержка'}:</b> {item.text or '[вложение]'}"
        for item in ticket.messages[-10:]
    )
    text = (
        f"<b>Обращение №{ticket.number}</b>\n"
        f"Тема: {ticket.subject}\n"
        f"Статус: {TICKET_STATUS_LABELS[ticket.status.value]}\n\n{messages}"
    )
    await callback.message.answer(
        text, reply_markup=ticket_keyboard(ticket.id, ticket.status == TicketStatus.CLOSED)
    )
    for support_message in ticket.messages[-10:]:
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


@router.callback_query(F.data.startswith("tktr:"))
async def ticket_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(ticket_id=callback.data.split(":", maxsplit=1)[1])
    await state.set_state(SupportStates.reply)
    await callback.message.answer("Введите ответ.")
    await callback.answer()


@router.message(SupportStates.reply)
async def ticket_reply(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    user_model: User,
) -> None:
    data = await state.get_data()
    file_size = incoming_file_size(message)
    if file_size is not None and file_size > settings.max_upload_bytes:
        await message.answer("Файл превышает допустимый размер.")
        return
    ticket = await SupportRepository(session).get(str(data["ticket_id"]))
    if ticket is None:
        await state.clear()
        await message.answer("Обращение не найдено.")
        return
    support_message = await SupportService(session, settings).reply_as_user(
        ticket=ticket,
        user=user_model,
        text=message.text or message.caption or "Вложение",
        now=utcnow(),
    )
    attachment = build_attachment(message, support_message.id)
    if attachment is not None:
        session.add(attachment)
    await state.clear()
    await message.answer("Ответ отправлен.")


@router.callback_query(F.data.startswith("tkto:"))
async def reopen_ticket(callback: CallbackQuery, session: AsyncSession, user_model: User) -> None:
    ticket_id = callback.data.split(":", maxsplit=1)[1]
    ticket = await SupportRepository(session).get(ticket_id)
    if ticket is None or ticket.user_id != user_model.id:
        await callback.answer("Обращение не найдено", show_alert=True)
        return
    ticket.status = TicketStatus.NEW
    ticket.closed_at = None
    await callback.answer("Обращение открыто повторно", show_alert=True)
