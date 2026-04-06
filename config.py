from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    marzban_base_url: str
    marzban_api_key: str
    database_path: str
    free_trial_days: int
    support_bot_username: str

    def missing_for_bot_start(self) -> list[str]:
        missing: list[str] = []

        if not self.bot_token:
            missing.append("BOT_TOKEN")

        return missing


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        marzban_base_url=os.getenv("MARZBAN_BASE_URL", "").strip(),
        marzban_api_key=os.getenv("MARZBAN_API_KEY", "").strip(),
        database_path=os.getenv("DATABASE_PATH", "./data/app.db").strip(),
        free_trial_days=int(os.getenv("FREE_TRIAL_DAYS", "14")),
        support_bot_username=os.getenv("SUPPORT_BOT_USERNAME", "").strip(),
    )
