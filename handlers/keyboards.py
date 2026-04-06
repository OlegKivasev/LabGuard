from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


CB_GET_INFO = "menu:get_info"
CB_GET_CONFIRM = "menu:get_confirm"
CB_STATUS = "menu:status"
CB_HELP = "menu:help"
CB_APPS = "menu:apps"
CB_SUPPORT = "menu:support"
CB_BACK = "menu:back"
CB_SUPPORT_CANCEL = "menu:support_cancel"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить VPN", callback_data=CB_GET_INFO)],
            [
                InlineKeyboardButton(text="Мой статус", callback_data=CB_STATUS),
                InlineKeyboardButton(text="Как подключить", callback_data=CB_HELP),
            ],
            [
                InlineKeyboardButton(text="Приложения", callback_data=CB_APPS),
                InlineKeyboardButton(text="Поддержка", callback_data=CB_SUPPORT),
            ],
        ]
    )


def subscription_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить подписку", callback_data=CB_GET_CONFIRM)],
            [InlineKeyboardButton(text="Назад в меню", callback_data=CB_BACK)],
        ]
    )


def post_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мой статус", callback_data=CB_STATUS)],
            [
                InlineKeyboardButton(text="Как подключить", callback_data=CB_HELP),
                InlineKeyboardButton(text="Приложения", callback_data=CB_APPS),
            ],
            [InlineKeyboardButton(text="Поддержка", callback_data=CB_SUPPORT)],
            [InlineKeyboardButton(text="Главное меню", callback_data=CB_BACK)],
        ]
    )


def support_wait_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=CB_SUPPORT_CANCEL)],
            [InlineKeyboardButton(text="Главное меню", callback_data=CB_BACK)],
        ]
    )
