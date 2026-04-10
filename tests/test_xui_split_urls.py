import unittest
import sys
import types
from unittest.mock import patch

dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv_stub)

httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object
sys.modules.setdefault("httpx", httpx_stub)

from config import load_settings
from xui import XUIClient


class XuiSplitUrlTests(unittest.TestCase):
    def test_load_settings_reads_xui_public_base_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "XUI_BASE_URL": "http://127.0.0.1:54321/base",
                "XUI_PUBLIC_BASE_URL": "https://panel.example.com:8444",
            },
            clear=False,
        ):
            settings = load_settings()

        self.assertEqual(settings.xui_base_url, "http://127.0.0.1:54321/base")
        self.assertEqual(settings.xui_public_base_url, "https://panel.example.com:8444")

    def test_subscription_url_uses_public_base_url(self) -> None:
        client = XUIClient(
            base_url="http://127.0.0.1:54321/10xUV5tZLeAEUT0bDf",
            public_base_url="https://panel.example.com:8444",
            username="demo",
            password="secret",
            inbound_id=1,
            subscription_path="/sub/",
        )

        inbound = {
            "id": 1,
            "settings": '{"clients": [{"id": "cid-1", "email": "demo", "subId": "sub-123", "enable": true, "expiryTime": 0}]}',
            "clientStats": [],
        }

        record = client._build_client_record(inbound, client._extract_clients(inbound)[0])

        self.assertEqual(record.subscription_url, "https://panel.example.com:8444/sub/sub-123#LabGuard")


if __name__ == "__main__":
    unittest.main()
