"""Small per-user update throttle to protect the bot from accidental floods."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import Settings


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, interval: float = 0.35) -> None:
        self.settings = settings
        self.interval = interval
        self.last_seen: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if isinstance(event, Message) and user and not self.settings.is_admin(user.id):
            now = time.monotonic()
            previous = self.last_seen.get(user.id, 0.0)
            if now - previous < self.interval:
                return None
            self.last_seen[user.id] = now
        return await handler(event, data)
