from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database

router = Router(name="get_vpn")


@router.message(Command("get"))
async def cmd_get(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return

    db.create_user_if_not_exists(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    expires_at = db.ensure_trial(
        telegram_id=message.from_user.id,
        days=settings.free_trial_days,
    )
    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "get")

    await message.answer(
        "Триал активирован.\n"
        f"Срок действия: до {expires_at} UTC\n\n"
        "На этом этапе API Marzban еще не подключен, поэтому конфиг будет выдан на следующем шаге интеграции API."
    )
