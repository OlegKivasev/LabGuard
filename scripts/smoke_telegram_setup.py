import asyncio

from telegram_setup import BOT_COMMANDS, setup_bot


class FakeBot:
    def __init__(self) -> None:
        self.commands = []

    async def set_my_commands(self, commands) -> None:
        self.commands = commands


async def main() -> None:
    bot = FakeBot()
    await setup_bot(bot)
    print("setup_ok:", len(bot.commands) == len(BOT_COMMANDS))


if __name__ == "__main__":
    asyncio.run(main())
