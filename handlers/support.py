from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from config import Settings
from database import Database

router = Router(name="support")


@router.message(Command("support"))
async def cmd_support(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
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

    db.log_event(message.from_user.id, "support")

    text = (command.args or "").strip()
    if text:
        ticket_id = db.create_ticket(message.from_user.id, text)
        await message.answer(
            f"Обращение принято: #{ticket_id}. Ответим в течение 24 часов."
        )
        return

    if settings.support_bot_username:
        await message.answer(
            "Напиши в поддержку: "
            f"@{settings.support_bot_username}\n"
            "Или отправь сообщение сразу сюда командой:\n"
            "/support Твой текст"
        )
        return

    await message.answer(
        "Опиши проблему командой:\n"
        "/support Твой текст"
    )
