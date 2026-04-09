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
    forum_chat_id = int(getattr(settings, "support_forum_chat_id", 0) or 0)
    if not forum_chat_id:
        raise RuntimeError("Support forum chat is not configured")

    ticket_id = db.create_ticket(telegram_id, text)
    username_text = f"@{username}" if username else "без username"
    topic = db.get_support_topic_by_telegram_id(telegram_id)
    if topic is None:
        title = f"{username_text} [{telegram_id}]"
        created_topic = await bot.create_forum_topic(chat_id=forum_chat_id, name=title[:128])
        message_thread_id = int(created_topic.message_thread_id)
        db.set_support_topic(
            telegram_id=telegram_id,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            ticket_id=ticket_id,
        )
    else:
        message_thread_id = int(topic["message_thread_id"])

    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        text=(
            f"Пользователь: {username_text}\n"
            f"Telegram ID: {telegram_id}\n\n"
            f"{text}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть профиль", url=f"tg://user?id={telegram_id}")]]
        ),
    )
    return ticket_id


async def forward_admin_reply_to_user(
    bot,
    db: Database,
    forum_chat_id: int,
    message_thread_id: int,
    text: str,
) -> bool:
    topic = db.get_support_topic_by_thread(forum_chat_id, message_thread_id)
    if not topic:
        return False
    await bot.send_message(chat_id=topic["telegram_id"], text=text)
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
    forum_chat_id = int(getattr(settings, "support_forum_chat_id", 0) or 0)
    if message.chat.id != forum_chat_id:
        return
    thread_id = int(message.message_thread_id or 0)
    if not thread_id:
        await message.answer("Ответь внутри темы пользователя, чтобы бот понял адресата.")
        return

    delivered = await forward_admin_reply_to_user(
        bot=message.bot,
        db=db,
        forum_chat_id=message.chat.id,
        message_thread_id=thread_id,
        text=message.text or "",
    )
    if not delivered:
        await message.answer("Не удалось определить адресата темы.")


@router.message(F.text)
async def support_user_message(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if _is_admin(message, settings):
        await message.answer("Чтобы ответить пользователю, используй reply на сообщение тикета.")
        return

    try:
        ticket_id = await forward_user_message_to_admin(
            bot=message.bot,
            db=db,
            settings=settings,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            text=message.text or "",
        )
    except RuntimeError:
        await message.answer(
            "Поддержка сейчас недоступна. Проверь настройку форума поддержки для support-бота."
        )
        return

    await message.answer(f"Сообщение отправлено в поддержку. Номер обращения: #{ticket_id}.")
