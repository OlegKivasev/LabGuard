import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from config import Settings
from database import Database
from marzban import MarzbanClient

router = Router(name="admin")
logger = logging.getLogger(__name__)


def _is_admin(message: Message, settings: Settings) -> bool:
    if not message.from_user:
        return False

    by_id = message.from_user.id in settings.admin_telegram_ids
    username = (message.from_user.username or "").lower()
    by_username = bool(username and username in settings.admin_telegram_usernames)
    return by_id or by_username


@router.message(Command("admin_users"))
async def cmd_admin_users(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    if not _is_admin(message, settings):
        await message.answer("Нет доступа к admin-командам.")
        return

    raw_limit = (command.args or "").strip()
    limit = 20
    if raw_limit.isdigit():
        limit = max(1, min(100, int(raw_limit)))

    users = db.list_recent_users(limit=limit)
    if not users:
        await message.answer("Пользователей пока нет.")
        return

    lines = ["👥 Последние пользователи:"]
    for user in users:
        lines.append(
            f"- id={user['telegram_id']} | tg={user['username'] or '-'} | "
            f"marzban={user['marzban_id'] or '-'} | exp={user['expires_at'] or '-'}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("admin_deactivate"))
async def cmd_admin_deactivate(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("Нет доступа к admin-командам.")
        return

    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Использование: /admin_deactivate <telegram_id>")
        return

    telegram_id = int(args)
    user = db.get_user_by_telegram_id(telegram_id)
    if user is None:
        await message.answer("Пользователь не найден в локальной базе.")
        return

    marzban_id = str(user.get("marzban_id") or "").strip()
    if marzban_id:
        try:
            await marzban.disable_user(marzban_id)
        except Exception as exc:
            logger.exception("Failed to disable Marzban user %s: %s", marzban_id, exc)
            await message.answer("Не удалось деактивировать пользователя в Marzban.")
            return

    db.clear_trial(telegram_id)
    db.log_event(telegram_id, "admin_deactivate")
    await message.answer(f"Триал деактивирован для telegram_id={telegram_id}.")


@router.message(Command("admin_delete"))
async def cmd_admin_delete(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("Нет доступа к admin-командам.")
        return

    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Использование: /admin_delete <telegram_id>")
        return

    telegram_id = int(args)
    user = db.get_user_by_telegram_id(telegram_id)
    if user is None:
        await message.answer("Пользователь не найден в локальной базе.")
        return

    marzban_id = str(user.get("marzban_id") or "").strip()
    if marzban_id:
        try:
            await marzban.delete_user(marzban_id)
        except Exception as exc:
            logger.exception("Failed to delete Marzban user %s: %s", marzban_id, exc)
            await message.answer("Не удалось удалить пользователя в Marzban.")
            return

    deleted = db.delete_user(telegram_id)
    if deleted:
        db.log_event(telegram_id, "admin_delete")
    await message.answer(f"Пользователь telegram_id={telegram_id} удален.")
