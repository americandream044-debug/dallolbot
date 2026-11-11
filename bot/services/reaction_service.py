"""Default post reaction and reaction-count snapshot support."""
from __future__ import annotations

import json

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji

from bot.config import Settings
from bot.db.repo import Repo

ALLOWED_REACTIONS = ("🔥", "🤯", "👨‍💻", "👾", "💯", "⚡")


class ReactionService:
    def __init__(self, bot: Bot, settings: Settings, repo: Repo) -> None:
        self.bot = bot
        self.settings = settings
        self.repo = repo

    async def apply_default(self, message_id: int) -> bool:
        if await self.repo.get_setting("auto_reaction", "0") != "1":
            return False
        emoji = await self.repo.get_setting("reaction_emoji", "🔥")
        if emoji not in ALLOWED_REACTIONS:
            emoji = "🔥"
        try:
            await self.bot.set_message_reaction(
                chat_id=self.settings.channel_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return True
        except Exception:
            return False

    async def capture_update(self, update: object) -> bool:
        message_id = getattr(update, "message_id", None)
        chat = getattr(update, "chat", None)
        if message_id is None or chat is None or str(chat.id) != str(self.settings.channel_id):
            return False
        post = await self.repo.post_by_message_id(int(message_id))
        if not post:
            return False
        reactions = getattr(update, "reactions", []) or []
        counts: dict[str, int] = {}
        for item in reactions:
            reaction = getattr(item, "type", None)
            emoji = getattr(reaction, "emoji", None) or getattr(reaction, "custom_emoji_id", "custom")
            counts[str(emoji)] = int(getattr(item, "total_count", 0))
        await self.repo.save_reaction_snapshot(int(post["id"]), counts)
        return True
