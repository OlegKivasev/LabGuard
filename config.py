from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    marzban_base_url: str
    marzban_api_key: str
    marzban_username: str
    marzban_password: str
    marzban_verify_tls: bool
    database_path: str
    free_trial_days: int
    support_bot_username: str
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

    def missing_for_marzban(self) -> list[str]:
        missing: list[str] = []

        if not self.marzban_base_url:
            missing.append("MARZBAN_BASE_URL")

        has_token = bool(self.marzban_api_key)
        has_credentials = bool(self.marzban_username and self.marzban_password)
        if not has_token and not has_credentials:
            missing.append("MARZBAN_API_KEY or MARZBAN_USERNAME+MARZBAN_PASSWORD")

        return missing


def load_settings() -> Settings:
    load_dotenv()

    verify_raw = os.getenv("MARZBAN_VERIFY_TLS", "true").strip().lower()
    verify_tls = verify_raw not in {"0", "false", "no", "off"}

    admin_ids_raw = os.getenv("ADMIN_TELEGRAM_IDS", "").strip()
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
        marzban_base_url=os.getenv("MARZBAN_BASE_URL", "").strip(),
        marzban_api_key=os.getenv("MARZBAN_API_KEY", "").strip(),
        marzban_username=os.getenv("MARZBAN_USERNAME", "").strip(),
        marzban_password=os.getenv("MARZBAN_PASSWORD", "").strip(),
        marzban_verify_tls=verify_tls,
        database_path=os.getenv("DATABASE_PATH", "./data/app.db").strip(),
        free_trial_days=int(os.getenv("FREE_TRIAL_DAYS", "14")),
        support_bot_username=os.getenv("SUPPORT_BOT_USERNAME", "").strip(),
        admin_telegram_ids=admin_ids,
        admin_telegram_usernames=admin_usernames,
        web_app_base_url=os.getenv("WEB_APP_BASE_URL", "").strip(),
        web_app_host=os.getenv("WEB_APP_HOST", "0.0.0.0").strip(),
        web_app_port=int(os.getenv("WEB_APP_PORT", "8081")),
        web_app_token_ttl_minutes=int(os.getenv("WEB_APP_TOKEN_TTL_MINUTES", "30")),
    )
