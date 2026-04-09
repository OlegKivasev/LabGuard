from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import Settings
from database import Database

router = Router(name="support_bot")


async def _create_support_topic(bot, db: Database, forum_chat_id: int, telegram_id: int, username_text: str, ticket_id: int) -> int:
    title = f"{username_text} [{telegram_id}]"
    created_topic = await bot.create_forum_topic(chat_id=forum_chat_id, name=title[:128])
    message_thread_id = int(created_topic.message_thread_id)
    db.set_support_topic(
        telegram_id=telegram_id,
        forum_chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        ticket_id=ticket_id,
    )
    return message_thread_id


async def _send_support_topic_header(
    bot,
    forum_chat_id: int,
    message_thread_id: int,
    username_text: str,
    telegram_id: int,
) -> None:
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        text=f"Пользователь: {username_text}\nTelegram ID: {telegram_id}",
    )


async def _send_support_user_text(
    bot,
    forum_chat_id: int,
    message_thread_id: int,
    text: str,
) -> None:
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        text=text,
    )


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
    is_new_topic = topic is None
    if topic is None:
        message_thread_id = await _create_support_topic(
            bot=bot,
            db=db,
            forum_chat_id=forum_chat_id,
            telegram_id=telegram_id,
            username_text=username_text,
            ticket_id=ticket_id,
        )
    else:
        message_thread_id = int(topic["message_thread_id"])

    try:
        if is_new_topic:
            await _send_support_topic_header(
                bot=bot,
                forum_chat_id=forum_chat_id,
                message_thread_id=message_thread_id,
                username_text=username_text,
                telegram_id=telegram_id,
            )
        await _send_support_user_text(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            text=text,
        )
    except TelegramBadRequest:
        if topic is None:
            raise
        message_thread_id = await _create_support_topic(
            bot=bot,
            db=db,
            forum_chat_id=forum_chat_id,
            telegram_id=telegram_id,
            username_text=username_text,
            ticket_id=ticket_id,
        )
        await _send_support_topic_header(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            username_text=username_text,
            telegram_id=telegram_id,
        )
        await _send_support_user_text(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            text=text,
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
        await forward_user_message_to_admin(
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

    await message.answer("Ваше сообщение отправлено. Оператор ответит вам в ближайшее время.")
