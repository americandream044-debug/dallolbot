"""Update activity capture for basic engagement analytics."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.db.repo import Repo
from bot.config import Settings


class EventsLoggerMiddleware(BaseMiddleware):
    def __init__(self, repo: Repo, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user:
            source = None
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                parts = event.text.split(maxsplit=1)
                source = parts[1][:64] if len(parts) > 1 else None
            await self.repo.upsert_user(user.id, user.username, user.first_name or "", source)
            await self.repo.add_event(user.id, "activity", {"kind": type(event).__name__})
            if self.settings.is_admin(user.id):
                action = "callback" if not isinstance(event, Message) else ("command" if event.text and event.text.startswith("/") else "message")
                label = getattr(event, "data", None) if action == "callback" else (event.text.split(maxsplit=1)[0][:40] if action == "command" else str(event.content_type))
                await self.repo.audit(user.id, action, str(label or "")[:80])
        return await handler(event, data)
