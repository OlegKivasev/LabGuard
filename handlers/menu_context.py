from datetime import datetime, timezone
from typing import Any

from .keyboards import main_menu_keyboard


def _has_active_subscription(user: dict[str, Any] | None) -> bool:
    if user is None:
        return False

    expires_raw = user.get("expires_at")
    if not expires_raw:
        return False

    try:
        expires_at = datetime.strptime(str(expires_raw), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return False

    return expires_at > datetime.now(timezone.utc)


def main_menu_for_user(user: dict[str, Any] | None):
    show_status = user is not None
    show_get_vpn = not _has_active_subscription(user)
    return main_menu_keyboard(show_get_vpn=show_get_vpn, show_status=show_status)
