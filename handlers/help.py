from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Database

router = Router(name="help")


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database) -> None:
    if message.from_user is not None:
        db.touch_last_active(message.from_user.id)
        db.log_event(message.from_user.id, "help")

    await message.answer(
        "Как подключиться:\n"
        "1) Нажми /get\n"
        "2) Получи конфиг (после шага интеграции API)\n"
        "3) Установи клиент: /apps\n"
        "4) Импортируй конфиг и подключись"
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
        "- macOS: Hiddify"
    )
