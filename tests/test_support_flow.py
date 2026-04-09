import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

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
