import asyncio
import argparse
import logging
import sys

from aiogram import Bot, Dispatcher

from config import load_settings
from database import Database
from handlers import register_routers
from scheduler import build_scheduler, send_expiry_notifications
from telegram_setup import setup_bot


def check_config() -> int:
    settings = load_settings()
    missing = settings.missing_for_bot_start()

    if missing:
        print("Config check failed. Missing:", ", ".join(missing))
        return 1

    print("Config check passed.")
    return 0


async def check_telegram_connection() -> int:
    settings = load_settings()
    missing = settings.missing_for_bot_start()

    if missing:
        print("Config check failed. Missing:", ", ".join(missing))
        return 1

    bot = Bot(token=settings.bot_token)
    try:
        me = await bot.get_me()
        print(f"Telegram check passed. Bot: @{me.username} (id={me.id})")
        return 0
    except Exception as exc:
        print(f"Telegram check failed: {exc}")
        return 1
    finally:
        await bot.session.close()


async def main() -> None:
    settings = load_settings()

    missing = settings.missing_for_bot_start()
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")

    database = Database(settings.database_path)
    database.init_schema()

    bot = Bot(token=settings.bot_token)
    await setup_bot(bot)

    dp = Dispatcher()
    dp["db"] = database
    dp["settings"] = settings
    register_routers(dp)

    scheduler = build_scheduler()
    scheduler.add_job(
        send_expiry_notifications,
        trigger="interval",
        hours=6,
        kwargs={"bot": bot, "db": database},
    )
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPN Telegram bot")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate required settings and exit",
    )
    parser.add_argument(
        "--check-telegram",
        action="store_true",
        help="Validate Telegram token and connectivity",
    )
    args = parser.parse_args()

    if args.check_config:
        raise SystemExit(check_config())

    if args.check_telegram:
        raise SystemExit(asyncio.run(check_telegram_connection()))

    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)
