from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import Settings
from database import Database
from marzban import MarzbanClient

from .get_vpn import cmd_get
from .help import cmd_apps, cmd_help
from .keyboards import (
    CB_APPS,
    CB_BACK,
    CB_GET_CONFIRM,
    CB_GET_INFO,
    CB_HELP,
    CB_STATUS,
    CB_SUPPORT,
    CB_SUPPORT_CANCEL,
    subscription_confirm_keyboard,
    support_wait_keyboard,
)
from .menu_context import main_menu_for_user
from .status import cmd_status

router = Router(name="menu")


class SupportDialog(StatesGroup):
    waiting_text = State()


@router.message(Command("menu"))
async def cmd_menu(message: Message, db: Database) -> None:
    if message.from_user is None:
        return

    existing = db.get_user_by_telegram_id(message.from_user.id)
    if existing is None and not db.has_received_trial(message.from_user.id):
        db.create_user_if_not_exists(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
    elif existing is not None:
        db.touch_last_active(message.from_user.id)

    db.log_event(message.from_user.id, "menu")
    await message.answer("Главное меню 👇", reply_markup=main_menu_for_user(existing))


@router.callback_query(F.data == CB_BACK)
async def cb_back(callback: CallbackQuery, db: Database) -> None:
    user = None
    if callback.from_user:
        db.touch_last_active(callback.from_user.id)
        db.log_event(callback.from_user.id, "menu_back")
        user = db.get_user_by_telegram_id(callback.from_user.id)

    if callback.message:
        await callback.message.answer("Главное меню 👇", reply_markup=main_menu_for_user(user))
    await callback.answer()


@router.callback_query(F.data == CB_GET_INFO)
async def cb_get_info(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if callback.from_user:
        db.touch_last_active(callback.from_user.id)
        db.log_event(callback.from_user.id, "get_info")

    if callback.message:
        await callback.message.answer(
            "Ты получишь бесплатную подписку на VPN.\n"
            "Что внутри:\n"
            "- один сервер\n"
            f"- срок: {settings.free_trial_days} дней\n"
            "- формат: подписка для удобного импорта в приложение\n\n"
            "Нажми кнопку ниже, чтобы активировать подписку.",
            reply_markup=subscription_confirm_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == CB_GET_CONFIRM)
async def cb_get_confirm(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> None:
    if callback.message:
        await cmd_get(callback.message, db, settings, marzban)
    await callback.answer()


@router.callback_query(F.data == CB_STATUS)
async def cb_status(callback: CallbackQuery, db: Database) -> None:
    if callback.message:
        await cmd_status(callback.message, db)
    await callback.answer()


@router.callback_query(F.data == CB_HELP)
async def cb_help(callback: CallbackQuery, db: Database) -> None:
    if callback.message:
        await cmd_help(callback.message, db)
    await callback.answer()


@router.callback_query(F.data == CB_APPS)
async def cb_apps(callback: CallbackQuery, db: Database) -> None:
    if callback.message:
        await cmd_apps(callback.message, db)
    await callback.answer()


@router.callback_query(F.data == CB_SUPPORT)
async def cb_support(callback: CallbackQuery, state: FSMContext, settings: Settings, db: Database) -> None:
    if callback.from_user:
        db.touch_last_active(callback.from_user.id)
        db.log_event(callback.from_user.id, "support")

    if not callback.message:
        await callback.answer()
        return

    if settings.support_bot_username:
        user = db.get_user_by_telegram_id(callback.from_user.id) if callback.from_user else None
        await callback.message.answer(
            "Напиши в поддержку: "
            f"@{settings.support_bot_username}\n"
            "Если удобно, можно отправить вопрос прямо сюда через команду /support.",
            reply_markup=main_menu_for_user(user),
        )
        await callback.answer()
        return

    await state.set_state(SupportDialog.waiting_text)
    await callback.message.answer(
        "Опиши проблему одним сообщением, и я создам обращение в поддержку.",
        reply_markup=support_wait_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == CB_SUPPORT_CANCEL)
async def cb_support_cancel(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = None
    if callback.from_user:
        db.touch_last_active(callback.from_user.id)
        db.log_event(callback.from_user.id, "support_cancel")
        user = db.get_user_by_telegram_id(callback.from_user.id)
    if callback.message:
        await callback.message.answer("Диалог с поддержкой отменен.", reply_markup=main_menu_for_user(user))
    await callback.answer()


@router.message(SupportDialog.waiting_text, F.text)
async def support_waiting_text(message: Message, state: FSMContext, db: Database) -> None:
    if message.from_user is None:
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Пожалуйста, отправь текст обращения одним сообщением.")
        return

    ticket_id = db.create_ticket(message.from_user.id, text)
    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "support_ticket")
    await state.clear()

    await message.answer(
        f"Обращение принято: #{ticket_id}. Ответим в течение 24 часов.",
        reply_markup=main_menu_for_user(db.get_user_by_telegram_id(message.from_user.id)),
    )


@router.message(F.text)
async def auto_menu_on_text(message: Message, db: Database) -> None:
    if message.from_user is None:
        return

    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    existing = db.get_user_by_telegram_id(message.from_user.id)
    if existing is None and not db.has_received_trial(message.from_user.id):
        db.create_user_if_not_exists(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
    elif existing is not None:
        db.touch_last_active(message.from_user.id)

    db.log_event(message.from_user.id, "menu_auto")
    await message.answer("С возвращением! Вот меню 👇", reply_markup=main_menu_for_user(existing))
