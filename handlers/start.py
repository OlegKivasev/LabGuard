from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from config import Settings
from database import Database
from miniapp_auth import sign_admin_token

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
        reply_markup=START_KEYBOARD,
    )

    is_admin = (
        message.from_user.id in settings.admin_telegram_ids
        or ((message.from_user.username or "").lower() in settings.admin_telegram_usernames)
    )
    if is_admin and settings.web_app_base_url:
        token = sign_admin_token(
            secret=settings.bot_token,
            admin_id=message.from_user.id,
            ttl_minutes=settings.web_app_token_ttl_minutes,
        )
        url = f"{settings.web_app_base_url.rstrip('/')}/admin-app?token={token}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Открыть админ-приложение", web_app=WebAppInfo(url=url))]
            ]
        )
        await message.answer("Панель администратора:", reply_markup=keyboard)
