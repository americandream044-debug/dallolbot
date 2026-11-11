"""Rate-limit-aware Telegram message effects."""
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

T = TypeVar("T")
SPINNERS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
LOADING_LINES = (
    "decrypting prompt matrix...",
    "compiling words...",
    "optimizing neural output...",
)


async def safe_edit(message: Message, text: str, **kwargs: object) -> None:
    """Edit a message while tolerating Telegram's common edit errors."""
    try:
        await message.edit_text(text, **kwargs)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(min(float(exc.retry_after), 2.0))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def boot_sequence(message: Message, enabled: bool = True) -> None:
    """Show a three-frame boot sequence lasting less than four seconds."""
    if not enabled:
        return
    frames = (
        "<pre>[ OK ] loading modules...</pre>",
        "<pre>[ OK ] connecting AI core...</pre>",
        "<pre>[ OK ] ACCESS GRANTED ✅</pre>",
    )
    for frame in frames:
        await safe_edit(message, frame)
        await asyncio.sleep(1.0)


async def run_with_loading(message: Message, operation: Awaitable[T], enabled: bool = True) -> T:
    """Run an awaitable while updating a loading card at most once per second."""
    task = asyncio.create_task(operation)
    try:
        if enabled:
            for index in range(3):
                if task.done():
                    break
                pct = (index + 1) * 25
                line = LOADING_LINES[index % len(LOADING_LINES)]
                await safe_edit(
                    message,
                    f"<pre>{SPINNERS[index * 3]} AI CORE / PROCESSING\n{line}\n{'▓' * ((index + 1) * 2)}{'░' * (10 - (index + 1) * 2)} {pct}%</pre>",
                )
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
        return await task
    except Exception:
        if not task.done():
            task.cancel()
        raise


async def typewriter(message: Message, text: str, enabled: bool = True) -> None:
    """Reveal a short response in three chunks rather than character-by-character."""
    if not enabled or len(text) < 100:
        await safe_edit(message, text)
        return
    size = max(1, len(text) // 3)
    for end in (size, size * 2, len(text)):
        await safe_edit(message, text[:end] + (" ▌" if end < len(text) else ""))
        if end < len(text):
            await asyncio.sleep(1.0)


async def glitch_title(message: Message, title: str, enabled: bool = True) -> None:
    """Briefly flicker a title, then restore its clean form."""
    if not enabled or len(title) < 5:
        await safe_edit(message, title)
        return
    chars = list(title)
    for _ in range(2):
        altered = chars.copy()
        for _ in range(min(2, max(1, len(chars) // 12))):
            idx = random.randrange(len(altered))
            altered[idx] = random.choice("#$%&*@")
        await safe_edit(message, "".join(altered))
        await asyncio.sleep(1.0)
    await safe_edit(message, title)


async def stamp(message: Message, success: bool, enabled: bool = True) -> None:
    """Show a compact success/failure stamp."""
    if enabled:
        label = "[ DEPLOYED ✅ ]" if success else "[ ACCESS DENIED ⛔ ]"
        await safe_edit(message, f"<pre>{label}</pre>")
