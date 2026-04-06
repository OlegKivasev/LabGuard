from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    telegram_id   INTEGER UNIQUE,
    username      TEXT,
    marzban_id    TEXT,
    platform      TEXT,
    source        TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at    DATETIME,
    last_active   DATETIME,
    notified_3d   BOOLEAN DEFAULT 0,
    notified_1d   BOOLEAN DEFAULT 0,
    gave_feedback BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    telegram_id INTEGER,
    event       TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id           INTEGER PRIMARY KEY,
    telegram_id  INTEGER,
    status       TEXT DEFAULT 'open',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at    DATETIME
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    ticket_id  INTEGER REFERENCES tickets(id),
    sender     TEXT,
    text       TEXT,
    sent_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date            DATE PRIMARY KEY,
    new_users       INTEGER DEFAULT 0,
    active_users    INTEGER DEFAULT 0,
    vpn_active      INTEGER DEFAULT 0,
    total_traffic   INTEGER DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def create_user_if_not_exists(
        self,
        telegram_id: int,
        username: str | None = None,
        platform: str = "unknown",
        source: str = "direct",
    ) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO users (telegram_id, username, platform, source)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, username, platform, source),
            )
            return cursor.rowcount > 0

    def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()

            if row is None:
                return None

            return dict(row)

    def list_recent_users(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_id, username, marzban_id, expires_at, created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def search_users(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            q = query.strip()
            if not q:
                rows = conn.execute(
                    """
                    SELECT telegram_id, username, marzban_id, expires_at, created_at
                    FROM users
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]

            pattern = f"%{q}%"
            rows = conn.execute(
                """
                SELECT telegram_id, username, marzban_id, expires_at, created_at
                FROM users
                WHERE CAST(telegram_id AS TEXT) LIKE ?
                   OR LOWER(COALESCE(username, '')) LIKE LOWER(?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def log_event(self, telegram_id: int, event: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events (telegram_id, event) VALUES (?, ?)",
                (telegram_id, event),
            )

    def set_marzban_binding(
        self,
        telegram_id: int,
        marzban_id: str,
        expires_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET marzban_id = ?, expires_at = ? WHERE telegram_id = ?",
                (marzban_id, expires_at, telegram_id),
            )

    def clear_trial(self, telegram_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET marzban_id = NULL,
                    expires_at = NULL,
                    notified_3d = 0,
                    notified_1d = 0,
                    gave_feedback = 0
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            )
            return cursor.rowcount > 0

    def delete_user(self, telegram_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            return cursor.rowcount > 0

    def ensure_trial(self, telegram_id: int, days: int = 14) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"User with telegram_id={telegram_id} not found")

            expires_at = row["expires_at"]
            if expires_at:
                return str(expires_at)

            expiry_dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=days)
            expiry_text = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

            conn.execute(
                "UPDATE users SET expires_at = ? WHERE telegram_id = ?",
                (expiry_text, telegram_id),
            )
            return expiry_text

    def touch_last_active(self, telegram_id: int) -> None:
        now_text = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_active = ? WHERE telegram_id = ?",
                (now_text, telegram_id),
            )

    def list_users_for_3d_notification(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_id, expires_at
                FROM users
                WHERE expires_at IS NOT NULL AND notified_3d = 0
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_users_for_1d_notification(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_id, expires_at
                FROM users
                WHERE expires_at IS NOT NULL AND notified_1d = 0
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_notified_3d(self, telegram_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET notified_3d = 1 WHERE telegram_id = ?",
                (telegram_id,),
            )

    def mark_notified_1d(self, telegram_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET notified_1d = 1 WHERE telegram_id = ?",
                (telegram_id,),
            )

    def create_ticket(self, telegram_id: int, text: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO tickets (telegram_id) VALUES (?)",
                (telegram_id,),
            )
            ticket_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO messages (ticket_id, sender, text) VALUES (?, 'user', ?)",
                (ticket_id, text),
            )
            return ticket_id

    def get_admin_overview(self) -> dict[str, int]:
        with self.connect() as conn:
            total_users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            active_trials = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM users
                    WHERE expires_at IS NOT NULL AND datetime(expires_at) > datetime('now')
                    """
                ).fetchone()[0]
            )
            new_today = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')"
                ).fetchone()[0]
            )
            get_today = int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event = 'get' AND date(created_at) = date('now')"
                ).fetchone()[0]
            )
            start_today = int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event = 'start' AND date(created_at) = date('now')"
                ).fetchone()[0]
            )
            open_tickets = int(
                conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'").fetchone()[0]
            )

        return {
            "total_users": total_users,
            "active_trials": active_trials,
            "new_today": new_today,
            "start_today": start_today,
            "get_today": get_today,
            "open_tickets": open_tickets,
        }
