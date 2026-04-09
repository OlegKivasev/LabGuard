import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from database import Database


class SupportConfigAndSchemaTests(unittest.TestCase):
    def test_database_support_mapping_roundtrip(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Database(str(Path(tmpdir.name) / "test.sqlite3"))
            db.init_schema()

            db.link_support_admin_message(
                admin_chat_id=777,
                admin_message_id=888,
                telegram_id=123456789,
                ticket_id=5,
            )

            row = db.get_support_link_by_admin_message(777, 888)

            self.assertIsNotNone(row)
            self.assertEqual(row["telegram_id"], 123456789)
            self.assertEqual(row["ticket_id"], 5)
        finally:
            tmpdir.cleanup()


class VpnIssueNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_admin_after_vpn_issue(self) -> None:
        from handlers.get_vpn import _notify_admin_about_vpn_issued

        bot = AsyncMock()
        settings = type("S", (), {"admin_telegram_ids": {555}})()

        await _notify_admin_about_vpn_issued(
            bot=bot,
            settings=settings,
            telegram_id=123456789,
            username="demo_user",
        )

        bot.send_message.assert_awaited_once()
        args = bot.send_message.await_args.kwargs
        self.assertEqual(args["chat_id"], 555)
        self.assertIn("123456789", args["text"])
        self.assertIn("demo_user", args["text"])


class SupportBotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_user_message_to_admin_creates_ticket_and_mapping(self) -> None:
        from handlers.support_bot import forward_user_message_to_admin

        db = Mock()
        db.create_ticket.return_value = 17
        db.link_support_admin_message.return_value = None

        bot = AsyncMock()
        bot.send_message.return_value.message_id = 321
        settings = type("S", (), {"admin_telegram_ids": {555}})()

        await forward_user_message_to_admin(
            bot=bot,
            db=db,
            settings=settings,
            telegram_id=123456789,
            username="demo_user",
            text="Не работает VPN",
        )

        db.create_ticket.assert_called_once_with(123456789, "Не работает VPN")
        db.link_support_admin_message.assert_called_once()

    async def test_forward_admin_reply_to_user_sends_message_from_bot(self) -> None:
        from handlers.support_bot import forward_admin_reply_to_user

        db = Mock()
        db.get_support_link_by_admin_message.return_value = {"telegram_id": 123456789, "ticket_id": 17}
        bot = AsyncMock()

        delivered = await forward_admin_reply_to_user(
            bot=bot,
            db=db,
            admin_chat_id=555,
            admin_message_id=321,
            text="Проверь, пожалуйста, настройки клиента.",
        )

        self.assertTrue(delivered)
        bot.send_message.assert_awaited_once_with(
            chat_id=123456789,
            text="Проверь, пожалуйста, настройки клиента.",
        )
