from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from database import Database

router = Router(name="start")


START_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/get"), KeyboardButton(text="/status")],
        [KeyboardButton(text="/help"), KeyboardButton(text="/apps")],
        [KeyboardButton(text="/support")],
    ],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
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
        reply_markup=START_KEYBOARD,
    )
