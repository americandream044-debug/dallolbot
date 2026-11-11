"""Admin-only filters and explicit callback authorization checks."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.config import Settings


class AdminFilter(BaseFilter):
    """Reject non-admin updates without revealing protected commands."""

    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        user = event.from_user
        if settings.is_admin(user.id if user else None):
            return True
        return False


async def require_admin(callback: CallbackQuery, settings: Settings) -> bool:
    """Re-check permissions inside every admin callback handler."""
    if settings.is_admin(callback.from_user.id if callback.from_user else None):
        return True
    await callback.answer("Buyruq topilmadi", show_alert=False)
    return False
