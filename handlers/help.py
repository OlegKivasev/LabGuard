from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Database
from .keyboards import main_menu_keyboard

router = Router(name="help")


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database) -> None:
    if message.from_user is not None:
        db.touch_last_active(message.from_user.id)
        db.log_event(message.from_user.id, "help")

    await message.answer(
        "Как подключиться:\n"
        "1) Нажми кнопку «Получить VPN»\n"
        "2) Подтверди выдачу подписки\n"
        "3) Открой «Приложения» и установи клиент\n"
        "4) Импортируй ссылку подписки и подключись",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("apps"))
async def cmd_apps(message: Message, db: Database) -> None:
    if message.from_user is not None:
        db.touch_last_active(message.from_user.id)
        db.log_event(message.from_user.id, "apps")

    await message.answer(
        "Рекомендуемые приложения:\n"
        "- iOS: Hiddify / Streisand\n"
        "- Android: Hiddify / v2rayNG\n"
        "- Windows: Hiddify / Nekoray\n"
        "- macOS: Hiddify",
        reply_markup=main_menu_keyboard(),
    )
