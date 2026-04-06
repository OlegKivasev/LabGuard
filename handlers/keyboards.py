from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


CB_GET_INFO = "menu:get_info"
CB_GET_CONFIRM = "menu:get_confirm"
CB_STATUS = "menu:status"
CB_SUPPORT = "menu:support"
CB_SUPPORT_CANCEL = "menu:support_cancel"


def main_menu_keyboard(show_get_vpn: bool = True, show_status: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if show_get_vpn:
        rows.append([InlineKeyboardButton(text="Получить VPN", callback_data=CB_GET_INFO)])

    if show_status:
        rows.append([InlineKeyboardButton(text="Мой статус", callback_data=CB_STATUS)])

    rows.append([InlineKeyboardButton(text="Поддержка", callback_data=CB_SUPPORT)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить подписку", callback_data=CB_GET_CONFIRM)],
        ]
    )


def post_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мой статус", callback_data=CB_STATUS)],
            [InlineKeyboardButton(text="Поддержка", callback_data=CB_SUPPORT)],
        ]
    )


def support_wait_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=CB_SUPPORT_CANCEL)],
        ]
    )


def open_app_keyboard(web_app_base_url: str) -> InlineKeyboardMarkup:
    app_url = f"{web_app_base_url.rstrip('/')}/app"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=app_url))],
        ]
    )
