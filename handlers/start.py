from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import Settings
from database import Database
from .menu_context import main_menu_for_user

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return

    existing = db.get_user_by_telegram_id(message.from_user.id)
    has_received_trial = db.has_received_trial(message.from_user.id)
    if existing is None and not has_received_trial:
        db.create_user_if_not_exists(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
    elif existing is not None:
        db.touch_last_active(message.from_user.id)

    db.log_event(message.from_user.id, "start")

    if existing is None and not has_received_trial:
        await message.answer(
            "Привет! Мы не берем деньги за этот доступ и не собираем логи твоего интернет-трафика.\n"
            "Сейчас это бесплатный инструмент, чтобы понять, насколько VPN востребован и перегружен в реальных условиях.\n\n"
            "Начни с кнопки «Получить VPN».",
            reply_markup=main_menu_for_user(existing),
        )
    else:
        await message.answer("С возвращением! Проверь «Мой статус».")

    _ = settings
