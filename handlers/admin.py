import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config import Settings
from database import Database
from miniapp_auth import sign_admin_token
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


def _candidate_marzban_usernames(user: dict, telegram_id: int) -> list[str]:
    candidates: list[str] = []
    for value in (user.get("marzban_id"), user.get("username"), f"tg_{telegram_id}"):
        name = str(value or "").strip()
        if name and name not in candidates:
            candidates.append(name)
    return candidates


@router.message(Command("admin_app"))
async def cmd_admin_app(message: Message, settings: Settings) -> None:
    if not _is_admin(message, settings):
        await message.answer("Нет доступа к admin-командам.")
        return

    if not settings.web_app_base_url:
        await message.answer("WEB_APP_BASE_URL не настроен в .env")
        return

    token = sign_admin_token(
        secret=settings.bot_token,
        admin_id=message.from_user.id,
        ttl_minutes=settings.web_app_token_ttl_minutes,
    )
    url = f"{settings.web_app_base_url.rstrip('/')}/admin-app?token={token}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть админ-приложение", web_app=WebAppInfo(url=url))]
        ]
    )
    await message.answer("Открой админ-приложение внутри Telegram:", reply_markup=keyboard)


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
    disabled = False
    for candidate in _candidate_marzban_usernames(user, telegram_id):
        try:
            if await marzban.disable_user(candidate):
                disabled = True
                break
        except Exception as exc:
            logger.exception("Failed to disable Marzban user %s: %s", candidate, exc)
            await message.answer("Не удалось деактивировать пользователя в Marzban.")
            return

    db.clear_trial(telegram_id)
    db.mark_trial_used(telegram_id)
    db.log_event(telegram_id, "admin_deactivate")
    if disabled:
        await message.answer(f"Триал деактивирован для telegram_id={telegram_id}.")
    else:
        await message.answer(
            f"Локальный триал сброшен для telegram_id={telegram_id}, "
            "но пользователь в Marzban не найден."
        )


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

    deleted_in_marzban = False
    for candidate in _candidate_marzban_usernames(user, telegram_id):
        try:
            if await marzban.delete_user(candidate):
                deleted_in_marzban = True
                break
        except Exception as exc:
            logger.exception("Failed to delete Marzban user %s: %s", candidate, exc)
            await message.answer("Не удалось удалить пользователя в Marzban.")
            return

    db.clear_trial_lock(telegram_id)
    deleted = db.delete_user(telegram_id)
    if deleted:
        db.log_event(telegram_id, "admin_delete")
    if deleted_in_marzban:
        await message.answer(f"Пользователь telegram_id={telegram_id} удален.")
    else:
        await message.answer(
            f"Локальный пользователь telegram_id={telegram_id} удален, "
            "но в Marzban не найден."
        )
