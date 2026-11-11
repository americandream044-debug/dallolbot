"""Mandatory-subscription gate with a sixty-second membership cache."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject

from bot.config import Settings
from bot.db.repo import Repo
from bot.ui.keyboards import subscription_keyboard
from bot.ui.texts import subscription_text


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, repo: Repo) -> None:
        self.settings = settings
        self.repo = repo
        self.cache: dict[int, tuple[float, bool]] = {}

    async def _is_member(self, bot: Any, user_id: int) -> bool:
        cached = self.cache.get(user_id)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        try:
            member = await bot.get_chat_member(self.settings.channel_id, user_id)
            result = member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        except (TelegramBadRequest, TelegramForbiddenError):
            result = False
        self.cache[user_id] = (time.monotonic(), result)
        return result

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or self.settings.is_admin(user.id):
            return await handler(event, data)
        if await self.repo.is_banned(user.id):
            return None
        # Protected commands and forged admin callbacks must reach the admin gate,
        # not reveal the mandatory-subscription screen.
        if isinstance(event, Message) and event.text and event.text.split(maxsplit=1)[0].split("@")[0] == "/admin":
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data and event.data.startswith(("admin:", "ai:", "post:", "schedule:", "ticket:", "tickets:", "analytics:", "broadcast:", "users:", "tools:", "settings:")):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "sub:check":
            self.cache.pop(user.id, None)
        required = await self.repo.get_setting("subscription_required", "1") == "1"
        if not required or await self._is_member(data["bot"], user.id):
            return await handler(event, data)

        markup = subscription_keyboard(f"https://t.me/{self.settings.channel_username}")
        text = subscription_text(self.settings.channel_username)
        if isinstance(event, CallbackQuery):
            await event.answer("Avval kanalga obuna bo‘ling.", show_alert=False)
            try:
                await event.message.edit_text(text, reply_markup=markup)
            except Exception:
                await event.message.answer(text, reply_markup=markup)
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
        # Chat-member and reaction updates do not represent a user action.
        return None
