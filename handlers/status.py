from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Database

router = Router(name="status")


def _parse_sqlite_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database) -> None:
    if message.from_user is None:
        return

    user = db.get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Тебя еще нет в системе. Нажми /start и затем /get")
        return

    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "status")

    expires_raw = user.get("expires_at")
    if not expires_raw:
        await message.answer("VPN еще не активирован. Нажми /get")
        return

    expires_at = _parse_sqlite_dt(str(expires_raw))
    now = datetime.now(timezone.utc)
    remaining_days = max(0, (expires_at - now).days)
    is_active = expires_at > now
    status_mark = "✅ активен" if is_active else "❌ истек"

    await message.answer(
        "📊 Твой статус:\n"
        f"{status_mark}\n"
        f"📅 Осталось: {remaining_days} дней\n"
        f"⏳ До: {expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        "📡 Трафик: будет доступен после подключения API"
    )
