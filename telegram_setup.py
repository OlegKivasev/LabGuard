from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands

from config import Settings


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть бота"),
    BotCommand(command="support", description="Написать в поддержку"),
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

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    _ = settings
