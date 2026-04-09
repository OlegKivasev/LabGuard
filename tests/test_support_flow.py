import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from config import load_settings
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

    def test_load_settings_uses_admin_id_fallback(self) -> None:
        with patch.dict(
            "os.environ",
            {"ADMIN_ID": "777", "ADMIN_TELEGRAM_IDS": ""},
            clear=False,
        ):
            settings = load_settings()

        self.assertIn(777, settings.admin_telegram_ids)


class SupportRuntimeSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_runtime_settings_fetches_support_username_from_bot(self) -> None:
        from bot import _resolve_runtime_settings

        settings = replace(
            load_settings(),
            bot_token="test-token",
            support_bot_token="support-token",
            support_bot_username="",
        )
        support_bot = AsyncMock()
        support_bot.get_me.return_value = type("Me", (), {"username": "labguard_support_bot"})()

        resolved = await _resolve_runtime_settings(settings, support_bot)

        self.assertEqual(resolved.support_bot_username, "labguard_support_bot")


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
    async def test_forward_user_message_to_admin_posts_plain_message_without_profile_button(self) -> None:
        from handlers.support_bot import forward_user_message_to_admin

        db = Mock()
        db.create_ticket.return_value = 17
        db.get_support_topic_by_telegram_id.return_value = None
        db.set_support_topic.return_value = None

        bot = AsyncMock()
        bot.create_forum_topic.return_value = type("Topic", (), {"message_thread_id": 321})()
        settings = type("S", (), {"support_forum_chat_id": -100555})()

        await forward_user_message_to_admin(
            bot=bot,
            db=db,
            settings=settings,
            telegram_id=123456789,
            username="demo_user",
            text="Не работает VPN",
        )

        db.create_ticket.assert_called_once_with(123456789, "Не работает VPN")
        db.set_support_topic.assert_called_once_with(
            telegram_id=123456789,
            forum_chat_id=-100555,
            message_thread_id=321,
            ticket_id=17,
        )
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100555)
        self.assertEqual(kwargs["message_thread_id"], 321)
        self.assertEqual(
            kwargs["text"],
            "Пользователь: @demo_user\n"
            "Telegram ID: 123456789\n\n"
            "Не работает VPN",
        )
        self.assertNotIn("reply_markup", kwargs)

    async def test_forward_admin_reply_to_user_sends_message_from_bot(self) -> None:
        from handlers.support_bot import forward_admin_reply_to_user

        db = Mock()
        db.get_support_topic_by_thread.return_value = {"telegram_id": 123456789, "ticket_id": 17}
        bot = AsyncMock()

        delivered = await forward_admin_reply_to_user(
            bot=bot,
            db=db,
            forum_chat_id=-100555,
            message_thread_id=321,
            text="Проверь, пожалуйста, настройки клиента.",
        )

        self.assertTrue(delivered)
        bot.send_message.assert_awaited_once_with(
            chat_id=123456789,
            text="Проверь, пожалуйста, настройки клиента.",
        )

    async def test_forward_user_message_to_admin_reuses_existing_topic(self) -> None:
        from handlers.support_bot import forward_user_message_to_admin

        db = Mock()
        db.create_ticket.return_value = 21
        db.get_support_topic_by_telegram_id.return_value = {
            "forum_chat_id": -100555,
            "message_thread_id": 654,
            "telegram_id": 123456789,
        }

        bot = AsyncMock()
        settings = type("S", (), {"support_forum_chat_id": -100555})()

        ticket_id = await forward_user_message_to_admin(
            bot=bot,
            db=db,
            settings=settings,
            telegram_id=123456789,
            username="demo_user",
            text="Не работает VPN",
        )

        self.assertEqual(ticket_id, 21)
        bot.create_forum_topic.assert_not_called()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["message_thread_id"], 654)

    async def test_forward_user_message_to_admin_requires_forum_chat(self) -> None:
        from handlers.support_bot import forward_user_message_to_admin

        db = Mock()
        db.create_ticket.return_value = 22

        bot = AsyncMock()
        settings = type("S", (), {"support_forum_chat_id": 0})()

        with self.assertRaisesRegex(RuntimeError, "Support forum chat is not configured"):
            await forward_user_message_to_admin(
                bot=bot,
                db=db,
                settings=settings,
                telegram_id=123456789,
                username="demo_user",
                text="Не работает VPN",
            )

    async def test_support_user_message_replies_with_short_confirmation(self) -> None:
        from handlers.support_bot import support_user_message

        message = AsyncMock()
        message.from_user = type("User", (), {"id": 123456789, "username": "demo_user"})()
        message.text = "Не работает VPN"
        message.bot = AsyncMock()

        db = Mock()
        db.create_ticket.return_value = 17
        db.get_support_topic_by_telegram_id.return_value = {
            "forum_chat_id": -100555,
            "message_thread_id": 654,
            "telegram_id": 123456789,
        }
        settings = type(
            "S",
            (),
            {
                "support_forum_chat_id": -100555,
                "admin_telegram_ids": {555},
                "admin_telegram_usernames": set(),
            },
        )()

        await support_user_message(message=message, db=db, settings=settings)

        message.answer.assert_awaited_once_with(
            "Ваше сообщение отправлено. Оператор ответит вам в ближайшее время."
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
        self.assertNotIn("Дата окончания", _USER_APP_HTML)


class SubscriptionDisplayNameTests(unittest.TestCase):
    def test_apply_subscription_display_names_replaces_any_vless_fragment(self) -> None:
        from handlers.get_vpn import _apply_subscription_display_names

        raw = "vless://uuid@example.com:443?type=tcp#%F0%9F%9A%80%20Marz%20%28labguard_olegkivasev%29%20%5BVLESS%20-%20tcp%5D"

        updated = _apply_subscription_display_names(raw)

        self.assertEqual(updated, "vless://uuid@example.com:443?type=tcp#%D0%A4%D0%B8%D0%BD%D0%BB%D1%8F%D0%BD%D0%B4%D0%B8%D1%8F")

    def test_apply_subscription_display_names_replaces_any_http_fragment(self) -> None:
        from handlers.get_vpn import _apply_subscription_display_names

        raw = "https://example.com/sub/abc#LabGuard"

        updated = _apply_subscription_display_names(raw)

        self.assertEqual(updated, "https://example.com/sub/abc#Финляндия")


class StubSettings:
    bot_token = "test-token"
    support_bot_token = "support-token"
    support_bot_username = "labguard_support_bot"
    support_forum_chat_id = -100555
    marzban_base_url = "https://example.com"
    marzban_api_key = ""
    marzban_username = ""
    marzban_password = ""
    marzban_verify_tls = False
    database_path = "./test.sqlite3"
    free_trial_days = 14
    admin_telegram_ids = {555}
    admin_telegram_usernames = set()
    web_app_base_url = ""
    web_app_host = "127.0.0.1"
    web_app_port = 8081
    web_app_token_ttl_minutes = 30


class StubBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class StubMarzbanForMiniApp:
    def __init__(self) -> None:
        self.base_url = "https://example.com"
        self.create_counter = 0

    @property
    def is_configured(self) -> bool:
        return True

    async def create_user(self, username: str, expire_at):
        self.create_counter += 1
        return {
            "username": username,
            "expire": 4070908800,
            "subscription_url": f"https://example.com/sub/{self.create_counter}#subscription",
        }

    async def get_user(self, username: str):
        return {
            "username": username,
            "used_traffic": 0,
            "subscription_url": "https://example.com/sub/rotating#subscription",
        }


class MiniAppApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from webapp import build_app

        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "miniapp.sqlite3")
        self.db = Database(self.db_path)
        self.db.init_schema()
        self.bot = StubBot()
        self.marzban = StubMarzbanForMiniApp()
        self.verify_user_patcher = patch("webapp.verify_telegram_init_data", return_value=(1001, "demo_user"))
        self.verify_user_patcher.start()
        app = build_app(self.db, StubSettings(), self.marzban, bot=self.bot)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.verify_user_patcher.stop()
        self.tmpdir.cleanup()

    def test_miniapp_get_vpn_notifies_admin_and_persists_stable_named_subscription(self) -> None:
        activation = self.client.post("/app/api/get-vpn")
        self.assertEqual(activation.status_code, 200)
        payload = activation.json()
        self.assertTrue(payload["subscription_url"].endswith("#Финляндия"))
        self.assertTrue(any(chat_id == 555 for chat_id, _ in self.bot.messages))

        status = self.client.get("/app/api/status")
        self.assertEqual(status.status_code, 200)
        status_payload = status.json()
        self.assertEqual(status_payload["subscription_url"], payload["subscription_url"])
