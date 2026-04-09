from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import Database

router = Router(name="support_bot")


def _is_admin(message: Message, settings: Settings) -> bool:
    if message.from_user is None:
        return False
    if message.from_user.id in settings.admin_telegram_ids:
        return True
    username = (message.from_user.username or "").strip().lower()
    return bool(username and username in settings.admin_telegram_usernames)


async def forward_user_message_to_admin(
    bot,
    db: Database,
    settings: Settings,
    telegram_id: int,
    username: str | None,
    text: str,
) -> int:
    admin_ids = sorted(settings.admin_telegram_ids)
    if not admin_ids:
        raise RuntimeError("No admin ids configured")

    ticket_id = db.create_ticket(telegram_id, text)
    username_text = f"@{username}" if username else "без username"
    sent = await bot.send_message(
        chat_id=admin_ids[0],
        text=(
            "Новый тикет поддержки.\n\n"
            f"Пользователь: {username_text}\n"
            f"Telegram ID: {telegram_id}\n"
            f"Сообщение: {text}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть", url=f"tg://user?id={telegram_id}")]]
        ),
    )
    db.link_support_admin_message(admin_ids[0], sent.message_id, telegram_id, ticket_id)
    return ticket_id


async def forward_admin_reply_to_user(
    bot,
    db: Database,
    admin_chat_id: int,
    admin_message_id: int,
    text: str,
) -> bool:
    link = db.get_support_link_by_admin_message(admin_chat_id, admin_message_id)
    if not link:
        return False
    await bot.send_message(chat_id=link["telegram_id"], text=text)
    return True


@router.message(CommandStart())
async def support_start(message: Message) -> None:
    await message.answer(
        "Добро пожаловать в поддержку LabGuard.\n\n"
        "Опиши здесь свой вопрос или проблему - оператор увидит сообщение и ответит, как только сможет.\n"
        "Все ответы придут прямо в этот чат."
    )


@router.message(F.reply_to_message, F.text)
async def support_admin_reply(message: Message, db: Database, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    if message.reply_to_message is None:
        return

    delivered = await forward_admin_reply_to_user(
        bot=message.bot,
        db=db,
        admin_chat_id=message.chat.id,
        admin_message_id=message.reply_to_message.message_id,
        text=message.text or "",
    )
    if not delivered:
        await message.answer("Не удалось определить адресата. Ответь реплаем на сообщение тикета.")


@router.message(F.text)
async def support_user_message(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if _is_admin(message, settings):
        await message.answer("Чтобы ответить пользователю, используй reply на сообщение тикета.")
        return

    ticket_id = await forward_user_message_to_admin(
        bot=message.bot,
        db=db,
        settings=settings,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        text=message.text or "",
    )
    await message.answer(f"Сообщение отправлено в поддержку. Номер обращения: #{ticket_id}.")
