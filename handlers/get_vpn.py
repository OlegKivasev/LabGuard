from datetime import datetime, timedelta, timezone
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from marzban import MarzbanClient
from .keyboards import main_menu_keyboard, post_subscription_keyboard

router = Router(name="get_vpn")
logger = logging.getLogger(__name__)


def _build_marzban_username(message: Message) -> str:
    if message.from_user and message.from_user.username:
        return message.from_user.username
    return f"tg_{message.from_user.id}"


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
            reply_markup=main_menu_keyboard(),
        )
        return

    db.create_user_if_not_exists(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )

    if not marzban.is_configured:
        await message.answer(
            "Marzban API пока не настроен. Заполни настройки API и попробуй снова.",
            reply_markup=main_menu_keyboard(),
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
                reply_markup=main_menu_keyboard(),
            )
            return
        await message.answer(
            "Ошибка Marzban API. Проверь настройки сервера и попробуй снова через кнопку меню.",
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:
        logger.exception("Failed to create Marzban user for telegram_id=%s: %s", message.from_user.id, exc)
        await message.answer(
            "Не удалось создать подписку. Попробуй позже или напиши в поддержку.",
            reply_markup=main_menu_keyboard(),
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

    if not config_text:
        await message.answer(
            "Подписка активирована, но ссылка пока недоступна. Напиши в поддержку.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if is_subscription:
        await message.answer(
            "Подписка активирована.\n"
            f"Срок действия: до {expires_at} UTC\n\n"
            "Ты получил подписку с одним сервером.\n"
            "Добавь ссылку в клиентское приложение:\n"
            f"{config_text}",
            reply_markup=post_subscription_keyboard(),
        )
        return

    await message.answer(
        "Подписка активирована, но сервер вернул только прямую ссылку.\n"
        f"Срок действия: до {expires_at} UTC\n\n"
        "Текущий доступ:\n"
        f"{config_text}",
        reply_markup=post_subscription_keyboard(),
    )
