import tempfile
import unittest
from pathlib import Path

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
