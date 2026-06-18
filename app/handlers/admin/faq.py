from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.admin import AdminFilter
from app.keyboards.admin import cancel_keyboard, confirm_delete, faq_actions, faq_admin_keyboard
from app.models.content_audit import Admin
from app.repositories.faq import FAQRepository
from app.services.permissions import PermissionService
from app.states.admin import AdminFAQStates
from app.utils.time import utcnow

router = Router(name="admin_faq")
router.message.filter(AdminFilter("faq"))
router.callback_query.filter(AdminFilter("faq"))


async def require_faq(admin: Admin) -> None:
    if not PermissionService.has_permission(admin, "faq"):
        raise PermissionError("Недостаточно прав для FAQ")


@router.callback_query(F.data == "adm:faq")
async def faq_list(callback: CallbackQuery, session: AsyncSession, admin_model: Admin) -> None:
    await require_faq(admin_model)
    items = await FAQRepository(session).list_all()
    await callback.message.answer("Управление FAQ", reply_markup=faq_admin_keyboard(items))
    await callback.answer()


@router.callback_query(F.data == "afaq:new")
async def faq_new(callback: CallbackQuery, state: FSMContext, admin_model: Admin) -> None:
    await require_faq(admin_model)
    await state.set_state(AdminFAQStates.question)
    await callback.message.answer("Введите вопрос.", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminFAQStates.question, F.text)
async def faq_question(message: Message, state: FSMContext) -> None:
    question = (message.text or "").strip()
    if not 3 <= len(question) <= 512:
        await message.answer("Вопрос должен содержать от 3 до 512 символов.")
        return
    await state.update_data(question=question)
    await state.set_state(AdminFAQStates.answer)
    await message.answer("Введите ответ до 4096 символов.", reply_markup=cancel_keyboard())


@router.message(AdminFAQStates.answer, F.text)
async def faq_answer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    answer = (message.text or "").strip()
    if not answer or len(answer) > 4096:
        await message.answer("Ответ обязателен и не должен превышать 4096 символов.")
        return
    data = await state.get_data()
    item = await FAQRepository(session).create(str(data["question"]), answer)
    await state.clear()
    await message.answer(f"FAQ создан: {item.question}", reply_markup=faq_actions(item))


@router.callback_query(F.data.startswith("afaq:") & ~F.data.in_({"afaq:new"}))
async def faq_card(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await FAQRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.answer(
        f"<b>{item.question}</b>\n\n{item.answer}\n\n"
        f"Публикация: {'включена' if item.is_published else 'отключена'}\n"
        f"Позиция: {item.position}",
        reply_markup=faq_actions(item),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("afqeq:"))
async def faq_edit_question_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(faq_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminFAQStates.edit_question)
    await callback.message.answer("Введите новый вопрос.", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminFAQStates.edit_question, F.text)
async def faq_edit_question(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if not 3 <= len(value) <= 512:
        await message.answer("Вопрос должен содержать от 3 до 512 символов.")
        return
    data = await state.get_data()
    item = await FAQRepository(session).get(str(data["faq_id"]))
    if item:
        item.question = value
    await state.clear()
    await message.answer("Вопрос обновлён.")


@router.callback_query(F.data.startswith("afqea:"))
async def faq_edit_answer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(faq_id=callback.data.split(":", 1)[1])
    await state.set_state(AdminFAQStates.edit_answer)
    await callback.message.answer("Введите новый ответ.", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminFAQStates.edit_answer, F.text)
async def faq_edit_answer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 4096:
        await message.answer("Ответ обязателен и не должен превышать 4096 символов.")
        return
    data = await state.get_data()
    item = await FAQRepository(session).get(str(data["faq_id"]))
    if item:
        item.answer = value
    await state.clear()
    await message.answer("Ответ обновлён.")


@router.callback_query(F.data.startswith("afqtg:"))
async def faq_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await FAQRepository(session).get(callback.data.split(":", 1)[1])
    if item:
        item.is_published = not item.is_published
    await callback.answer("Статус публикации изменён", show_alert=True)


@router.callback_query(F.data.startswith("afqup:") | F.data.startswith("afqdn:"))
async def faq_move(callback: CallbackQuery, session: AsyncSession) -> None:
    prefix, faq_id = callback.data.split(":", 1)
    item = await FAQRepository(session).get(faq_id)
    if item:
        item.position = max(0, item.position + (-1 if prefix == "afqup" else 1))
    await callback.answer("Позиция изменена", show_alert=True)


@router.callback_query(F.data.startswith("afqdel:"))
async def faq_delete_confirm(callback: CallbackQuery) -> None:
    faq_id = callback.data.split(":", 1)[1]
    await callback.message.answer(
        "Подтвердите удаление FAQ.", reply_markup=confirm_delete("afqdelok", faq_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("afqdelok:"))
async def faq_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    item = await FAQRepository(session).get(callback.data.split(":", 1)[1])
    if item:
        await FAQRepository(session).soft_delete(item, utcnow())
    await callback.answer("FAQ удалён", show_alert=True)
