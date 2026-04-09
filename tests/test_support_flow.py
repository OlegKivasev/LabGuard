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


class MiniAppCopyTests(unittest.TestCase):
    def test_user_app_uses_support_bot_linking(self) -> None:
        from webapp import _USER_APP_HTML

        self.assertIn("?start=app_support", _USER_APP_HTML)

    def test_user_app_removes_need_support_copy(self) -> None:
        from webapp import _USER_APP_HTML

        self.assertNotIn("Нужна поддержка", _USER_APP_HTML)
        self.assertIn("Подписка истекла", _USER_APP_HTML)
        self.assertIn("Подписка не активирована", _USER_APP_HTML)


class SubscriptionDisplayNameTests(unittest.TestCase):
    def test_apply_subscription_display_names(self) -> None:
        from handlers.get_vpn import _apply_subscription_display_names

        raw = "vless://uuid@example.com:443?type=tcp#subscription"

        updated = _apply_subscription_display_names(raw)

        self.assertIn("%F0%9F%87%AB%F0%9F%87%AE%20%D0%A4%D0%B8%D0%BD%D0%BB%D1%8F%D0%BD%D0%B4%D0%B8%D1%8F%20VPN", updated)

    def test_apply_subscription_name_for_http_subscription_url(self) -> None:
        from handlers.get_vpn import _apply_subscription_display_names

        raw = "https://example.com/sub/abc#subscription"

        updated = _apply_subscription_display_names(raw)

        self.assertIn("#LabGuard", updated)
