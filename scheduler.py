from datetime import datetime, timezone
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database


def _parse_sqlite_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


async def send_expiry_notifications(bot, db: Database) -> None:
    now = datetime.now(timezone.utc)

    for user in db.list_users_for_3d_notification():
        expires_at = _parse_sqlite_dt(str(user["expires_at"]))
        remaining_days = (expires_at - now).total_seconds() / 86400
        if 2 < remaining_days <= 3:
            await bot.send_message(
                int(user["telegram_id"]),
                "⏳ Напоминаем: твой VPN истекает через 3 дня. /status",
            )
            db.mark_notified_3d(int(user["telegram_id"]))

    for user in db.list_users_for_1d_notification():
        expires_at = _parse_sqlite_dt(str(user["expires_at"]))
        remaining_days = (expires_at - now).total_seconds() / 86400
        if 0 < remaining_days <= 1:
            await bot.send_message(
                int(user["telegram_id"]),
                "⚠️ Завтра заканчивается твой бесплатный VPN. /status",
            )
            db.mark_notified_1d(int(user["telegram_id"]))

    logging.info("Expiry notification check finished")


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    return scheduler
