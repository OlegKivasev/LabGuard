from aiogram import Dispatcher

from .admin import router as admin_router
from .get_vpn import router as get_vpn_router
from .help import router as help_router
from .start import router as start_router
from .status import router as status_router
from .support import router as support_router


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(get_vpn_router)
    dp.include_router(status_router)
    dp.include_router(help_router)
    dp.include_router(support_router)
