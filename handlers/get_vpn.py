from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from marzban import MarzbanClient

router = Router(name="get_vpn")


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
    marzban_username = f"tg_{message.from_user.id}"

    try:
        marzban_user = await marzban.create_user(
            username=marzban_username,
            expire_at=expiry_dt,
        )
    except Exception:
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
    subscription_url = str(marzban_user.get("subscription_url", "")).strip()
    config_text = str(links[0]).strip() if links else ""

    if not config_text:
        await message.answer(
            "Триал активирован, но ссылка конфига пока недоступна. Напиши /support"
        )
        return

    await message.answer(
        "Триал активирован.\n"
        f"Срок действия: до {expires_at} UTC\n\n"
        "🔗 Твой VLESS конфиг:\n"
        f"{config_text}\n\n"
        f"📦 Подписка: {subscription_url if subscription_url else 'недоступно'}"
    )
