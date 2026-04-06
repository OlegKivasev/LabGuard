import asyncio
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path

from database import Database
from scheduler import send_expiry_notifications


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


async def main() -> None:
    tmp_dir = tempfile.mkdtemp(prefix="vpn-bot-smoke-")
    db_path = Path(tmp_dir) / "app.db"

    db = Database(str(db_path))
    db.init_schema()

    db.create_user_if_not_exists(100, "user100")
    db.create_user_if_not_exists(101, "user101")
    db.ensure_trial(100)
    db.ensure_trial(101)

    exp_3d = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2, hours=12))
    exp_1d = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=20))
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET expires_at=? WHERE telegram_id=100",
            (exp_3d.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        conn.execute(
            "UPDATE users SET expires_at=? WHERE telegram_id=101",
            (exp_1d.strftime("%Y-%m-%d %H:%M:%S"),),
        )

    bot = FakeBot()
    await send_expiry_notifications(bot, db)

    with db.connect() as conn:
        n3 = conn.execute(
            "SELECT notified_3d FROM users WHERE telegram_id=100"
        ).fetchone()[0]
        n1 = conn.execute(
            "SELECT notified_1d FROM users WHERE telegram_id=101"
        ).fetchone()[0]

    print("messages_sent:", len(bot.sent))
    print("notification_flags_ok:", n3 == 1 and n1 == 1)


if __name__ == "__main__":
    asyncio.run(main())
