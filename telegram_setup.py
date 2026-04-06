from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from config import Settings


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть бота"),
    BotCommand(command="support", description="Написать в поддержку"),
]

ADMIN_BOT_COMMANDS = [
    *BOT_COMMANDS,
    BotCommand(command="admin_app", description="Открыть админ мини-приложение"),
]

BOT_SHORT_DESCRIPTION = (
    "Бесплатный VPN-бот: тестовая подписка и быстрый старт в пару кликов."
)

BOT_DESCRIPTION = (
    "Этот бот выдает бесплатную VPN-подписку на ограниченный срок.\n"
    "Сделан как тестовый инструмент, чтобы оценить актуальность VPN и нагрузку на сервер.\n"
    "Без оплаты и без сбора логов интернет-трафика пользователя."
)


async def setup_bot(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    await bot.set_my_description(description=BOT_DESCRIPTION)

    await bot.set_my_short_description(
        short_description=BOT_SHORT_DESCRIPTION,
        language_code="ru",
    )
    await bot.set_my_description(
        description=BOT_DESCRIPTION,
        language_code="ru",
    )

    if settings.web_app_base_url:
        app_url = f"{settings.web_app_base_url.rstrip('/')}/app"
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=app_url))
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    for admin_id in settings.admin_telegram_ids:
        await bot.set_my_commands(
            ADMIN_BOT_COMMANDS,
            scope=BotCommandScopeChat(chat_id=admin_id),
        )
