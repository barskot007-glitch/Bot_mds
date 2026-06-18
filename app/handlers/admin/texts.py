from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    cancel_keyboard,
    text_delete_confirmation,
    text_groups_keyboard,
    text_item_actions,
    text_items_keyboard,
)
from app.models.content_audit import Admin
from app.repositories.admins import AdminRepository
from app.repositories.text_library import TextLibraryRepository
from app.services.permissions import PermissionService
from app.services.text_library import TextLibraryService
from app.states.admin import AdminTextStates
from app.texts.library import TEXT_GROUP_LABELS
from app.utils.time import utcnow

router = Router(name="admin_texts")
MAX_TEXT_LENGTH = 4096


def normalize_content(value: str) -> str:
    return value.strip()


@router.callback_query(F.data == "adm:texts")
async def text_groups(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    groups = await TextLibraryService(session).groups()
    await callback.message.answer(
        "<b>Библиотека текстов</b>\n\n"
        "Выберите этап. Активный вариант выбирается случайно при каждом новом сценарии. "
        "Можно добавлять, редактировать, отключать и удалять варианты.",
        reply_markup=text_groups_keyboard(groups),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("atxg:"))
async def text_group_card(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    text_key = callback.data.split(":", 1)[1]
    label = TEXT_GROUP_LABELS.get(text_key)
    if label is None:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    items = await TextLibraryService(session).list_items(text_key)
    await callback.message.answer(
        f"<b>{label}</b>\n\nВариантов: {len(items)}",
        reply_markup=text_items_keyboard(text_key, items),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("atx:") & ~F.data.startswith("atx:new"))
async def text_item_card(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    item = await TextLibraryRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Текст не найден", show_alert=True)
        return
    status = "включён" if item.is_active else "выключен"
    label = TEXT_GROUP_LABELS.get(item.text_key, item.text_key)
    await callback.message.answer(
        f"Группа: {label}\nСтатус: {status}\n\n{item.content}",
        reply_markup=text_item_actions(item),
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("atxnew:"))
async def text_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    text_key = callback.data.split(":", 1)[1]
    if text_key not in TEXT_GROUP_LABELS:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    await state.set_state(AdminTextStates.content)
    await state.update_data(text_key=text_key)
    await callback.message.answer(
        f"Отправьте новый вариант текста для группы «{TEXT_GROUP_LABELS[text_key]}».\n\n"
        f"Максимальная длина — {MAX_TEXT_LENGTH} символов.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminTextStates.content, F.text)
async def text_add_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    content = normalize_content(message.text or "")
    if not 1 <= len(content) <= MAX_TEXT_LENGTH:
        await message.answer(f"Текст должен содержать от 1 до {MAX_TEXT_LENGTH} символов.")
        return
    data = await state.get_data()
    text_key = str(data["text_key"])
    item = await TextLibraryRepository(session).create(
        text_key=text_key,
        content=content,
        created_by_admin_id=admin_model.id,
    )
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="bot_text_created",
        entity_type="bot_text",
        entity_id=item.id,
        now=utcnow(),
        metadata={"text_key": text_key},
    )
    await state.clear()
    items = await TextLibraryService(session).list_items(text_key)
    await message.answer(
        "Новый вариант добавлен и сразу включён.",
        reply_markup=text_items_keyboard(text_key, items),
    )


@router.callback_query(F.data.startswith("atxedit:"))
async def text_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    item = await TextLibraryRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await state.set_state(AdminTextStates.edit_content)
    await state.update_data(text_id=item.id)
    await callback.message.answer(
        f"Текущий текст:\n\n{item.content}\n\nОтправьте новый текст.",
        reply_markup=cancel_keyboard(),
        parse_mode=None,
    )
    await callback.answer()


@router.message(AdminTextStates.edit_content, F.text)
async def text_edit_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    content = normalize_content(message.text or "")
    if not 1 <= len(content) <= MAX_TEXT_LENGTH:
        await message.answer(f"Текст должен содержать от 1 до {MAX_TEXT_LENGTH} символов.")
        return
    data = await state.get_data()
    repository = TextLibraryRepository(session)
    item = await repository.get(str(data["text_id"]))
    if item is None:
        await state.clear()
        await message.answer("Текст не найден.")
        return
    await repository.update_content(item, content)
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="bot_text_updated",
        entity_type="bot_text",
        entity_id=item.id,
        now=utcnow(),
        metadata={"text_key": item.text_key},
    )
    await state.clear()
    await message.answer(
        "Текст обновлён.",
        reply_markup=text_item_actions(item),
    )


@router.callback_query(F.data.startswith("atxtoggle:"))
async def text_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    repository = TextLibraryRepository(session)
    item = await repository.get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await repository.toggle(item)
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="bot_text_toggled",
        entity_type="bot_text",
        entity_id=item.id,
        now=utcnow(),
        metadata={"is_active": item.is_active, "text_key": item.text_key},
    )
    await callback.message.answer(
        f"Вариант {'включён' if item.is_active else 'выключен'}.",
        reply_markup=text_item_actions(item),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("atxdelq:"))
async def text_delete_question(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    item = await TextLibraryRepository(session).get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.message.answer(
        "Удалить этот вариант текста? Действие скроет его из библиотеки.",
        reply_markup=text_delete_confirmation(item),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("atxdel:"))
async def text_delete(
    callback: CallbackQuery,
    session: AsyncSession,
    admin_model: Admin,
) -> None:
    if not PermissionService.has_permission(admin_model, "texts"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    repository = TextLibraryRepository(session)
    item = await repository.get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer("Текст не найден", show_alert=True)
        return
    text_key = item.text_key
    await repository.soft_delete(item)
    await AdminRepository(session).log_action(
        admin_id=admin_model.id,
        action="bot_text_deleted",
        entity_type="bot_text",
        entity_id=item.id,
        now=utcnow(),
        metadata={"text_key": text_key},
    )
    items = await TextLibraryService(session).list_items(text_key)
    await callback.message.answer(
        "Вариант удалён.", reply_markup=text_items_keyboard(text_key, items)
    )
    await callback.answer()
