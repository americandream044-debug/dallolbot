"""Environment configuration and startup validation."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    channel_id: int | str
    channel_username: str
    ai_provider: str
    ai_api_key: str
    ai_model: str
    timezone: str = "Asia/Tashkent"
    db_path: str = "./data/bot.sqlite3"
    backup_chat_id: int = 0
    support_cooldown: int = 30
    max_message_length: int = 3500
    log_level: str = "INFO"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f".env sozlamasida {name} ko'rsatilmagan.")
    return value


def load_settings() -> Settings:
    """Load .env, validate required values, and return immutable settings."""
    load_dotenv()
    token = _required("BOT_TOKEN")
    raw_admins = _required("ADMIN_IDS")
    try:
        admin_order = [int(x.strip()) for x in raw_admins.split(",") if x.strip()]
        admins = frozenset(admin_order)
    except ValueError as exc:
        raise ConfigError("ADMIN_IDS faqat vergul bilan ajratilgan Telegram raqamli ID'laridan iborat bo'lishi kerak.") from exc
    if not admins:
        raise ConfigError("ADMIN_IDS ichida kamida bitta admin ID bo'lishi kerak.")

    raw_channel = _required("CHANNEL_ID")
    try:
        channel_id: int | str = int(raw_channel)
    except ValueError:
        channel_id = raw_channel
    channel_username = _required("CHANNEL_USERNAME").lstrip("@")
    provider = _required("AI_PROVIDER").lower()
    if provider not in {"openai", "anthropic"}:
        raise ConfigError("AI_PROVIDER qiymati 'openai' yoki 'anthropic' bo'lishi kerak.")
    api_key = _required("AI_API_KEY")
    model = _required("AI_MODEL")
    timezone = os.getenv("TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent"
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"TIMEZONE noto'g'ri: {timezone}") from exc

    try:
        backup_chat_id = int(os.getenv("BACKUP_CHAT_ID", "").strip() or admin_order[0])
        cooldown = max(5, int(os.getenv("SUPPORT_COOLDOWN", "30")))
        max_message_length = max(500, min(3500, int(os.getenv("MAX_MESSAGE_LENGTH", "3500"))))
    except ValueError as exc:
        raise ConfigError("BACKUP_CHAT_ID, SUPPORT_COOLDOWN va MAX_MESSAGE_LENGTH son bo'lishi kerak.") from exc

    db_path = os.getenv("DB_PATH", "./data/bot.sqlite3").strip() or "./data/bot.sqlite3"
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        admin_ids=admins,
        channel_id=channel_id,
        channel_username=channel_username,
        ai_provider=provider,
        ai_api_key=api_key,
        ai_model=model,
        timezone=timezone,
        db_path=db_path,
        backup_chat_id=backup_chat_id,
        support_cooldown=cooldown,
        max_message_length=max_message_length,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
