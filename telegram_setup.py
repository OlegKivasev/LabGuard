from aiogram import Bot
from aiogram.types import BotCommand


BOT_COMMANDS = [
    BotCommand(command="start", description="Запуск бота"),
    BotCommand(command="get", description="Получить VPN (локальный триал)"),
    BotCommand(command="status", description="Проверить статус"),
    BotCommand(command="help", description="Инструкция"),
    BotCommand(command="apps", description="Приложения"),
    BotCommand(command="support", description="Поддержка"),
]


async def setup_bot(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
