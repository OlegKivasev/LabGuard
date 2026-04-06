from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import Settings
from database import Database

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return

    db.create_user_if_not_exists(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "start")

    await message.answer(
        "Привет! Я выдаю бесплатный VPN на 14 дней.\n"
        "Команды:\n"
        "/get - получить VPN\n"
        "/status - мой статус\n"
        "/help - инструкция",
    )

    _ = settings
