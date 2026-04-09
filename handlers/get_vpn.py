from datetime import datetime, timedelta, timezone
import logging
import re
from urllib.parse import urlparse

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from marzban import MarzbanClient
from .keyboards import post_subscription_keyboard
from .menu_context import main_menu_for_user

router = Router(name="get_vpn")
logger = logging.getLogger(__name__)


def _build_marzban_username(message: Message) -> str:
    if message.from_user and message.from_user.username:
        base = message.from_user.username.lower()
    else:
        base = f"tg_{message.from_user.id}"

    safe = re.sub(r"[^a-z0-9_]", "_", base)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = f"tg_{message.from_user.id}"

    marzban_username = f"labguard_{safe}"
    return marzban_username[:48].rstrip("_")


def _parse_sqlite_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _extract_subscription_text(marzban_user: dict) -> tuple[str, bool]:
    for key in ("subscription_url", "subscription_link", "sub_url", "subscription"):
        value = str(marzban_user.get(key, "")).strip()
        if value:
            return value, True

    for key in ("subscription_urls", "subscriptions"):
        values = marzban_user.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text:
                    return text, True

    links = marzban_user.get("links") or []
    for link in links:
        link_text = str(link).strip()
        if link_text.lower().startswith("vless://"):
            return link_text, False

    return "", False


def _normalize_subscription_url(raw_url: str, base_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return url

    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url

    base = base_url.strip().rstrip("/")
    if not base:
        return url

    return f"{base}/{url.lstrip('/')}"


async def _notify_admin_about_vpn_issued(
    bot,
    settings: Settings,
    telegram_id: int,
    username: str | None,
) -> None:
    admin_ids = sorted(settings.admin_telegram_ids)
    if not admin_ids or bot is None:
        return

    username_text = f"@{username}" if username else "без username"
    text = (
        "Новый пользователь получил VPN-ссылку.\n\n"
        f"Пользователь: {username_text}\n"
        f"Telegram ID: {telegram_id}\n"
        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    await bot.send_message(chat_id=admin_ids[0], text=text)


@router.message(Command("get"))
async def cmd_get(
    message: Message,
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> None:
    if message.from_user is None:
        return

    existing = db.get_user_by_telegram_id(message.from_user.id)
    if existing and existing.get("expires_at"):
        try:
            expires_at = _parse_sqlite_dt(str(existing["expires_at"]))
            now = datetime.now(timezone.utc)
            if expires_at > now:
                remaining_days = max(0, (expires_at - now).days)
                db.mark_trial_used(message.from_user.id)
                db.touch_last_active(message.from_user.id)
                db.log_event(message.from_user.id, "get_existing")
                await message.answer(
                    "Твой триал уже активирован.\n"
                    f"📅 Осталось: {remaining_days} дней\n"
                    f"⏳ До: {expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                    "Открой «Мой статус» в меню ниже.",
                    reply_markup=post_subscription_keyboard(),
                )
                return
        except Exception:
            logger.exception("Failed to parse local expires_at for telegram_id=%s", message.from_user.id)

    if db.has_received_trial(message.from_user.id):
        db.touch_last_active(message.from_user.id)
        db.log_event(message.from_user.id, "get_denied_finished")
        await message.answer(
            "Пробный период уже был использован и повторно не выдается.\n"
            "Ниже меню, проверь статус или напиши в поддержку.",
            reply_markup=main_menu_for_user(existing),
        )
        return

    db.create_user_if_not_exists(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    if existing is None:
        existing = db.get_user_by_telegram_id(message.from_user.id)

    if not marzban.is_configured:
        await message.answer(
            "Marzban API пока не настроен. Заполни настройки API и попробуй снова.",
            reply_markup=main_menu_for_user(existing),
        )
        return

    expiry_dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=settings.free_trial_days)
    marzban_username = _build_marzban_username(message)

    try:
        marzban_user = await marzban.create_user(
            username=marzban_username,
            expire_at=expiry_dt,
        )
    except RuntimeError as exc:
        reason = str(exc)
        logger.exception("Marzban runtime error for telegram_id=%s: %s", message.from_user.id, reason)
        if "No enabled VLESS inbounds" in reason:
            await message.answer(
                "На сервере не найден активный VLESS inbound. "
                "Включи VLESS inbound в Marzban и попробуй снова.",
                reply_markup=main_menu_for_user(existing),
            )
            return
        await message.answer(
            "Ошибка Marzban API. Проверь настройки сервера и попробуй снова через кнопку меню.",
            reply_markup=main_menu_for_user(existing),
        )
        return
    except Exception as exc:
        logger.exception("Failed to create Marzban user for telegram_id=%s: %s", message.from_user.id, exc)
        await message.answer(
            "Не удалось создать подписку. Попробуй позже или напиши в поддержку.",
            reply_markup=main_menu_for_user(existing),
        )
        return

    expires_at = datetime.fromtimestamp(
        int(marzban_user.get("expire", int(expiry_dt.timestamp()))),
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M:%S")

    db.set_marzban_binding(
        telegram_id=message.from_user.id,
        marzban_id=str(marzban_user.get("username", marzban_username)),
        expires_at=expires_at,
    )
    db.mark_trial_used(message.from_user.id)
    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "get")

    config_text, is_subscription = _extract_subscription_text(marzban_user)
    if is_subscription:
        config_text = _normalize_subscription_url(config_text, marzban.base_url)

    if not config_text:
        await message.answer(
            "Подписка активирована, но ссылка пока недоступна. Напиши в поддержку.",
            reply_markup=main_menu_for_user(existing),
        )
        return

    if is_subscription:
        try:
            await _notify_admin_about_vpn_issued(
                bot=message.bot,
                settings=settings,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
            )
        except Exception:
            logger.exception("Failed to notify admin about vpn issue for telegram_id=%s", message.from_user.id)
        await message.answer(
            "Подписка активирована.\n"
            f"Срок действия: до {expires_at} UTC\n\n"
            "Ты получил подписку с одним сервером.\n"
            "Добавь ссылку в клиентское приложение:\n"
            f"{config_text}",
            reply_markup=post_subscription_keyboard(),
        )
        return

    try:
        await _notify_admin_about_vpn_issued(
            bot=message.bot,
            settings=settings,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
    except Exception:
        logger.exception("Failed to notify admin about vpn issue for telegram_id=%s", message.from_user.id)
    await message.answer(
        "Подписка активирована, но сервер вернул только прямую ссылку.\n"
        f"Срок действия: до {expires_at} UTC\n\n"
        "Текущий доступ:\n"
        f"{config_text}",
        reply_markup=post_subscription_keyboard(),
    )
