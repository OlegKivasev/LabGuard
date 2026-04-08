import asyncio
import argparse
import logging
import sys

from aiogram import Bot, Dispatcher

from config import load_settings
from database import Database
from handlers import register_routers
from marzban import MarzbanClient
from scheduler import build_scheduler, send_expiry_notifications
from telegram_setup import setup_bot
from webapp import start_web_app_server


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


async def check_marzban_connection() -> int:
    settings = load_settings()
    missing = settings.missing_for_marzban()

    if missing:
        print("Marzban check failed. Missing:", ", ".join(missing))
        return 1

    client = MarzbanClient(
        base_url=settings.marzban_base_url,
        api_key=settings.marzban_api_key,
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_tls=settings.marzban_verify_tls,
    )

    try:
        ok = await client.healthcheck()
        if ok:
            print("Marzban check passed.")
            return 0

        print("Marzban check failed: unauthorized or endpoint unavailable.")
        return 1
    except Exception as exc:
        print(f"Marzban check failed: {exc}")
        return 1


async def main() -> None:
    settings = load_settings()

    missing = settings.missing_for_bot_start()
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")

    database = Database(settings.database_path)
    database.init_schema()

    bot = Bot(token=settings.bot_token)
    await setup_bot(bot, settings)

    dp = Dispatcher()
    dp["db"] = database
    dp["settings"] = settings
    marzban_client = MarzbanClient(
        base_url=settings.marzban_base_url,
        api_key=settings.marzban_api_key,
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_tls=settings.marzban_verify_tls,
    )
    dp["marzban"] = marzban_client
    register_routers(dp)

    scheduler = build_scheduler()
    scheduler.add_job(
        send_expiry_notifications,
        trigger="interval",
        hours=6,
        kwargs={"bot": bot, "db": database},
    )
    scheduler.start()

    web_server = None
    web_task = None
    if settings.web_app_base_url:
        web_server, web_task = await start_web_app_server(database, settings, marzban_client, bot=bot)

    try:
        await dp.start_polling(bot)
    finally:
        if web_server is not None and web_task is not None:
            web_server.should_exit = True
            await web_task
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
    parser.add_argument(
        "--check-marzban",
        action="store_true",
        help="Validate Marzban API settings and connectivity",
    )
    args = parser.parse_args()

    if args.check_config:
        raise SystemExit(check_config())

    if args.check_telegram:
        raise SystemExit(asyncio.run(check_telegram_connection()))

    if args.check_marzban:
        raise SystemExit(asyncio.run(check_marzban_connection()))

    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)
