import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from database import Database
from webapp import _ADMIN_APP_HTML, build_app


class StubSettings:
    bot_token = "test-token"
    admin_telegram_ids: set[int] = set()
    admin_telegram_usernames: set[str] = set()


class StubMarzban:
    async def get_user(self, username: str):
        return None

    async def get_user_online_status(self, username: str):
        return {"online_now": False, "online_status": "offline"}

    async def update_user_trial(self, username: str, expire_at, active: bool = True):
        return False

    async def create_user(self, username: str, expire_at):
        return {"username": username}

    async def disable_user(self, username: str):
        return False

    async def delete_user(self, username: str):
        return False


class StubBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class AdminUserManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.sqlite3")
        self.db = Database(self.db_path)
        self.db.init_schema()
        self.db.create_user_if_not_exists(telegram_id=1001, username="AlphaUser")
        self.db.set_user_expiry(1001, "2099-01-01 00:00:00")
        self.bot = StubBot()
        self.verify_admin_token_patcher = patch("webapp.verify_admin_token", return_value=1)
        self.verify_admin_token_patcher.start()
        app = build_app(self.db, StubSettings(), StubMarzban(), bot=self.bot)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.verify_admin_token_patcher.stop()
        try:
            self.tmpdir.cleanup()
        except PermissionError:
            pass

    def test_search_users_returns_trial_activity_flag(self) -> None:
        users = self.db.search_users("alpha", limit=10)
        self.assertIn("trial_active", users[0])
        self.assertTrue(bool(users[0]["trial_active"]))

    def test_user_detail_endpoint_returns_profile_payload(self) -> None:
        response = self.client.get("/admin-app/api/user/1001?token=test")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["user"]
        self.assertEqual(payload["telegram_id"], 1001)
        self.assertEqual(payload["username"], "AlphaUser")
        self.assertIn("online_status", payload)

    def test_trial_update_endpoint_accepts_absolute_expiry(self) -> None:
        response = self.client.post(
            "/admin-app/api/user/1001/trial?token=test",
            json={"expires_at": "2099-01-05T12:30", "no_trial_limits": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["expires_at"], "2099-01-05 12:30:00")
        self.assertIn("notification_sent", payload)

    def test_admin_html_contains_user_detail_shell(self) -> None:
        self.assertIn("userDetailSection", _ADMIN_APP_HTML)
        self.assertIn("Изменить дату подписки", _ADMIN_APP_HTML)


if __name__ == "__main__":
    unittest.main()
