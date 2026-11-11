"""Channel publishing, HTML sanitization, and post lifecycle."""
from __future__ import annotations

import re
import json
import html
from datetime import datetime, timezone

import bleach
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.db.repo import Repo, utc_now
from bot.services.reaction_service import ReactionService
from bot.ui.stylizer import stylize

ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "blockquote", "a", "tg-spoiler"}
ALLOWED_ATTRIBUTES = {"a": ["href"], "blockquote": ["expandable"]}


def sanitize_telegram_html(value: str) -> str:
    """Strip unsafe HTML while preserving Telegram's supported formatting tags."""
    cleaned = bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, protocols={"http", "https", "tg"}, strip=True)
    return cleaned


def visible_text_length(body: str) -> int:
    """Count rendered characters rather than HTML markup or encoded entities."""
    plain = re.sub(r"<[^>]+>", "", body)
    return len(html.unescape(plain))


def extract_title(body: str) -> str:
    plain = re.sub(r"<[^>]+>", "", body)
    plain = bleach.clean(plain, tags=[], strip=True).strip()
    return plain.splitlines()[0][:180] if plain else "Yangi post"


class PostService:
    def __init__(self, bot: Bot, settings: Settings, repo: Repo) -> None:
        self.bot = bot
        self.settings = settings
        self.repo = repo
        self.reactions = ReactionService(bot, settings, repo)

    async def save_draft(self, body_html: str, style: str, font: str, title: str = "", media_type: str | None = None, media_file_id: str | None = None) -> int:
        safe_html = sanitize_telegram_html(stylize(body_html, font))
        return await self.repo.create_post(title or extract_title(safe_html), safe_html, style, font, "draft", media_type=media_type, media_file_id=media_file_id)

    async def publish(self, post_id: int, notify: bool = False, pin: bool = False) -> int:
        post = await self.repo.get_post(post_id)
        if not post:
            raise ValueError("Post topilmadi.")
        body = sanitize_telegram_html(str(post["body_html"]))
        media_type = post.get("media_type")
        character_limit = 1024 if media_type in {"photo", "video", "document"} else 4096
        visible_length = visible_text_length(body)
        if visible_length > character_limit:
            raise ValueError(
                f"Post {visible_length} belgidan iborat. Telegram limiti: {character_limit}. "
                "Avval postni qisqartiring yoki editor asbobidan foydalaning."
            )
        button_rows = []
        try:
            button_data = json.loads(post.get("buttons_json") or "[]")
            button_rows = [[InlineKeyboardButton(text=str(item["text"])[:50], url=str(item["url"]))] for item in button_data[:4] if item.get("text") and item.get("url")]
        except (json.JSONDecodeError, TypeError, KeyError):
            button_rows = []
        reply_markup = InlineKeyboardMarkup(inline_keyboard=button_rows) if button_rows else None
        if post.get("media_type") == "photo" and post.get("media_file_id"):
            sent = await self.bot.send_photo(self.settings.channel_id, post["media_file_id"], caption=body[:1024], disable_notification=not notify, reply_markup=reply_markup)
        elif post.get("media_type") == "video" and post.get("media_file_id"):
            sent = await self.bot.send_video(self.settings.channel_id, post["media_file_id"], caption=body[:1024], disable_notification=not notify, reply_markup=reply_markup)
        elif post.get("media_type") == "document" and post.get("media_file_id"):
            sent = await self.bot.send_document(self.settings.channel_id, post["media_file_id"], caption=body[:1024], disable_notification=not notify, reply_markup=reply_markup)
        else:
            sent = await self.bot.send_message(self.settings.channel_id, body, disable_notification=not notify, link_preview_options=None, reply_markup=reply_markup)
        if post.get("poll_question") and post.get("poll_options_json"):
            try:
                options = json.loads(post["poll_options_json"])
                if 2 <= len(options) <= 10:
                    poll = await self.bot.send_poll(self.settings.channel_id, str(post["poll_question"])[:300], [str(x)[:100] for x in options], is_anonymous=True, disable_notification=not notify)
                    await self.repo.update_post(post_id, poll_message_id=poll.message_id)
            except Exception:
                # Poll failure must not mark an already-published channel post as failed.
                pass
        recurring = bool(post.get("recurrence"))
        await self.repo.update_post(
            post_id,
            status="published",
            channel_message_id=sent.message_id,
            published_at=utc_now(),
            scheduled_at=utc_now() if recurring else None,
        )
        await self.repo.add_event(None, "post_published", {"post_id": post_id, "message_id": sent.message_id, "style": post["style"], "tag": post["tag"]})
        if pin:
            try:
                await self.bot.pin_chat_message(self.settings.channel_id, sent.message_id, disable_notification=True)
            except Exception:
                pass
        await self.reactions.apply_default(sent.message_id)
        return sent.message_id

    async def edit_published(self, post_id: int, body_html: str) -> bool:
        post = await self.repo.get_post(post_id)
        if not post or not post.get("channel_message_id"):
            return False
        safe = sanitize_telegram_html(body_html)
        if post.get("media_type"):
            await self.bot.edit_message_caption(self.settings.channel_id, int(post["channel_message_id"]), caption=safe[:1024])
        else:
            await self.bot.edit_message_text(safe, self.settings.channel_id, int(post["channel_message_id"]))
        await self.repo.update_post(post_id, body_html=safe, title=extract_title(safe))
        return True

    async def delete_published(self, post_id: int) -> bool:
        post = await self.repo.get_post(post_id)
        if not post or not post.get("channel_message_id"):
            return False
        await self.bot.delete_message(self.settings.channel_id, int(post["channel_message_id"]))
        await self.repo.update_post(post_id, status="failed")
        return True
