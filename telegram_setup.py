from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from config import Settings


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть бота и меню"),
    BotCommand(command="menu", description="Показать главное меню"),
    BotCommand(command="support", description="Написать в поддержку"),
]


async def setup_bot(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(BOT_COMMANDS)

    if settings.web_app_base_url:
        web_url = f"{settings.web_app_base_url.rstrip('/')}/admin-app"
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=web_url))
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
