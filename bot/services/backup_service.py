"""SQLite backup creation and delivery without leaving temporary files."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import aiosqlite
from aiogram import Bot
from aiogram.types import FSInputFile

from bot.config import Settings


class BackupService:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

    async def create_backup(self) -> Path:
        """Create a consistent SQLite backup using SQLite's online backup API."""
        fd, name = tempfile.mkstemp(prefix="dasturlash_ai_", suffix=".sqlite3")
        os.close(fd)
        target = Path(name)
        async with aiosqlite.connect(self.settings.db_path) as source:
            async with aiosqlite.connect(target) as destination:
                await source.backup(destination)
        return target

    async def send_backup(self, chat_id: int | None = None) -> None:
        target = await self.create_backup()
        try:
            await self.bot.send_document(chat_id or self.settings.backup_chat_id, FSInputFile(target, filename="dasturlash_ai_backup.sqlite3"), caption="💾 <b>DATABASE BACKUP</b>\n[ OK ] Zaxira nusxa tayyor.")
        finally:
            await asyncio.to_thread(target.unlink, missing_ok=True)
