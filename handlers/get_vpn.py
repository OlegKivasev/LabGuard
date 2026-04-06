from datetime import datetime, timedelta, timezone
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from marzban import MarzbanClient

router = Router(name="get_vpn")
logger = logging.getLogger(__name__)


def _build_marzban_username(message: Message) -> str:
    if message.from_user and message.from_user.username:
        return message.from_user.username
    return f"tg_{message.from_user.id}"


@router.message(Command("get"))
async def cmd_get(
    message: Message,
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> None:
    if message.from_user is None:
        return

    db.create_user_if_not_exists(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    if not marzban.is_configured:
        await message.answer(
            "Marzban API пока не настроен. Заполни настройки API и попробуй снова."
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
                "Включи VLESS inbound в Marzban и попробуй снова."
            )
            return
        await message.answer("Ошибка Marzban API. Проверь настройки сервера и повтори /get")
        return
    except Exception as exc:
        logger.exception("Failed to create Marzban user for telegram_id=%s: %s", message.from_user.id, exc)
        await message.answer("Не удалось создать VPN-конфиг. Попробуй позже или напиши /support")
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
    db.touch_last_active(message.from_user.id)
    db.log_event(message.from_user.id, "get")

    links = marzban_user.get("links") or []
    config_text = ""
    for link in links:
        link_text = str(link).strip()
        if link_text.lower().startswith("vless://"):
            config_text = link_text
            break

    if not config_text:
        await message.answer(
            "Триал активирован, но VLESS-ссылка недоступна. Проверь VLESS inbound в Marzban и попробуй снова."
        )
        return

    await message.answer(
        "Триал активирован.\n"
        f"Срок действия: до {expires_at} UTC\n\n"
        "🔗 Твоя VLESS ссылка:\n"
        f"{config_text}"
    )
