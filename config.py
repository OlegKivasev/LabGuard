from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    support_bot_token: str
    xui_base_url: str
    xui_username: str
    xui_password: str
    xui_inbound_id: int
    xui_subscription_name: str
    xui_server_name: str
    xui_subscription_path: str
    xui_verify_tls: bool
    database_path: str
    free_trial_days: int
    support_bot_username: str
    support_forum_chat_id: int
    admin_telegram_ids: set[int]
    admin_telegram_usernames: set[str]
    web_app_base_url: str
    web_app_host: str
    web_app_port: int
    web_app_token_ttl_minutes: int

    def missing_for_bot_start(self) -> list[str]:
        missing: list[str] = []

        if not self.bot_token:
            missing.append("BOT_TOKEN")

        return missing

    def missing_for_support_bot_start(self) -> list[str]:
        missing: list[str] = []

        if not self.support_bot_token:
            missing.append("SUPPORT_BOT_TOKEN")

        return missing

    def missing_for_xui(self) -> list[str]:
        missing: list[str] = []

        if not self.xui_base_url:
            missing.append("XUI_BASE_URL")
        if not self.xui_username:
            missing.append("XUI_USERNAME")
        if not self.xui_password:
            missing.append("XUI_PASSWORD")
        if not self.xui_inbound_id:
            missing.append("XUI_INBOUND_ID")

        return missing


def load_settings() -> Settings:
    load_dotenv()

    verify_raw = os.getenv("XUI_VERIFY_TLS", "true").strip().lower()
    verify_tls = verify_raw not in {"0", "false", "no", "off"}

    admin_ids_raw = os.getenv("ADMIN_TELEGRAM_IDS", "").strip()
    if not admin_ids_raw:
        admin_ids_raw = os.getenv("ADMIN_ID", "").strip()
    admin_ids: set[int] = set()
    admin_usernames: set[str] = set()
    if admin_ids_raw:
        for part in admin_ids_raw.split(","):
            value = part.strip()
            if not value:
                continue
            if value.isdigit():
                admin_ids.add(int(value))
            else:
                admin_usernames.add(value.lstrip("@").lower())

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        support_bot_token=os.getenv("SUPPORT_BOT_TOKEN", "").strip(),
        xui_base_url=os.getenv("XUI_BASE_URL", "").strip(),
        xui_username=os.getenv("XUI_USERNAME", "").strip(),
        xui_password=os.getenv("XUI_PASSWORD", "").strip(),
        xui_inbound_id=int(os.getenv("XUI_INBOUND_ID", "0") or "0"),
        xui_subscription_name=os.getenv("XUI_SUBSCRIPTION_NAME", "LabGuard").strip() or "LabGuard",
        xui_server_name=os.getenv("XUI_SERVER_NAME", "Финляндия").strip() or "Финляндия",
        xui_subscription_path=os.getenv("XUI_SUBSCRIPTION_PATH", "/sub/").strip() or "/sub/",
        xui_verify_tls=verify_tls,
        database_path=os.getenv("DATABASE_PATH", "./data/app.db").strip(),
        free_trial_days=int(os.getenv("FREE_TRIAL_DAYS", "14")),
        support_bot_username=os.getenv("SUPPORT_BOT_USERNAME", "").strip(),
        support_forum_chat_id=int(os.getenv("SUPPORT_FORUM_CHAT_ID", "0") or "0"),
        admin_telegram_ids=admin_ids,
        admin_telegram_usernames=admin_usernames,
        web_app_base_url=os.getenv("WEB_APP_BASE_URL", "").strip(),
        web_app_host=os.getenv("WEB_APP_HOST", "0.0.0.0").strip(),
        web_app_port=int(os.getenv("WEB_APP_PORT", "8081")),
        web_app_token_ttl_minutes=int(os.getenv("WEB_APP_TOKEN_TTL_MINUTES", "30")),
    )
