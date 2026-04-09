import sys
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock


def _install_fake_aiogram() -> None:
    aiogram_module = types.ModuleType("aiogram")
    filters_module = types.ModuleType("aiogram.filters")
    types_module = types.ModuleType("aiogram.types")
    exceptions_module = types.ModuleType("aiogram.exceptions")

    class DummyFilter:
        def __getattr__(self, _name):
            return self

    class DummyRouter:
        def __init__(self, *args, **kwargs):
            pass

        def message(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class CommandStart:
        def __init__(self, *args, **kwargs):
            pass

    class Message:
        pass

    class TelegramBadRequest(Exception):
        pass

    aiogram_module.F = DummyFilter()
    aiogram_module.Router = DummyRouter
    filters_module.CommandStart = CommandStart
    types_module.Message = Message
    exceptions_module.TelegramBadRequest = TelegramBadRequest

    sys.modules["aiogram"] = aiogram_module
    sys.modules["aiogram.filters"] = filters_module
    sys.modules["aiogram.types"] = types_module
    sys.modules["aiogram.exceptions"] = exceptions_module


def _install_fake_dotenv() -> None:
    dotenv_module = types.ModuleType("dotenv")

    def load_dotenv(*args, **kwargs):
        return False

    dotenv_module.load_dotenv = load_dotenv
    sys.modules["dotenv"] = dotenv_module


class SupportTopicRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recreates_topic_when_stored_thread_was_deleted(self) -> None:
        _install_fake_aiogram()
        _install_fake_dotenv()

        from aiogram.exceptions import TelegramBadRequest

        module_path = Path(__file__).resolve().parents[1] / "handlers" / "support_bot.py"
        spec = importlib.util.spec_from_file_location("support_bot_under_test", module_path)
        support_bot = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(support_bot)

        db = Mock()
        db.create_ticket.return_value = 42
        db.get_support_topic_by_telegram_id.return_value = {
            "forum_chat_id": -100555,
            "message_thread_id": 654,
            "telegram_id": 123456789,
        }

        bot = AsyncMock()
        bot.create_forum_topic.return_value = type("Topic", (), {"message_thread_id": 777})()
        bot.send_message.side_effect = [
            TelegramBadRequest("thread not found"),
            None,
            None,
        ]
        settings = type("S", (), {"support_forum_chat_id": -100555})()

        ticket_id = await support_bot.forward_user_message_to_admin(
            bot=bot,
            db=db,
            settings=settings,
            telegram_id=123456789,
            username="demo_user",
            text="Не работает VPN",
        )

        self.assertEqual(ticket_id, 42)
        bot.create_forum_topic.assert_awaited_once_with(
            chat_id=-100555,
            name="@demo_user [123456789]",
        )
        db.set_support_topic.assert_called_once_with(
            telegram_id=123456789,
            forum_chat_id=-100555,
            message_thread_id=777,
            ticket_id=42,
        )
        self.assertEqual(bot.send_message.await_count, 3)
        first_call = bot.send_message.await_args_list[0].kwargs
        second_call = bot.send_message.await_args_list[1].kwargs
        third_call = bot.send_message.await_args_list[2].kwargs
        self.assertEqual(first_call["text"], "Не работает VPN")
        self.assertEqual(second_call["text"], "Пользователь: @demo_user\nTelegram ID: 123456789")
        self.assertEqual(third_call["text"], "Не работает VPN")


if __name__ == "__main__":
    unittest.main()
