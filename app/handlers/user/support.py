from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.broadcast_support import SupportAttachment, SupportMessage
from app.models.enums import FileType
from app.models.users_events import User
from app.services.support import SupportService
from app.services.text_library import TextLibraryService
from app.states.user import SupportStates
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
        return SupportAttachment(message_id=support_message_id, url=url, position=0)
    return None


async def start_contact(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await state.set_state(SupportStates.message)
    await state.update_data(subject="Обращение из главного меню")
    await message.answer(
        await TextLibraryService(session).get("support_message"),
        parse_mode=None,
    )


@router.message(F.text == "📞 Связаться с нами")
async def contact_from_reply_menu(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await start_contact(message, state, session)


@router.callback_query(F.data == "menu:contact")
async def contact_from_main_menu(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await start_contact(callback.message, state, session)
    await callback.answer()


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
    if not message.text and not message.caption and not message.photo and not message.document:
        await message.answer("Отправьте текст, фотографию или документ одним сообщением.")
        return
    service = SupportService(session, settings)
    ticket = await service.create_ticket(
        user=user_model,
        subject=str(data.get("subject") or "Обращение из главного меню"),
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
    await service.notify_admins(message.bot, ticket, user_model, message)
    await state.clear()
    await message.answer("Ваше сообщение отправлено администраторам. Ответ придёт в этот чат.")
